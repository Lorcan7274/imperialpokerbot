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
        limped = set()
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
                        limped.add(p)
                else:
                    tag = "f3" if p in raised else "fr"
                    c[p, tag] += 1
                    c[p, tag + "_" + k[0]] += 1
                    if tag == "fr":
                        c[p, "fr", g] += 1
                        if k == "fold":
                            c[p, "fr_f", g] += 1
                        if p in limped:
                            c[p, "lr"] += 1
                            if k == "fold":
                                c[p, "lr_f"] += 1
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


TAG_CHART = Chart(
    opens=["22+,A2s+,K4s+,Q6s+,J7s+,T7s+,96s+,85s+,75s+,64s+,54s,A4o+,K9o+,Q9o+,J9o+,T9o",
           "22+,A2s+,K8s+,Q9s+,J8s+,T8s+,97s+,86s+,76s,65s,A9o+,KTo+,QTo+,JTo",
           "33+,A2s+,K9s+,Q9s+,J9s+,T9s,98s,87s,ATo+,KJo+,QJo",
           "55+,A8s+,A5s-A4s,KTs+,QTs+,JTs,T9s,98s,AJo+,KQo",
           "66+,ATs+,KTs+,QTs+,JTs,T9s,AJo+,KQo",
           "77+,ATs+,KJs+,QJs,JTs,AQo+"],
    sb="22+,A2s+,K6s+,Q8s+,J8s+,T8s+,97s+,86s+,76s,65s,A7o+,K9o+,QTo+,JTo",
    iso="99+,AJs+,KQs,AQo+",
    limp="22-88,A2s-A9s,K8s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,65s,54s",
    v3=["TT+,AQs+,AKo", "QQ+,AKs,AKo"],
    b3="A5s-A3s",
    flat=["99-22,AJs-ATs,KTs+,QTs+,JTs,T9s,98s,AQo,KQo", "JJ-22,AQs-AJs,KQs,QJs,JTs,AQo"],
    bbdef=["99-22,AJs-A2s,K5s+,Q7s+,J7s+,T7s+,96s+,86s+,75s+,65s,54s,AQo-A7o,KTo+,QTo+,JTo",
           "JJ-22,AQs-A2s,KTs+,QTs+,J9s+,T9s,98s,87s,76s,AQo-AJo,KQo"],
    sbflat="99-77,AJs-ATs,KQs,QJs,JTs",
    v4=["QQ+,AKs,AKo", "KK+,AKs"],
    b4="A5s",
    c3=["QQ-88,AQs-AJs,KQs,AKo,JTs,T9s", "QQ-TT,AQs,AKo"],
    j5="KK+,AKs",
    c4="QQ",
    cold="KK+")

LAG_CHART = Chart(
    opens=["22+,A2s+,K2s+,Q2s+,J4s+,T6s+,95s+,84s+,74s+,63s+,53s+,43s,A2o+,K5o+,Q8o+,J8o+,T8o+,97o+,87o,76o",
           "22+,A2s+,K4s+,Q6s+,J7s+,T7s+,96s+,85s+,75s+,64s+,54s,A5o+,K9o+,Q9o+,J9o+,T9o",
           "22+,A2s+,K7s+,Q8s+,J8s+,T8s+,97s+,86s+,76s,65s,A9o+,KTo+,QTo+,JTo",
           "33+,A2s+,K9s+,Q9s+,J9s+,T8s+,98s,87s,76s,ATo+,KJo+,QJo",
           "44+,A7s+,A5s-A3s,K9s+,Q9s+,J9s+,T9s,98s,ATo+,KJo+",
           "55+,A9s+,A5s-A4s,KTs+,QTs+,JTs,T9s,AJo+,KQo"],
    sb="22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,85s+,75s+,64s+,54s,A2o+,K7o+,Q9o+,J9o+,T8o+,98o",
    iso="77+,ATs+,KJs+,QJs,AJo+,KQo",
    limp="22-66,A2s-A8s,K5s+,Q8s+,J8s+,T7s+,96s+,85s+,75s+,64s+,54s,KTo+,QTo+,JTo",
    v3=["99+,AJs+,KQs,AQo+", "JJ+,AQs+,AKo"],
    b3="A9s-A2s,K9s+,Q9s+,J9s+,T9s,98s,87s,76s,65s,ATo,KJo",
    flat=["88-22,ATs-A9s,KTs+,QTs+,J9s+,T8s+,97s+,86s+,75s+,65s,54s,AJo,KQo,QJo",
          "TT-22,AJs-ATs,KJs+,QTs+,JTs,T9s,98s,87s,76s,AQo"],
    bbdef=["88-22,ATs-A2s,K2s+,Q4s+,J6s+,T6s+,95s+,85s+,74s+,64s+,53s+,43s,AJo-A2o,K8o+,Q9o+,J8o+,T8o+,97o+,87o",
           "TT-22,AJs-A2s,K8s+,Q9s+,J8s+,T8s+,97s+,86s+,75s+,65s,54s,AQo-ATo,KJo+,QJo"],
    sbflat="88-55,ATs,KJs,QJs,JTs,T9s",
    v4=["JJ+,AKs,AKo", "QQ+,AKs,AKo"],
    b4="A5s-A2s,KQs",
    c3=["JJ-66,AQs-ATs,KQs,KJs,QJs,JTs,T9s,98s,87s,AQo", "JJ-99,AQs,AJs,KQs,AQo"],
    j5="QQ+,AKs,AKo",
    c4="JJ,AQs",
    cold="QQ+,AKs")

