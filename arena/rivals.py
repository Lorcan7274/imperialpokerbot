import random
from collections import defaultdict
from itertools import accumulate

from arena.opponents import Base
from pokerbot.cards import evaluate
from pokerbot.state import Action

RANKS = "23456789TJQKA"


def _raisable(s):
    return s.max_raise_to > s.my_bet + s.to_call


class KitStarter(Base):
    """Port of the kit's starter bot.py: raises any pair or king-high-or-better hole cards on every street, otherwise calls up to two big blinds."""

    def decide(self, s):
        ranks = sorted(c >> 2 for c in s.hole)
        strong = ranks[0] == ranks[1] or ranks[1] >= 11
        if strong and _raisable(s):
            return Action("raise", min(s.min_raise_to + s.pot // 2, s.max_raise_to))
        if not s.to_call:
            return Action("check")
        if s.to_call <= s.big_blind * 2 or strong:
            return Action("call")
        return Action("fold")


class KitStation(Base):
    """Port of examples/calling_station.py: never folds, never raises."""

    def decide(self, s):
        return Action("call") if s.to_call else Action("check")


class KitRandom(Base):
    """Port of examples/random_bot.py: a uniformly random legal action, raising to at most three times the minimum."""

    def decide(self, s):
        legal = ["fold", "call"] if s.to_call else ["check"]
        if _raisable(s):
            legal.append("raise")
        action = self.rng.choice(legal)
        if action == "raise":
            lo, hi = s.min_raise_to, s.max_raise_to
            return Action("raise", self.rng.randint(lo, min(hi, lo * 3)))
        return Action(action)


def _kit_strength(hole):
    a, b = sorted((c >> 2 for c in hole), reverse=True)
    if a == b:
        return 0.5 + a / 24
    return (a + b) / 24 + (0.06 if (hole[0] & 3) == (hole[1] & 3) else 0) - (0.04 if a - b > 4 else 0)


class KitTag(Base):
    """Port of examples/tight_aggressive.py: raises strong starting hands, calls small raises with decent ones, bets or calls any pair after the flop."""

    def decide(self, s):
        can = _raisable(s)
        bb = s.big_blind
        if not s.board:
            x = _kit_strength(s.hole)
            if s.my_stack <= 10 * bb and x >= 0.62 and can:
                return Action("raise", s.max_raise_to)
            if x >= 0.8 and can:
                return Action("raise", min(s.max_raise_to, s.min_raise_to + 2 * bb))
            if x >= 0.62 and s.to_call <= 3 * bb:
                return Action("call") if s.to_call else Action("check")
        else:
            ranks = [c >> 2 for c in s.hole + s.board]
            if any(ranks.count(c >> 2) >= 2 for c in s.hole):
                if can and s.to_call == 0:
                    return Action("raise", min(s.max_raise_to, s.min_raise_to + s.pot // 2))
                return Action("call") if s.to_call else Action("check")
        return Action("fold") if s.to_call else Action("check")


ORDER = (
    "AA KK QQ JJ TT 99 AKs 88 AQs AJs AKo 77 ATs KQs AQo KJs A9s AJo A8s KTs A7s 66 ATo QJs KQo "
    "A5s KJo K9s QTs A6s A9o A4s K8s JTs A8o 55 KTo A3s QJo Q9s A2s K7s A7o K6s J9s K9o A6o A5o "
    "QTo K5s Q8s 44 T9s A4o K8o K4s JTo Q9o A3o K3s Q7s J8s K7o Q6s A2o K2s T8s K6o Q5s J9o J7s "
    "33 Q8o K5o T9o 98s Q4s K4o Q3s J6s T7s Q2s Q7o J5s J8o K3o 97s J4s Q5o Q6o T6s K2o 87s T8o "
    "J7o 22 J3s Q4o J2s 98o 96s T5s T4s 86s Q3o T7o J6o 76s 97o Q2o T3s 95s J5o T6o 87o J4o T2s "
    "65s 85s 75s J3o 94s 93s 96o T5o 84s 54s 92s J2o 86o T4o 74s 64s 76o T3o 95o 83s 85o 82s 53s "
    "T2o 43s 73s 94o 63s 65o 75o 93o 52s 72s 84o 54o 62s 92o 64o 32s 42s 74o 83o 53o 82o 43o 63o "
    "73o 72o 52o 62o 32o 42o").split()


def hand_key(a, b):
    ra, rb = a >> 2, b >> 2
    if ra < rb:
        ra, rb = rb, ra
    return ra * 13 + rb if ra == rb or (a & 3) == (b & 3) else rb * 13 + ra


def _name_key(name):
    hi, lo = RANKS.index(name[0]), RANKS.index(name[1])
    return lo * 13 + hi if name.endswith("o") else hi * 13 + lo


def _percentiles():
    pct = [1.0] * 169
    seen = 0
    for name in ORDER:
        size = 6 if len(name) == 2 else 4 if name[2] == "s" else 12
        pct[_name_key(name)] = (seen + size / 2) / 1326
        seen += size
    return pct


PCT = _percentiles()


def _straight(mask):
    m = mask << 1 | mask >> 12 & 1
    return m & m >> 1 & m >> 2 & m >> 3 & m >> 4


def _pair_class(r, h0, h1, tops):
    if h0 == h1:
        if r > tops[0]:
            return 4
        return 2 if len(tops) > 1 and r > tops[1] else 1
    if r == tops[0]:
        return 4 if (h1 if h0 == r else h0) >= 9 else 3
    return 2 if len(tops) > 1 and r == tops[1] else 1


def made(hole, board):
    """0 nothing, 1 weak pair, 2 middle pair, 3 top pair weak kicker, 4 top pair good kicker or overpair, 5 two pair, 6 trips or a one-card straight, 7 straight or flush, 8 full house or better."""
    cards = hole + board
    if len(board) == 5 and evaluate(cards) == evaluate(board):
        return 0
    rc = [0] * 13
    brc = [0] * 13
    mask = bmask = 0
    for c in cards:
        rc[c >> 2] += 1
        mask |= 1 << (c >> 2)
    for c in board:
        brc[c >> 2] += 1
        bmask |= 1 << (c >> 2)
    h0, h1 = hole[0] >> 2, hole[1] >> 2
    quads = [r for r in range(13) if rc[r] == 4]
    trips = [r for r in range(13) if rc[r] == 3]
    pairs = [r for r in range(13) if rc[r] == 2]
    if quads:
        return 8 if brc[quads[0]] < 4 else 0
    if trips and (pairs or len(trips) > 1):
        return 6 if brc[trips[-1]] == 3 else 8
    for su in range(4):
        mine = [c >> 2 for c in hole if c & 3 == su]
        on_board = sum(1 for c in board if c & 3 == su)
        if mine and on_board + len(mine) >= 5:
            return 7 if on_board <= 3 or max(mine) >= 10 else 4
    if _straight(mask):
        return 6 if any(_straight(bmask | 1 << r) for r in range(13)) else 7
    if trips:
        if brc[trips[0]] == 3:
            return 1 if max(h0, h1) >= 11 else 0
        return 6
    tops = sorted({c >> 2 for c in board}, reverse=True)
    mine = [r for r in pairs if brc[r] < 2]
    if not mine:
        return 0
    if len(pairs) >= 2 and brc[pairs[-1]] < 2 and brc[pairs[-2]] < 2:
        return 5
    return _pair_class(max(mine), h0, h1, tops)


def draws(hole, board):
    """Outs to a flush or straight that use a hole card: 9 for a flush draw, 4 per straight card."""
    cards = hole + board
    outs = 0
    for su in {hole[0] & 3, hole[1] & 3}:
        if sum(1 for c in cards if c & 3 == su) == 4:
            outs = 9
    mask = bmask = 0
    for c in cards:
        mask |= 1 << (c >> 2)
    for c in board:
        bmask |= 1 << (c >> 2)
    if not _straight(mask):
        for r in range(13):
            if not mask >> r & 1 and _straight(mask | 1 << r) and not _straight(bmask | 1 << r):
                outs += 4
    return outs


def random_equity(hole, board, k, rng, trials):
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    won = 0.0
    for _ in range(trials):
        d = rng.sample(deck, need + 2 * k)
        full = board + d[:need]
        hv = evaluate(hole + full)
        res = 1.0
        for j in range(need, need + 2 * k, 2):
            v = evaluate(d[j:j + 2] + full)
            if v > hv:
                res = 0.0
                break
            if v == hv:
                res = 0.5
        won += res
    return won / trials


def R(spec):
    out = set()
    for tok in spec.replace(" ", "").split(","):
        if not tok:
            continue
        first, _, last = tok.partition("-")
        plus = first.endswith("+")
        first = first.rstrip("+")
        hi, lo = RANKS.index(first[0]), RANKS.index(first[1])
        kind = first[2:]
        if last:
            end = RANKS.index(last[1])
            lows = range(min(lo, end), max(lo, end) + 1)
        elif plus:
            lows = range(lo, 13 if hi == lo else hi)
        else:
            lows = (lo,)
        for x in lows:
            if hi == lo:
                out.add(x * 14)
            else:
                if kind != "o":
                    out.add(hi * 13 + x)
                if kind != "s":
                    out.add(x * 13 + hi)
    return frozenset(out)


class Chart:
    def __init__(self, **kw):
        for name, spec in kw.items():
            setattr(self, name, R(spec) if isinstance(spec, str) else [R(x) for x in spec])


COMBOS = sorted(((a, b) for a in range(52) for b in range(a)), key=lambda c: (PCT[hand_key(*c)], c))
NC = len(COMBOS)
GRID = 130
_EDGE = [NC * (k / GRID) ** 1.8 for k in range(GRID + 1)]


class Grid:
    """A per-hand sample of the hands an opponent can hold, denser among strong hands, each weighted by the share of hands it stands for."""

    def __init__(self, hole, rng):
        h0, h1 = hole
        rnd = rng.random
        self.combos = combos = []
        self.pct = pct = []
        self.mass = mass = []
        for k in range(GRID):
            lo, hi = _EDGE[k], _EDGE[k + 1]
            i = int(lo + rnd() * (hi - lo))
            a, b = COMBOS[i]
            if a != h0 and a != h1 and b != h0 and b != h1:
                combos.append((a, b))
                pct.append(i / NC)
                mass.append(hi - lo)
        self.n = len(combos)
        self._streets = {}

    def on(self, board):
        hit = self._streets.get(len(board))
        if hit is None:
            dead = set(board)
            vals = [-1 if a in dead or b in dead else evaluate([a, b] + board) for a, b in self.combos]
            order = sorted((i for i in range(self.n) if vals[i] >= 0), key=vals.__getitem__, reverse=True)
            hit = self._streets[len(board)] = (vals, order)
        return hit


def shape(w, order, lo, hi, inner, floor):
    total = 0.0
    for i in order:
        total += w[i]
    if total <= 0:
        return
    cum = 0.0
    for i in order:
        x = w[i]
        if x:
            mid = (cum + 0.5 * x) / total
            cum += x
            if mid < lo:
                w[i] = x * inner
            elif mid > hi:
                w[i] = x * floor


_TOPS = (0.015, 0.03, 0.05, 0.08, 0.12, 0.18, 0.27, 0.4, 0.6, 1.0)
_ALLIN = {}


def _allin(key, i):
    hit = _ALLIN.get((key, i))
    if hit is None:
        rng = random.Random(key * 16 + i)
        a, b = divmod(key, 13)
        hole = [a * 4, b * 4 + (0 if a > b else 1)]
        pool = [c for c in COMBOS[:max(6, int(_TOPS[i] * NC))] if c[0] not in hole and c[1] not in hole]
        deck = [c for c in range(52) if c not in hole]
        won = 0.0
        for _ in range(600):
            x, y = pool[int(rng.random() * len(pool))]
            board = []
            while len(board) < 5:
                c = deck[int(rng.random() * 50)]
                if c != x and c != y and c not in board:
                    board.append(c)
            u, w = evaluate(hole + board), evaluate([x, y] + board)
            won += 1.0 if u > w else 0.5 if u == w else 0.0
        hit = _ALLIN[(key, i)] = won / 600
    return hit


def allin_eq(hole, frac):
    """All-in equity before the flop against a hand drawn from the top `frac` of ORDER; cached, seeded by hand so it never depends on who asked first."""
    key = hand_key(*hole)
    if frac <= _TOPS[0]:
        return _allin(key, 0)
    for i in range(1, len(_TOPS)):
        if frac <= _TOPS[i]:
            t = (frac - _TOPS[i - 1]) / (_TOPS[i] - _TOPS[i - 1])
            return (1.0 - t) * _allin(key, i - 1) + t * _allin(key, i)
    return _allin(key, len(_TOPS) - 1)


def wetness(board):
    suits = [0] * 4
    for c in board:
        suits[c & 3] += 1
    ranks = sorted({c >> 2 for c in board})
    close = sum(1 for i in range(len(ranks) - 1) if ranks[i + 1] - ranks[i] <= 2)
    top = max(suits)
    return (2 if top >= 3 else 1 if top == 2 and len(board) == 3 else 0) + (1 if close >= 2 else 0)


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Stats:
    """Per-opponent counters read from each finished hand: how often they enter, raise, re-raise, call all-ins, bet when checked to and fold to bets."""

    def __init__(self):
        self.c = defaultdict(int)
        self.jam = 800
        self.players = None

    def rate(self, num, den, prior, k):
        c = self.c
        return (c.get(num, 0) + prior * k) / (c.get(den, 0) + k)

    def observe(self, hist):
        c = self.c
        jam = self.jam
        group = {}
        players = self.players
        if players and hist[0].player in players:
            i = players.index(hist[0].player)
            order = players[i:] + players[:i]
            for j, p in enumerate(order):
                group[p] = 2 if j == 0 else 3 if j == 1 else 0 if len(order) - 1 - j <= 2 else 1
        street = nr = level = 0
        raised = set()
        entered = set()
        seen = set()
        init = aggr = pfa = None
        for r in hist:
            p, k = r.player, r.kind
            if r.street != street:
                init = aggr if street else pfa
                street = r.street
                nr = 0
                aggr = None
            if k == "sb" or k == "bb":
                level = max(level, r.to)
                continue
            if street == 0:
                if p not in seen:
                    seen.add(p)
                    c[p, "hands"] += 1
                g = group.get(p, 1)
                if nr == 0:
                    c[p, "uo"] += 1
                    c[p, "uo", g] += 1
                    if k == "raise":
                        c[p, "uo_r"] += 1
                        c[p, "uo_r", g] += 1
                    elif k == "call":
                        c[p, "uo_c"] += 1
                else:
                    tag = "f3" if p in raised else "fr"
                    c[p, tag] += 1
                    c[p, tag + "_" + k[0]] += 1
                    if tag == "fr":
                        c[p, "fr", g] += 1
                        if k == "fold":
                            c[p, "fr_f", g] += 1
                    if level >= jam:
                        c[p, "fj"] += 1
                        if k != "fold":
                            c[p, "fj_c"] += 1
                if k == "raise":
                    nr += 1
                    raised.add(p)
                    pfa = p
                    level = r.to
                    if r.to >= jam:
                        c[p, "jam"] += 1
                if k == "call" or k == "raise":
                    entered.add(p)
            else:
                if nr == 0:
                    c[p, "nb", street, p == init] += 1
                    if k == "raise":
                        c[p, "nb_b", street, p == init] += 1
                else:
                    c[p, "vb", street] += 1
                    c[p, "vb_" + k[0], street] += 1
                if k == "raise":
                    nr += 1
                    aggr = p
        for p in entered:
            c[p, "vpip"] += 1
        for p in raised:
            c[p, "pfr"] += 1


class View:
    def __init__(self, s):
        me = s.hero
        hist = s.history
        n = len(s.players)
        self.bb = s.big_blind
        self.stack0 = (s.pot + sum(s.stacks.values())) // n
        self.jam = jam = 0.4 * self.stack0
        self.sbp = hist[0].player
        self.bbp = hist[1].player
        self.raises = raises = []
        self.labels = labels = {}
        self.acts = acts = []
        self.aggr = aggr = {}
        self.my_aggr = my_aggr = set()
        bets = {}
        limpers = callers = my_raises = 0
        street = nr = level = pot = 0
        pfa = None
        for r in hist:
            p, k = r.player, r.kind
            if r.street != street:
                street = r.street
                nr = level = 0
                bets = {}
            if street == 0:
                if k == "raise":
                    nr += 1
                    raises.append((p, r.to))
                    labels[p] = "jam" if r.to >= jam else ("open", "3bet", "4bet")[min(nr, 3) - 1]
                    callers = 0
                    pfa = p
                    if p == me:
                        my_raises += 1
                elif k == "call":
                    if nr:
                        callers += 1
                        labels[p] = ("calljam" if level >= jam else "limpcall" if nr == 1 and labels.get(p) == "limp"
                                     else ("call", "call3", "call4")[min(nr, 3) - 1])
                    else:
                        limpers += 1
                        labels[p] = "limp"
                elif k == "check":
                    labels[p] = "check"
            elif k == "raise":
                init = aggr.get(street - 1) if street > 1 else pfa
                acts.append((p, street, "raise" if nr else "bet", r.amount / pot, p == init))
                nr += 1
                aggr[street] = p
                if p == me:
                    my_aggr.add(street)
            elif k != "fold":
                init = aggr.get(street - 1) if street > 1 else pfa
                acts.append((p, street, k, r.amount / pot if k == "call" else 0.0, p == init))
            if k != "fold" and k != "check":
                bets[p] = r.to
                if r.to > level:
                    level = r.to
            pot += r.amount
        st = s.street
        if street != st:
            nr = level = 0
            bets = {}
        self.limpers, self.callers, self.my_raises = limpers, callers, my_raises
        self.pfa = pfa
        self.nr = nr
        self.level = level
        self.bets = bets
        self.init = (aggr.get(st - 1) if st > 1 else pfa) if st else None
        self.behind = sum(1 for v in s.active if v != me and bets.get(v, 0) < level and s.stacks[v] > 0)
        self.checked = any(a[0] == me and a[1] == st and a[2] == "check" for a in acts)
        self.is_sb = me == self.sbp
        self.is_bb = me == self.bbp
        self.pos = n - 1 - s.players.index(me)


_OPEN_W = (0.44, 0.28, 0.21, 0.16, 0.13, 0.11)
_BANDS = {
    "3bet": (0.0, 0.06, 1.0, 0.05), "4bet": (0.0, 0.03, 1.0, 0.03), "jam": (0.0, 0.05, 1.0, 0.03),
    "call": (0.025, 0.24, 0.35, 0.08), "limpcall": (0.05, 0.5, 0.3, 0.15), "call3": (0.012, 0.13, 0.4, 0.04),
    "call4": (0.0, 0.05, 1.0, 0.03), "calljam": (0.0, 0.06, 1.0, 0.03),
    "limp": (0.08, 0.6, 0.3, 0.3), "check": (0.07, 1.0, 0.3, 1.0)}
_BET_F = ((0.33, 0.33, 0.33), (0.6, 0.5, 0.45))
_RAISE_F = (0.10, 0.09, 0.07)
_FOLD_F = (0.42, 0.45, 0.5)
_BET_FLOOR = (0.30, 0.22, 0.14)
_RAISE_FLOOR = (0.12, 0.08, 0.05)


class Rival(Base):
    trials = 70
    track = False

    def __init__(self, seed=0):
        super().__init__(seed)
        self._tag = None
        self._grid = None
        self.stats = Stats() if self.track else None

    def decide(self, s):
        v = View(s)
        if self.stats:
            self.stats.jam, self.stats.players = v.jam, s.players
        return self.post(s, v) if s.board else self.pre(s, v)

    def end_hand(self, history, showdown):
        if self.stats:
            self.stats.observe(history)

    def grid(self, s):
        tag = (s.hand_id, s.hole[0], s.hole[1])
        if tag != self._tag:
            self._tag = tag
            self._grid = Grid(s.hole, self.rng)
        return self._grid

    def freq(self, p, kind, st, init):
        if kind == "bet":
            return _BET_F[init][st - 1]
        return (_RAISE_F if kind == "raise" else _FOLD_F)[st - 1]

    def pre_band(self, s, v, p):
        lab = v.labels.get(p, "check")
        if lab == "open":
            if p == v.sbp:
                return 0.0, 0.36, 1.0, 0.06
            if p == v.bbp:
                return 0.0, 0.12, 1.0, 0.06
            return 0.0, _OPEN_W[min(len(s.players) - 1 - s.players.index(p), 5)], 1.0, 0.06
        if lab == "call" and p == v.bbp:
            return 0.03, 0.5, 0.3, 0.1
        return _BANDS[lab]

    def narrow(self, w, order, p, st, kind, frac, init):
        f = self.freq
        if kind == "bet":
            x = clamp(f(p, "bet", st, init) * (0.66 / max(frac, 0.25)) ** 0.5, 0.08, 0.95)
            shape(w, order, 0.0, x, 1.0, _BET_FLOOR[st - 1])
        elif kind == "raise":
            shape(w, order, 0.0, 1.3 * f(p, "raise", st, init), 1.0, _RAISE_FLOOR[st - 1])
        elif kind == "call":
            ff = clamp(f(p, "fold", st, init) * (frac / 0.4) ** 0.5, 0.05, 0.9)
            shape(w, order, f(p, "raise", st, init), 1.0 - ff, 0.55, 0.06)
        elif init:
            shape(w, order, 0.8 * f(p, "bet", st, True), 1.0, 0.4, 1.0)

    def weights(self, s, v, p):
        grid = self.grid(s)
        lo, hi, top, leak = self.pre_band(s, v, p)
        w = [m * (top if x < lo else 1.0 if x <= hi else leak) for m, x in zip(grid.mass, grid.pct)]
        board = s.board
        for q, st, kind, frac, init in v.acts:
            if q == p:
                self.narrow(w, grid.on(board[:st + 2])[1], p, st, kind, frac, init)
        for i, x in enumerate(grid.on(board)[0]):
            if x < 0:
                w[i] = 0.0
        return w

    def ranges(self, s, v):
        return [self.weights(s, v, p) for p in s.active if p != s.hero]

    def equity(self, s, ws):
        grid = self.grid(s)
        board = s.board
        hole = s.hole
        if len(board) == 5:
            vals = grid.on(board)[0]
            hv = evaluate(hole + board)
            eq = 1.0
            for w in ws:
                won = tot = 0.0
                for x, y in zip(w, vals):
                    if x:
                        tot += x
                        if hv > y:
                            won += x
                        elif hv == y:
                            won += 0.5 * x
                eq *= won / tot if tot else 0.5
            return eq
        combos = grid.combos
        trials = self.trials
        rng = self.rng
        picks = []
        for w in ws:
            cum = list(accumulate(w))
            if cum[-1] > 0:
                picks.append(rng.choices(range(grid.n), cum_weights=cum, k=trials))
        dead = set(hole) | set(board)
        deck = [c for c in range(52) if c not in dead]
        nd = len(deck)
        rnd = rng.random
        won = tot = 0.0
        for t in range(trials):
            used = set()
            opp = []
            for pk in picks:
                a, b = combos[pk[t]]
                if a in used or b in used:
                    break
                used.add(a)
                used.add(b)
                opp.append((a, b))
            else:
                full = list(board)
                while len(full) < 5:
                    c = deck[int(rnd() * nd)]
                    if c not in used:
                        used.add(c)
                        full.append(c)
                hv = evaluate(hole + full)
                res = 1.0
                for a, b in opp:
                    y = evaluate([a, b] + full)
                    if y > hv:
                        res = 0.0
                        break
                    if y == hv:
                        res = 0.5
                won += res
                tot += 1
        return won / tot if tot else 0.5

    def rto(self, s, to):
        if not _raisable(s):
            return Action("call") if s.to_call else Action("check")
        if to >= 0.45 * s.max_raise_to:
            to = s.max_raise_to
        return Action("raise", int(max(s.min_raise_to, min(to, s.max_raise_to))))

    def bet(self, s, frac):
        return self.rto(s, s.my_bet + s.to_call + frac * (s.pot + s.to_call))

    def jam(self, s):
        if _raisable(s):
            return Action("raise", s.max_raise_to)
        return Action("call") if s.to_call else Action("check")


class TightIsoA(Rival):
    """Stand-in for the practice-round winner "Equity Engine": opens to 3.5 big blinds plus one per limper, attacks limpers widely from late position and the blinds, three-bets to three times the raise, then bets and calls on equity against random hands."""

    opens = (0.37, 0.25, 0.24, 0.16)

    def pre(self, s, v):
        p = PCT[hand_key(*s.hole)]
        bb = v.bb
        nr = len(v.raises)
        if nr == 0:
            if v.is_bb:
                return self.rto(s, (3.5 + v.limpers) * bb) if p < 0.55 else Action("check")
            thr = 0.41 if v.is_sb else self.opens[min(v.pos, 3)]
            if p < thr:
                return self.rto(s, (3.5 + v.limpers) * bb)
            if v.is_sb and v.limpers and p < 0.52:
                return Action("call")
            return Action("fold")
        level = v.level
        if v.my_raises:
            if nr == 2:
                if p < 0.03:
                    return self.rto(s, 2.5 * level)
                return Action("call") if p < 0.06 and s.to_call <= 0.25 * s.my_stack else Action("fold")
            if p < 0.02:
                return self.jam(s)
            return Action("call") if p < 0.04 else Action("fold")
        if nr >= 2 or level >= v.jam:
            return self.jam(s) if p < 0.025 else Action("fold")
        if p < 0.08:
            return self.rto(s, 3 * level + bb * v.limpers)
        if p < (0.245 if level <= 5 * bb else 0.12):
            return Action("call")
        return Action("fold")

    def post(self, s, v):
        st = s.street
        k = min(len(s.active) - 1, 3)
        eq = random_equity(s.hole, s.board, k, self.rng, 80)
        x = k ** 0.8
        c, p = s.to_call, s.pot
        if not c:
            if st == 3:
                return self.bet(s, 0.5) if eq >= 0.88 ** x else Action("check")
            if eq >= 0.9 ** x:
                return self.bet(s, 1.0)
            if eq >= 0.68 ** x:
                return self.bet(s, 0.8)
            if eq >= 0.58 ** x:
                return self.bet(s, 0.5)
            return Action("check")
        need = c / (p + c)
        if st < 3 and eq >= 0.84 ** x and _raisable(s):
            return self.bet(s, 0.8)
        if eq >= need + 0.15 + 0.06 * min(2.0, c / max(1, p - c)):
            return Action("call")
        return Action("fold")


class TightIsoB(Rival):
    """Stand-in for the practice-round winner "Astra La Vista": opens to three big blinds, isolates limpers to 90/110/130, folds most opens to a three-bet, bets made hands at 60% of the pot and almost never raises after the flop."""

    opens = (0.40, 0.30, 0.20, 0.18)

    def pre(self, s, v):
        p = PCT[hand_key(*s.hole)]
        bb = v.bb
        nr = len(v.raises)
        if nr == 0:
            size = (3.5 + v.limpers) * bb if v.limpers else 3 * bb
            if v.is_bb:
                return self.rto(s, size + bb // 2) if p < 0.08 else Action("check")
            thr = 0.32 if v.is_sb else self.opens[min(v.pos, 3)]
            if p < thr:
                return self.rto(s, size)
            if v.limpers >= 2 and p < thr + (0.10 if v.is_sb else 0.16) and (v.is_sb or v.pos <= 1):
                return Action("call")
            return Action("fold")
        level = v.level
        if v.my_raises:
            if nr == 2:
                if p < 0.02:
                    return self.rto(s, 2.3 * level)
                return Action("call") if p < 0.026 and s.to_call <= 0.25 * s.my_stack else Action("fold")
            if p < 0.012:
                return self.jam(s)
            return Action("call") if p < 0.045 else Action("fold")
        if level >= v.jam:
            return Action("call") if p < 0.02 else Action("fold")
        if nr >= 2:
            if p < 0.012:
                return self.rto(s, 2.3 * level)
            return Action("call") if p < 0.02 else Action("fold")
        if p < 0.04:
            return self.rto(s, level + s.pot + s.to_call)
        if p < (0.18 if level <= 5 * bb else 0.09):
            return Action("call")
        return Action("fold")

    def post(self, s, v):
        st = s.street
        cls = made(s.hole, s.board)
        outs = draws(s.hole, s.board) if st < 3 else 0
        c, p = s.to_call, s.pot
        heads_up = len(s.active) == 2
        if not c:
            if cls >= 4 or cls == 3 and (st == 1 or heads_up):
                return self.bet(s, 0.7 if cls >= 5 and st == 3 else 0.6)
            if st == 1 and v.init == s.hero and (cls >= 2 or outs >= 8 or heads_up and self.rng.random() < 0.45):
                return self.bet(s, 0.6)
            return Action("check")
        ratio = c / max(1, p - c)
        if cls >= 6:
            return self.jam(s) if st == 1 and ratio >= 0.5 else Action("call")
        if cls >= 4:
            return Action("call")
        if cls == 3:
            return Action("call") if ratio <= 1.2 else Action("fold")
        if cls == 2 and st < 3 and ratio <= 0.8:
            return Action("call")
        if outs >= 8 and c / (p + c) <= 0.34:
            return Action("call")
        return Action("fold")


RIVALS = {"kit_starter": KitStarter, "kit_station": KitStation, "kit_random": KitRandom, "kit_tag": KitTag,
          "tight_iso_a": TightIsoA, "tight_iso_b": TightIsoB}
