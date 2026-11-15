import json
import os
from bisect import bisect
from functools import partial

from arena.opponents import Base
from arena.realfield import REAL, klass
from pokerbot.preflop import percentile
from pokerbot.state import Action

STACK = 2000
BET_EDGES = (0.22, 0.42, 0.62, 0.88, 1.3)
FACE_EDGES = (0.36, 0.68, 1.2)
PRE = ("f", "c", "r", "j")
BETS = ("x", "b0", "b1", "b2", "b3", "b4", "b5")
ANSWERS = ("f", "c", "r0", "r1", "r2")
GRID = 50
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clone_profiles.json")
def opener_group(left):
    """The raiser's seat by the seats still to act behind it: early, middle, button, blind."""
    return 0 if left >= 5 else 1 if left >= 3 else 2 if left == 2 else 3


def bet_group(rate):
    """A player by how often it bets when nobody has bet yet: under 45%, to 65%, to 85%, more."""
    return 0 if rate < 0.45 else 1 if rate < 0.65 else 2 if rate < 0.85 else 3


def bucket(x, edges):
    k = 0
    for e in edges:
        if x >= e:
            k += 1
    return k


class Track:
    """Follows one hand record by record and names the situation a player is in (the key of a profile row)."""

    def __init__(self, order, bb=20, stack=STACK):
        self.order = list(order)
        self.n = len(self.order)
        self.bb = bb
        self.stack = stack
        self.street = 0
        self.level = 0
        self.raises = 0
        self.pot = 0
        self.bets = {}
        self.paid = {}
        self.folded = set()
        self.limpers = set()
        self.raisers = set()
        self.called = set()
        self.checked = set()
        self.bettors = set()
        self.agg = None
        self.prev_agg = None
        self.now_called = set()
        self.prev_called = set()
        self.fed = 0

    def enter(self, street):
        if street != self.street:
            self.prev_called = set(self.called) if self.street == 0 else self.now_called
            self.now_called = set()
            self.street = street
            self.prev_agg = self.agg
            self.agg = None
            self.level = 0
            self.raises = 0
            self.bets = {}
            self.checked = set()
            self.bettors = set()

    def feed(self, r):
        self.fed += 1
        self.enter(r.street)
        p, k = r.player, r.kind
        prev = self.bets.get(p, 0)
        if k == "fold":
            self.folded.add(p)
            return
        if k == "check":
            self.checked.add(p)
            return
        add = r.to - prev if k != "call" else r.amount
        self.bets[p] = prev + add
        self.paid[p] = self.paid.get(p, 0) + add
        self.pot += add
        if k == "raise":
            self.raises += 1
            self.level = self.bets[p]
            self.agg = p
            self.bettors.add(p)
            if self.street == 0:
                self.raisers.add(p)
        elif k == "call":
            if self.street == 0:
                (self.called if self.raises else self.limpers).add(p)
            else:
                self.now_called.add(p)
        else:
            self.level = max(self.level, self.bets[p])

    def left(self, p):
        return self.n - 1 - (self.order.index(p) - 2) % self.n

    def key(self, p):
        level = self.level
        mine = self.bets.get(p, 0)
        if self.street == 0:
            left = self.left(p)
            if not self.raises:
                if not self.limpers:
                    return "o%d" % min(left, 5)
                return "lb" if left == 0 else "ls" if left == 1 else "lo"
            # facing an all-in is its own row: there a raise is not on offer
            big = "a" if level - mine >= self.stack - self.paid.get(p, 0) else "j" if level >= 40 * self.bb else "n"
            if p in self.raisers:
                if self.raises == 2:
                    return "r" + (big if big != "n" else "s" if level <= 3.2 * mine else "b")
                return "f" + big
            if self.raises == 1:
                pos = "b" if left == 0 else "s" if left == 1 else "l" if p in self.limpers else "i"
                bbs = level / self.bb
                return "v" + pos + ("a" if big == "a" else "s" if bbs <= 2.5 else "m" if bbs <= 4 else "l" if bbs <= 8
                                    else "x" if bbs < 25 else "j")
            return ("s" if p in self.called else "c" if self.raises == 2 else "d") + big
        st = self.street
        if not self.raises:
            live = [q for q in self.order if q not in self.folded]
            line = "a" if self.prev_agg == p else "k" if self.prev_agg is not None else "n"
            return "B%d%s%s%s" % (st, line, "h" if len(live) == 2 else "m", "i" if live and live[-1] == p else "o")
        to_call = level - mine
        frac = to_call / max(1, self.pot - to_call)
        shove = to_call >= self.stack - self.paid.get(p, 0)
        if p not in self.bettors:
            # how the player got here: led the street before, called a bet or raise on it, or neither
            line = "a" if self.prev_agg == p else "c" if p in self.prev_called else "n"
            return "C%d%d%s%s" % (st, 4 if shove else bucket(frac, FACE_EDGES), "x" if p in self.checked else "d", line)
        return "E%d%d" % (st, 3 if shove else 0 if frac < 0.5 else 1 if frac < 1.0 else 2)

    def label(self, r):
        """The action's label within its row, the menu its size belongs to, and the size."""
        p, k = r.player, r.kind
        prev = self.bets.get(p, 0)
        if self.street == 0:
            if k != "raise":
                return ("f" if k == "fold" else "c"), None, None
            if r.to >= 0.75 * (prev + self.stack - self.paid.get(p, 0)):
                return "j", None, None
            if not self.raises:
                return "r", "o" if not self.limpers else "l", round(r.to / self.bb * 2) / 2
            return "r", "m%d" % min(self.raises, 3), round(r.to / max(1, self.level), 1)
        if not self.raises:
            if k != "raise":
                return "x", None, None
            frac = r.to / max(1, self.pot)
            return "b%d" % bucket(frac, BET_EDGES), "b%d" % self.street, round(min(frac, 6.0) * 50) / 50
        if k != "raise":
            return ("f" if k == "fold" else "c"), None, None
        frac = (r.to - self.level) / max(1, self.pot + self.level - prev)
        return "r%d" % (0 if frac < 0.6 else 1 if frac < 1.5 else 2), "r%d" % self.street, round(min(frac, 6.0) * 20) / 20