BALANCED_CHART = Chart(
    opens=["22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,85s+,75s+,64s+,54s,A2o+,K8o+,Q9o+,J9o+,T8o+,98o",
           "22+,A2s+,K6s+,Q8s+,J8s+,T7s+,97s+,86s+,76s,65s,54s,A8o+,KTo+,QTo+,JTo",
           "33+,A2s+,K8s+,Q9s+,J9s+,T8s+,98s,87s,76s,ATo+,KJo+,QJo",
           "44+,A7s+,A5s-A3s,K9s+,Q9s+,J9s+,T9s,98s,87s,AJo+,KQo",
           "55+,A9s+,A5s-A4s,KTs+,QTs+,JTs,T9s,98s,AJo+,KQo",
           "66+,ATs+,A5s,KTs+,QTs+,JTs,T9s,AQo+"],
    sb="22+,A2s+,K4s+,Q7s+,J7s+,T7s+,96s+,86s+,75s+,65s,54s,A5o+,K9o+,Q9o+,J9o+,T9o",
    iso="88+,ATs+,KJs+,AJo+,KQo",
    limp="22-77,A2s-A9s,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,65s,54s",
    v3=["JJ+,AQs+,AKo", "QQ+,AKs,AKo"],
    b3="TT-99,AJs-ATs,KQs,KJs,A5s-A2s,T9s,98s,87s,76s",
    flat=["TT-22,AJs-ATs,KTs+,QTs+,J9s+,T9s,98s,87s,76s,AQo,KQo", "JJ-22,AQs-AJs,KQs,QJs,JTs,T9s,AQo"],
    bbdef=["TT-22,AJs-A2s,K2s+,Q5s+,J7s+,T6s+,96s+,85s+,74s+,64s+,53s+,43s,AQo-A2o,K9o+,Q9o+,J9o+,T8o+,98o,87o",
           "JJ-22,AQs-A2s,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,76s,65s,AQo-ATo,KJo+,QJo"],
    sbflat="TT-66,AJs-ATs,KQs,QJs,JTs",
    v4=["KK+,AKs", "KK+"],
    b4="QQ,AKo,AKs,A5s,A4s",
    c3=["QQ-77,AQs-ATs,KQs,KJs,QJs,JTs,T9s,98s,AKs,AKo,AQo", "QQ-99,AQs,AJs,KQs,AKs,AKo"],
    j5="KK+,AKs",
    c4="QQ,JJ,AKo",
    cold="KK+")

_BIG_PAIRS = R("KK+")


class ChartBot(Rival):
    chart = TAG_CHART
    open_bb = 3.0
    b3f = (0.5, 0.0)
    b4f = 0.25
    jam_range = (0.055, 0.045, 0.03)
    value = (0.60, 0.62, 0.66)
    vsize = (0.6, 0.7, 0.7)
    raise_thr = (0.78, 0.80, 0.86)
    margin = (0.04, 0.03, 0.02)
    cbet = (0.65, 0.30, 0.08)
    barrel = (0.35, 0.25)
    semi = (0.6, 0.4, 0.2)
    semi_raise = 0.15
    semi_outs = 12
    stab = 0.3
    probe = 0.15
    checkto = 0.6
    floats = 0.0
    bluff_raise = 0.0

    def pre(self, s, v):
        key = hand_key(*s.hole)
        nr = len(v.raises)
        if nr == 0:
            return self.unopened(s, v, key)
        if v.level >= v.jam or s.to_call >= 0.3 * s.my_stack:
            return self.vs_jam(s, v, key)
        if not v.my_raises:
            if nr == 1 or v.level <= 5 * v.bb:
                return self.vs_open(s, v, key)
            return self.cold(s, v, key)
        if nr == 2 and v.raises[0][0] == s.hero:
            return self.vs_3bet(s, v, key)
        return self.vs_4bet(s, v, key)

    def unopened(self, s, v, key):
        ch, bb, limp = self.chart, v.bb, v.limpers
        if v.is_bb:
            return self.rto(s, (3.5 + limp) * bb) if key in ch.iso else Action("check")
        if v.is_sb:
            opens = ch.opens[3] if limp else ch.sb
        else:
            opens = ch.opens[min(v.pos + (1 if limp else 0), 5)]
        if key in opens:
            return self.rto(s, ((3.5 + limp) if limp else 3.0 if v.is_sb else self.open_bb) * bb)
        if limp and key in ch.limp and (v.is_sb or v.pos <= 2):
            return Action("call")
        return Action("fold")

    def vs_open(self, s, v, key):
        ch, bb = self.chart, v.bb
        opener, level = v.raises[-1]
        late = 0 if opener == v.sbp or len(s.players) - 1 - s.players.index(opener) <= 2 else 1
        blind = v.is_sb or v.is_bb
        three = level * (3.8 if blind else 3.1) + v.callers * level + v.limpers * bb
        r = self.rng.random()
        if key in ch.v3[late]:
            return self.three_bet(s, v, key, three, r)
        if level > (4.6 + v.limpers) * bb:
            return Action("call") if level <= 9 * bb and key in ch.c3[1] else Action("fold")
        if key in ch.b3 and r < self.b3f[late] and self.pressure(opener):
            return self.rto(s, three)
        if v.is_bb:
            if key in ch.bbdef[late] or level <= 2.25 * bb and key in ch.bbdef[0]:
                return Action("call")
        elif v.is_sb:
            if key in ch.sbflat:
                return Action("call")
        elif key in ch.flat[late]:
            return Action("call")
        return Action("fold")

    def three_bet(self, s, v, key, to, r):
        return self.rto(s, to)

    def pressure(self, p):
        return True

    def bluffable(self, s):
        return True

    def vs_3bet(self, s, v, key):
        ch = self.chart
        raiser, level = v.raises[-1]
        wide = 0 if v.is_sb or v.pos <= 2 else 1
        ip = s.players.index(s.hero) > s.players.index(raiser)
        if key in ch.v4[wide] or key in ch.b4 and self.rng.random() < self.b4f and self.pressure(raiser):
            return self.rto(s, level * (2.2 if ip else 2.5))
        if level <= 4.3 * s.my_bet and key in ch.c3[0 if ip else 1]:
            return Action("call")
        return Action("fold")

    def vs_4bet(self, s, v, key):
        ch = self.chart
        if key in ch.j5:
            return self.jam(s)
        if key in ch.c4 and s.to_call <= 0.22 * s.my_stack:
            return Action("call")
        return Action("fold")

    def cold(self, s, v, key):
        return self.rto(s, 2.4 * v.level) if key in self.chart.cold else Action("fold")

    def jam_width(self, s, v, p):
        return 0.04 if v.labels.get(p) in ("calljam", "call4") else self.jam_range[min(len(v.raises), 3) - 1]

    def vs_jam(self, s, v, key):
        eq = 1.0
        for p in s.active:
            if p != s.hero and v.bets.get(p, 0) >= v.level:
                eq *= allin_eq(s.hole, self.jam_width(s, v, p))
        need = s.to_call / (s.pot + s.to_call)
        if eq >= need + 0.02:
            return self.jam(s) if eq >= need + 0.08 else Action("call")
        return Action("fold")

    def post(self, s, v):
        ws = self.ranges(s, v)
        eq = self.equity(s, ws)
        return self.facing(s, v, eq, len(ws)) if s.to_call else self.lead(s, v, eq, len(ws))

    def lead(self, s, v, eq, nv):
        st = s.street
        me = s.hero
        ip = s.active[-1] == me
        init = v.init == me
        r = self.rng.random()
        k = min(nv, 3) - 1
        if eq >= max(0.42, self.value[st - 1] - 0.07 * (nv - 1)):
            if st == 1 and not init and not ip and v.init in s.active and r < self.checkto:
                return Action("check")
            return self.bet(s, self.vsize[st - 1] + (0.2 if st == 3 and eq >= 0.9 else 0.0))
        outs = draws(s.hole, s.board) if st < 3 else 0
        if outs >= 8 and r < self.semi[k]:
            return self.bet(s, 0.6)
        if not self.bluffable(s):
            return Action("check")
        if init:
            if st == 1:
                p = self.cbet[k] * (1.0 - 0.18 * wetness(s.board))
            else:
                p = self.barrel[st - 2] * (1.3 if outs else 1.0) if nv == 1 and (st == 2 or eq < 0.3) else 0.0
        elif nv == 1 and (st < 3 or eq < 0.3):
            p = self.stab if ip else self.probe if st > 1 and v.aggr.get(st - 1) is None else 0.0
        else:
            p = 0.0
        if r < p:
            return self.bet(s, 0.5 if st == 1 else 0.7)
        return Action("check")

    def facing(self, s, v, eq, nv):
        st = s.street
        c, pot = s.to_call, s.pot
        need = c / (pot + c)
        can = _raisable(s)
        r = self.rng.random()
        outs = draws(s.hole, s.board) if st < 3 else 0
        if can and eq >= self.raise_thr[st - 1] + 0.03 * (nv - 1):
            return self.raise_value(s, v, eq, r)
        lone = nv == 1 and v.nr == 1
        if can and lone and outs >= self.semi_outs and r < self.semi_raise:
            return self.bet(s, 0.7)
        deep = s.my_stack > 4 * c
        bonus = (0.05 if outs >= 8 else 0.02 if outs else 0.0) if deep else 0.0
        if eq + bonus >= need + self.margin[st - 1] + 0.03 * v.behind:
            return Action("call")
        if st == 1 and lone and deep and self.bluffable(s):
            if s.active[-1] == s.hero and r < self.floats:
                return Action("call")
            if can and r > 1.0 - self.bluff_raise:
                return self.bet(s, 0.7)
        return Action("fold")

    def raise_value(self, s, v, eq, r):
        return self.bet(s, 0.75)