def labels_for(key):
    return PRE if key[0] not in "BCE" else BETS if key[0] == "B" else ANSWERS


_PROFILES = {}


def profiles(path=PATH):
    if path not in _PROFILES:
        with open(path) as f:
            _PROFILES[path] = json.load(f)["teams"]
    return _PROFILES[path]


def cumulate(row):
    out, t = [], 0.0
    for x in row:
        t += x
        out.append(t)
    return out


class Clone(Base):
    """A stand-in driven by a team's profile: action frequencies per situation, split by hand class after the flop
    and by where the hand sits in the range it arrived with before it."""

    def __init__(self, team="field", seed=0, profile=None):
        super().__init__(seed)
        prof = profile or profiles()[team]
        self.pre = prof["pre"]
        self.pi = prof.get("pi", 0.0)
        self.ordered = prof.get("ordered", False)
        self.vpos = prof.get("vpos")
        self.adapt = prof.get("adapt")
        self.seen = {}
        self.rank = None
        self.post = {k: [cumulate(row) for row in rows] for k, rows in prof["post"].items()}
        self.menu = {k: (v[0], cumulate(v[1])) for k, v in prof["menu"].items()}
        self.hand = None
        self.track = None
        self.w = None
        self.pct = 0.5

    def size(self, name, default):
        m = self.menu.get(name)
        if not m or not m[0]:
            return default
        vals, cum = m
        return vals[min(bisect(cum, self.rng.random() * cum[-1]), len(vals) - 1)]

    def sync(self, s):
        t = self.track
        if t is None or self.hand != s.hand_id or t.fed > len(s.history) or t.order != s.players:
            t = self.track = Track(s.players, s.big_blind)
            self.hand = s.hand_id
            self.w = [1.0] * GRID
            self.rank = None
            self.pct = percentile(*s.hole)
        for r in s.history[t.fed:]:
            t.feed(r)
        t.enter(s.street)
        return t

    def band(self, row, key, q):
        f, c, r, j = row
        v = r * (1.0 - self.pi) if key[0] in "vc" else r
        top = j + v
        if q < top:
            return (0.0, 0.0, v / top, j / top)
        if q < top + c:
            return (0.0, 1.0, 0.0, 0.0)
        rest = 1.0 - top - c
        t = min(1.0, (r - v) / rest) if rest > 1e-9 else 0.0
        return (1.0 - t, 0.0, t, 0.0)

    def preflop(self, s, t, key):
        row = self.pre.get(key) or self.pre.get(key[0]) or (0.8, 0.15, 0.04, 0.01)
        if self.vpos and key[0] == "v" and len(t.raisers) == 1:
            # real teams answer a button raise far more often than an early one; the rows do not know the raiser's seat
            m = self.vpos[opener_group(t.left(next(iter(t.raisers))))]
            row = [x * y for x, y in zip(row, m)]
            tot = sum(row)
            row = [x / tot for x in row]
        w = self.w
        tot = sum(w) or 1.0
        x = self.pct * GRID
        cell = min(GRID - 1, int(x))
        q = (sum(w[:cell]) + w[cell] * (x - cell)) / tot
        probs = self.band(row, key, q)
        u = self.rng.random()
        a = 0
        while a < 3 and u >= probs[a]:
            u -= probs[a]
            a += 1
        can = s.max_raise_to > s.my_bet + s.to_call
        if a >= 2 and not can:
            a = 1
        if a == 0 and s.to_call <= 0:
            a = 1
        if a:
            acc = 0.0
            new = []
            for wi in w:
                new.append(wi * self.band(row, key, (acc + wi / 2) / tot)[a])
                acc += wi
            if sum(new) > 1e-9:
                self.w = new
        if a == 0:
            return Action("fold")
        if a == 1:
            return Action("call") if s.to_call > 0 else Action("check")
        if a == 3:
            return Action("raise", s.max_raise_to)
        level = s.my_bet + s.to_call
        if not t.raises:
            to = self.size("l" if t.limpers else "o", 3.0) * s.big_blind
        else:
            to = self.size("m%d" % min(t.raises, 3), 3.0) * level
        return Action("raise", to)

    def postflop(self, s, t, key):
        rows = self.post.get(key)
        if not rows and key[0] == "C":
            rows = next((self.post[k] for k in (key[:4] + x for x in "nca") if k in self.post), None)
        labels = labels_for(key)
        if not rows:
            return Action("check") if s.to_call <= 0 else Action("fold")
        cum = rows[klass(s.hole, s.board)]
        if self.adapt and labels[0] == "f" and cum[0] > 0.0:
            cum = self.adapted(cum, t)
        x = self.rng.random() * cum[-1]
        if labels[0] == "f" and self.ordered:
            # an assumption, not a fit: within a hand class the folds are the hands that stood lowest before the flop
            if self.rank is None:
                w = self.w
                cell = min(GRID - 1, int(self.pct * GRID))
                self.rank = 1.0 - (sum(w[:cell]) + w[cell] * (self.pct * GRID - cell)) / (sum(w) or 1.0)
            pf = cum[0] / cum[-1]
            if self.rank < pf:
                x = 0.0
            else:
                x = cum[0] + self.rng.random() * (cum[-1] - cum[0])
                # what did not fold is spread over the whole scale again for the next decision
                self.rank = (self.rank - pf) / (1.0 - pf) if pf < 1.0 else 1.0
        lab = labels[min(bisect(cum, x), len(labels) - 1)]
        if lab == "x":
            return Action("check")
        if lab in ("f", "c"):
            return Action("fold" if lab == "f" else "call")
        if lab[0] == "b":
            mid = (0.15, 0.33, 0.5, 0.75, 1.0, 2.0)[int(lab[1])]
            return Action("raise", self.size("b%d%s" % (s.street, lab), mid) * s.pot)
        mid = (0.4, 1.0, 2.5)[int(lab[1])]
        frac = self.size("r%d%s" % (s.street, lab), mid)
        return Action("raise", s.my_bet + s.to_call + frac * (s.pot + s.to_call))

    def adapted(self, cum, t):
        """Folds less to a player who has bet nearly every time this round and more to one who rarely does."""
        c = self.seen.get(t.agg)
        if c is None or c[1] < 30:
            return cum
        m = self.adapt[t.street - 1][bet_group(c[0] / c[1])]
        f = cum[0] / cum[-1]
        g = f * m / (f * m + 1.0 - f)
        k = (1.0 - g) / (1.0 - f) if f < 1.0 else 1.0
        return [g * cum[-1]] + [(g + (x / cum[-1] - f) * k) * cum[-1] for x in cum[1:]]

    def end_hand(self, history, showdown, board=()):
        street = 0
        bet = False
        for r in history:
            if r.street != street:
                street = r.street
                bet = False
            if street and not bet and r.kind in ("check", "raise"):
                c = self.seen.setdefault(r.player, [0, 0])
                c[1] += 1
                c[0] += r.kind == "raise"
            if r.kind == "raise":
                bet = True

    def decide(self, s):
        try:
            t = self.sync(s)
            key = t.key(s.hero)
            a = self.preflop(s, t, key) if not s.board else self.postflop(s, t, key)
        except Exception:
            a = Action("check")
        return self.legal(s, a)

    def legal(self, s, a):
        if a.kind == "raise":
            if s.max_raise_to > s.my_bet + s.to_call and s.max_raise_to >= s.min_raise_to > 0:
                return Action("raise", max(s.min_raise_to, min(int(a.amount), s.max_raise_to)))
            return Action("call") if s.to_call > 0 else Action("check")
        if s.to_call <= 0:
            return Action("check")
        return Action("call") if a.kind == "call" else Action("fold")


def short_names(path=PATH):
    try:
        return {v["short"]: k for k, v in profiles(path).items()}
    except Exception:
        return {}


CLONES = {"clone_" + short: partial(Clone, team) for short, team in short_names().items()}
REAL.update(CLONES)