class Tag(ChartBot):
    """Position-aware tight-aggressive: fixed opening, three-bet and four-bet charts, continuation bets, value bets at 60-70% of the pot, and calls on pot odds against the range the action implies."""


class Lag(ChartBot):
    """Loose-aggressive: steals wide from late position and the small blind, three-bets and four-bets light, barrels several streets, floats and semi-bluff raises; stops bluffing players it has seen never fold."""

    chart = LAG_CHART
    track = True
    open_bb = 2.5
    b3f = (0.45, 0.2)
    b4f = 0.4
    value = (0.56, 0.58, 0.62)
    vsize = (0.7, 0.75, 0.8)
    raise_thr = (0.74, 0.77, 0.84)
    margin = (0.02, 0.02, 0.01)
    cbet = (0.8, 0.5, 0.15)
    barrel = (0.6, 0.45)
    semi = (0.8, 0.6, 0.4)
    semi_raise = 0.4
    semi_outs = 8
    stab = 0.65
    probe = 0.5
    checkto = 0.4
    floats = 0.35
    bluff_raise = 0.08

    def pressure(self, p):
        c = self.stats.c
        return c.get((p, "f3"), 0) < 6 or c.get((p, "f3_f"), 0) >= 0.3 * c.get((p, "f3"), 0)

    def bluffable(self, s):
        c = self.stats.c
        for p in s.active:
            if p != s.hero:
                n = c.get((p, "vb", 1), 0) + c.get((p, "vb", 2), 0) + c.get((p, "vb", 3), 0)
                f = c.get((p, "vb_f", 1), 0) + c.get((p, "vb_f", 2), 0) + c.get((p, "vb_f", 3), 0)
                if n >= 10 and f < 0.25 * n:
                    return False
        return True


class Trapper(ChartBot):
    """Trappy: flat-calls its biggest pairs before the flop, checks strong hands to check-raise or let others bet, and calls down lighter the more often an opponent has been seen betting."""

    track = True
    cbet = (0.5, 0.2, 0.05)
    barrel = (0.2, 0.15)
    semi = (0.5, 0.3, 0.1)
    stab = 0.25
    probe = 0.1

    def freq(self, p, kind, st, init):
        prior = ChartBot.freq(self, p, kind, st, init)
        if kind == "bet":
            return self.stats.rate((p, "nb_b", st, init), (p, "nb", st, init), prior, 6.0)
        return prior

    def three_bet(self, s, v, key, to, r):
        if key in _BIG_PAIRS and not v.callers and r < 0.4:
            return Action("call")
        return self.rto(s, to)

    def lead(self, s, v, eq, nv):
        st = s.street
        if st < 3 and eq >= 0.82 + 0.03 * (nv - 1) and wetness(s.board) < 2:
            r = self.rng.random()
            if s.active[-1] != s.hero:
                keen = max(self.freq(p, "bet", st, p == v.init) for p in s.active if p != s.hero)
                if r < (0.8 if keen >= 0.45 else 0.4) * (0.5 if st == 2 and v.aggr.get(1) is None else 1.0):
                    return Action("check")
            elif st == 1 and r < 0.35:
                return Action("check")
        return ChartBot.lead(self, s, v, eq, nv)

    def raise_value(self, s, v, eq, r):
        if s.street == 1 and not v.checked and s.active[-1] == s.hero and r < 0.55 and wetness(s.board) < 2:
            return Action("call")
        return self.bet(s, 0.9 if v.checked else 0.75)


class Adaptive(ChartBot):
    """Exploiter: measures how often each opponent enters, raises, re-raises, bets and folds; steals from folders and limpers who give up, sizes up and bets thinner into callers, checks strong hands to frequent bettors and reads every range from the measured rates."""

    track = True

    def freq(self, p, kind, st, init):
        prior = ChartBot.freq(self, p, kind, st, init)
        rate = self.stats.rate
        if kind == "bet":
            return rate((p, "nb_b", st, init), (p, "nb", st, init), prior, 5.0)
        if kind == "raise":
            return rate((p, "vb_r", st), (p, "vb", st), prior, 8.0)
        return rate((p, "vb_f", st), (p, "vb", st), prior, 5.0)

    def group(self, s, v, p):
        if p == v.sbp:
            return 2
        if p == v.bbp:
            return 3
        return 0 if len(s.players) - 1 - s.players.index(p) <= 2 else 1

    def width(self, v, p):
        rate = self.stats.rate
        mine = [i for i, (q, _) in enumerate(v.raises) if q == p]
        w = rate((p, "pfr"), (p, "hands"), 0.18, 12.0)
        if len(mine) >= 2:
            w *= 1.0 - rate((p, "f3_f"), (p, "f3"), 0.6, 6.0)
        elif mine and mine[0] >= 1:
            w = rate((p, "fr_r"), (p, "fr"), 0.06, 12.0)
        if v.labels.get(p) == "jam":
            w = min(w, max(0.02, 2.5 * rate((p, "jam"), (p, "hands"), 0.02, 15.0)))
        return clamp(w, 0.015, 0.95)

    def pre_band(self, s, v, p):
        lo, hi, top, leak = ChartBot.pre_band(self, s, v, p)
        lab = v.labels.get(p, "check")
        rate = self.stats.rate
        if lab == "open":
            g = self.group(s, v, p)
            hi = clamp(rate((p, "uo_r", g), (p, "uo", g), hi, 8.0), 0.03, 0.95)
        elif lab in ("3bet", "4bet", "jam"):
            hi = self.width(v, p)
        elif lab in ("call", "limpcall"):
            g = self.group(s, v, p)
            hi = clamp(1.0 - rate((p, "fr_f", g), (p, "fr", g), 1.0 - hi, 8.0), 0.06, 0.98)
            lo = min(lo, 0.5 * rate((p, "fr_r"), (p, "fr"), 0.06, 12.0))
        elif lab == "limp":
            up = rate((p, "uo_r"), (p, "uo"), 0.12, 8.0)
            lo = 0.8 * up
            hi = clamp(up + 1.1 * rate((p, "uo_c"), (p, "uo"), 0.45, 8.0), 0.3, 1.0)
        return lo, hi, top, leak

    def jam_width(self, s, v, p):
        if v.labels.get(p) in ("calljam", "call4"):
            return clamp(self.stats.rate((p, "fj_c"), (p, "fj"), 0.04, 8.0), 0.015, 1.0)
        return self.width(v, p)

    def unopened(self, s, v, key):
        a = ChartBot.unopened(self, s, v, key)
        rate = self.stats.rate
        pf = 1.0
        stick = n = 0
        for p in s.active:
            if p == s.hero:
                continue
            if p in v.labels:
                f = rate((p, "lr_f"), (p, "lr"), 0.5, 5.0)
            else:
                g = self.group(s, v, p)
                f = rate((p, "fr_f", g), (p, "fr", g), (0.82, 0.86, 0.78, 0.55)[g], 6.0)
            pf *= f
            stick += 1.0 - f
            n += 1
        x = PCT[key]
        if a.kind != "raise":
            if pf > 0.5 and x < 2.4 * (pf - 0.42):
                return self.rto(s, (3.0 + v.limpers) * v.bb)
            return a
        if x < 0.1 and n and stick / n > 0.45:
            return self.rto(s, a.amount * (1.0 + 2.0 * (stick / n - 0.3)))
        return a

    def vs_open(self, s, v, key):
        a = ChartBot.vs_open(self, s, v, key)
        opener, level = v.raises[-1]
        if level > 6 * v.bb:
            return a
        std = ChartBot.pre_band(self, s, v, opener)[1]
        w = self.pre_band(s, v, opener)[1]
        x = PCT[key]
        if w > 1.35 * std:
            if x < 0.3 * w:
                return self.rto(s, level * 3.5 + v.callers * level + v.limpers * v.bb)
            if a.kind == "fold" and x < (0.85 if v.is_bb else 0.6) * w:
                return Action("call")
        elif w < 0.6 * std:
            if a.kind == "raise" and x > 0.3 * w:
                a = Action("call")
            if a.kind == "call" and x > 1.5 * w:
                return Action("fold")
        return a

    def reraised(self, s, v, key, default):
        raiser, level = v.raises[-1]
        w = self.width(v, raiser)
        if w < 0.09:
            return default(self, s, v, key)
        eq = allin_eq(s.hole, w)
        if eq >= 0.56:
            return self.rto(s, 2.3 * level)
        if eq >= 0.45 and s.to_call <= 0.2 * s.my_stack:
            return Action("call")
        return Action("fold")

    def vs_3bet(self, s, v, key):
        return self.reraised(s, v, key, ChartBot.vs_3bet)

    def vs_4bet(self, s, v, key):
        return self.reraised(s, v, key, ChartBot.vs_4bet)

    def cold(self, s, v, key):
        return self.reraised(s, v, key, ChartBot.cold)

    def lead(self, s, v, eq, nv):
        if not _raisable(s):
            return Action("check")
        st = s.street
        me = s.hero
        pot = s.pot
        ip = s.active[-1] == me
        foes = [p for p in s.active if p != me]
        outs = draws(s.hole, s.board) if st < 3 else 0
        best = None
        best_ev = eq * pot * (1.0 if st == 3 else 0.9 if ip else 0.8)
        if eq >= 0.8 and (st < 3 or not ip):
            best_ev += 0.45 * pot * max(self.freq(p, "bet", st, p == v.init) for p in foes)
        reraise = max(self.freq(p, "raise", st, False) for p in foes)
        for frac in (0.4, 0.75, 1.2):
            b = min(frac * pot, s.my_stack)
            pf = 1.0
            for p in foes:
                pf *= clamp(self.freq(p, "fold", st, False) * (b / (pot + b) / 0.4) ** 0.6, 0.02, 0.95)
            fbar = pf ** (1.0 / nv)
            eqc = clamp((eq - fbar) / (1.0 - fbar), 0.7 * eq if outs >= 8 else 0.04, 1.0)
            ev = pf * pot + (1.0 - pf) * (eqc * (pot + 2.0 * b) - b)
            if eqc < 0.75:
                ev -= (1.0 - pf) * reraise * 0.4 * b
            if ev > best_ev + 0.03 * pot:
                best, best_ev = frac, ev
        return self.bet(s, best) if best else Action("check")


class Balanced(ChartBot):
    """Game-theory-minded and static: mixed three-bet and four-bet frequencies, bets the top of its own range plus bluffs from the bottom in proportion, and defends against bets at minimum defence frequency."""

    chart = BALANCED_CHART
    open_bb = 2.5
    b3f = (0.45, 0.3)
    b4f = 0.5

    def quantile(self, s, v):
        own = self.weights(s, v, s.hero)
        vals = self.grid(s).on(s.board)[0]
        hv = evaluate(s.hole + s.board)
        above = tot = 0.0
        for x, y in zip(own, vals):
            if x:
                tot += x
                if y > hv:
                    above += x
                elif y == hv:
                    above += 0.5 * x
        return above / tot if tot else 0.5

    def post(self, s, v):
        me = s.hero
        st = s.street
        ws = self.ranges(s, v)
        nv = len(ws)
        eq = self.equity(s, ws)
        q = self.quantile(s, v)
        outs = draws(s.hole, s.board) if st < 3 else 0
        r = self.rng.random()
        c, pot = s.to_call, s.pot
        ip = s.active[-1] == me
        if c:
            need = c / (pot + c)
            mdf = (pot - c - s.my_bet) / pot * (1.0 if nv == 1 else 0.7)
            can = _raisable(s)
            if can and q <= 0.12 and eq >= (0.72, 0.75, 0.82)[st - 1] + 0.03 * (nv - 1):
                return self.bet(s, 0.8) if st == 3 or r < 0.8 else Action("call")
            if can and nv == 1 and v.nr == 1:
                if st < 3 and outs >= 12 and r < 0.35:
                    return self.bet(s, 0.8)
                if st == 3 and q >= 0.93 and r < 0.12:
                    return self.bet(s, 0.9)
            if eq < 0.45 * need and not outs:
                return Action("fold")
            if q <= mdf or eq >= need + 0.08 or outs >= 8 and need <= 0.34:
                return Action("call")
            return Action("fold")
        if not (v.init == me or ip or st > 1 and v.aggr.get(st - 1) is None):
            return Action("check")
        wet = wetness(s.board)
        size = (0.5 if wet else 0.33) if st == 1 else 0.7 if st == 2 else 0.75
        if eq >= max(0.44, (0.6, 0.62, 0.64)[st - 1] - 0.07 * (nv - 1)):
            if st < 3 and wet < 2 and r < 0.15:
                return Action("check")
            return self.bet(s, size + (0.25 if st == 3 and q <= 0.05 else 0.0))
        if nv > 2:
            return Action("check")
        if st < 3:
            p = 0.7 if outs >= 8 else 0.45 if outs else 0.0
            if q >= (0.68, 0.78)[st - 1] and nv == 1:
                p = max(p, (0.5, 0.45)[st - 1])
        else:
            p = 0.7 if q >= 0.86 and nv == 1 else 0.0
        return self.bet(s, size) if r < p else Action("check")


class EqBot(Rival):
    """Equity-threshold player of the kind a language model writes by default: Monte Carlo equity against a random hand for each opponent still in, bet above fixed thresholds, call on pot odds less a discount for the size of the bet."""

    opens = (0.42, 0.32, 0.25, 0.20, 0.16, 0.14)

    def pre(self, s, v):
        p = PCT[hand_key(*s.hole)]
        bb = v.bb
        nr = len(v.raises)
        if nr == 0:
            if v.is_bb:
                return self.rto(s, (4 + v.limpers) * bb) if p < 0.09 else Action("check")
            thr = 0.36 if v.is_sb else self.opens[min(v.pos, 5)]
            if p < thr * (0.8 if v.limpers else 1.0):
                return self.rto(s, (3 + v.limpers) * bb)
            if v.limpers and p < 0.5 and (v.is_sb or v.pos <= 1):
                return Action("call")
            return Action("fold")
        level = v.level
        if level >= v.jam or s.to_call >= 0.3 * s.my_stack:
            return self.jam(s) if p < 0.03 else Action("fold")
        if nr == 1 and not v.my_raises:
            if p < 0.045:
                return self.rto(s, 3 * level)
            if level <= 4 * bb and p < (0.30 if v.is_bb else 0.16):
                return Action("call")
            return Action("call") if p < 0.08 and level <= 8 * bb else Action("fold")
        if p < 0.022:
            return self.jam(s)
        return Action("call") if p < 0.06 and s.to_call <= 12 * bb else Action("fold")

    def post(self, s, v):
        st = s.street
        k = min(len(s.active) - 1, 3)
        eq = random_equity(s.hole, s.board, k, self.rng, 90)
        x = k ** 0.8
        c, pot = s.to_call, s.pot
        if not c:
            if eq >= 0.8 ** x:
                return self.bet(s, 0.75)
            if eq >= 0.6 ** x:
                return self.bet(s, 0.5)
            if st == 1 and v.init == s.hero and k == 1 and self.rng.random() < 0.45:
                return self.bet(s, 0.5)
            return Action("check")
        ratio = c / max(1, pot - c)
        adj = eq - 0.08 - 0.12 * min(1.5, ratio) - 0.04 * (st - 1) - (0.1 if v.nr >= 2 else 0.0)
        if adj >= 0.8 ** x and _raisable(s):
            return self.bet(s, 0.75)
        return Action("call") if adj >= c / (pot + c) + 0.02 else Action("fold")


class Shover(Rival):
    """Push-or-fold: goes all-in before the flop whenever the expected value is positive against each opponent's observed calling range, and calls all-ins on equity against the range the jammer has shown."""

    track = True

    def pre(self, s, v):
        rate = self.stats.rate
        me = s.hero
        hole = s.hole
        pot = s.pot
        if v.raises and (v.level >= v.jam or s.to_call >= 0.3 * s.my_stack):
            eq = 1.0
            for p in s.active:
                if p != me and v.bets.get(p, 0) >= v.level:
                    lab = v.labels.get(p)
                    if lab == "jam":
                        w = rate((p, "jam"), (p, "hands"), 0.03, 12.0)
                    elif lab == "calljam":
                        w = rate((p, "fj_c"), (p, "fj"), 0.04, 6.0)
                    else:
                        w = 0.03
                    eq *= allin_eq(hole, max(0.012, w))
            if eq >= s.to_call / (pot + s.to_call) + 0.03:
                return self.jam(s)
            return Action("fold")
        risk = s.my_stack
        none = total = 1.0
        extra = 0.0
        for p in s.active:
            if p == me:
                continue
            c = rate((p, "fj_c"), (p, "fj"), 0.035, 5.0)
            lab = v.labels.get(p)
            if lab in ("open", "3bet", "4bet"):
                base = rate((p, "pfr"), (p, "hands"), 0.15, 10.0)
            elif lab in ("limp", "call", "limpcall", "call3"):
                base = rate((p, "vpip"), (p, "hands"), 0.25, 10.0)
            else:
                base = 1.0
            pc = min(1.0, c / max(base, 0.02))
            x = pc * allin_eq(hole, max(0.012, min(c, base)))
            y = 1.0 - pc
            none *= y
            total *= x + y
            extra += (v.stack0 - v.bets.get(p, 0)) * x / (x + y)
        ev = none * pot + (total - none) * (pot + risk) + total * extra - (1.0 - none) * risk
        if _raisable(s) and ev > (0.4 * pot if not s.to_call else 0.0) + 0.25 * v.bb:
            return self.jam(s)
        return Action("fold") if s.to_call else Action("check")

    def post(self, s, v):
        cls = made(s.hole, s.board)
        c, pot = s.to_call, s.pot
        if cls >= 5:
            return self.jam(s)
        if cls == 4:
            if not c:
                return self.bet(s, 1.0)
            return Action("call") if c <= 0.5 * pot else Action("fold")
        if not c:
            return Action("check")
        if s.street < 3 and draws(s.hole, s.board) >= 8 and c <= 0.25 * pot:
            return Action("call")
        return Action("fold")


RIVALS = {"kit_starter": KitStarter, "kit_station": KitStation, "kit_random": KitRandom, "kit_tag": KitTag,
          "tight_iso_a": TightIsoA, "tight_iso_b": TightIsoB,
          "tag": Tag, "lag": Lag, "shover": Shover, "trapper": Trapper, "adaptive": Adaptive,
          "eqbot": EqBot, "balanced": Balanced}
KIT = ("kit_starter", "kit_station", "kit_random", "kit_tag")
STRONG = ("tag", "lag", "shover", "trapper", "adaptive", "eqbot", "balanced", "tight_iso_a", "tight_iso_b")
