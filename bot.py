from collections import defaultdict, namedtuple
from collections import namedtuple
import random
import time

RANKS = "23456789TJQKA"
SUITS = "cdhs"

RANK_KEY = [1 << (3 * (c >> 2)) for c in range(52)]
SUIT_KEY = [1 << (4 * (c & 3)) for c in range(52)]
RANK_BIT = [1 << (c >> 2) for c in range(52)]


def parse_card(text):
    if isinstance(text, int):
        return text
    t = text.strip()
    if t[:2] == "10":
        t = "T" + t[2:]
    a, b = t[0].upper(), t[1].lower()
    if a in RANKS and b in SUITS:
        return RANKS.index(a) * 4 + SUITS.index(b)
    a, b = t[1].upper(), t[0].lower()
    return RANKS.index(a) * 4 + SUITS.index(b)


def parse_cards(cards):
    if isinstance(cards, str):
        cards = cards.replace(",", " ").split() if (" " in cards or "," in cards) else [
            cards[i:i + 2] for i in range(0, len(cards), 2)]
    return [parse_card(c) for c in cards]


def card_str(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def _straight_high(mask):
    for high in range(12, 3, -1):
        if (mask >> (high - 4)) & 31 == 31:
            return high
    if mask & 0b1000000001111 == 0b1000000001111:
        return 3
    return 0


def _top(mask, n):
    v = 0
    k = 0
    for r in range(12, -1, -1):
        if mask >> r & 1:
            v = v << 4 | r
            k += 1
            if k == n:
                break
    return v << (4 * (5 - k))


STRAIGHT = [_straight_high(m) for m in range(8192)]
TOP5 = [_top(m, 5) for m in range(8192)]
_CACHE = {}


def _rank_value(key):
    quads, trips, pairs, singles = [], [], [], []
    mask = 0
    for r in range(12, -1, -1):
        n = key >> (3 * r) & 7
        if n:
            mask |= 1 << r
            (singles, pairs, trips, quads)[n - 1].append(r)
    if quads:
        q = quads[0]
        kick = max(trips + pairs + singles + quads[1:])
        return 7 << 20 | q << 16 | kick << 12
    if trips and (len(trips) > 1 or pairs):
        other = max(trips[1:] + pairs[:1])
        return 6 << 20 | trips[0] << 16 | other << 12
    high = STRAIGHT[mask]
    if high:
        return 4 << 20 | high << 16
    if trips:
        k = singles[:2]
        return 3 << 20 | trips[0] << 16 | k[0] << 12 | k[1] << 8
    if len(pairs) >= 2:
        kick = max(pairs[2:] + singles[:1])
        return 2 << 20 | pairs[0] << 16 | pairs[1] << 12 | kick << 8
    if pairs:
        k = singles[:3]
        v = 1 << 20 | pairs[0] << 16
        shift = 12
        for x in k:
            v |= x << shift
            shift -= 4
        return v
    return TOP5[mask]


def evaluate(cards):
    rk = 0
    sk = 0
    for c in cards:
        rk += RANK_KEY[c]
        sk += SUIT_KEY[c]
    flush = (sk + 0x3333) & 0x8888
    if flush:
        suit = 0 if flush & 0x8 else 1 if flush & 0x80 else 2 if flush & 0x800 else 3
        mask = 0
        for c in cards:
            if c & 3 == suit:
                mask |= RANK_BIT[c]
        high = STRAIGHT[mask]
        if high:
            return 8 << 20 | high << 16
        return 5 << 20 | TOP5[mask]
    v = _CACHE.get(rk)
    if v is None:
        v = _CACHE[rk] = _rank_value(rk)
    return v


def category(value):
    return value >> 20

EQ = {
    "AA": 0.8526,
    "AKs": 0.6732,
    "AKo": 0.6506,
    "AQs": 0.6603,
    "AQo": 0.6429,
    "AJs": 0.6555,
    "AJo": 0.6344,
    "ATs": 0.6460,
    "ATo": 0.6276,
    "A9s": 0.6271,
    "A9o": 0.6058,
    "A8s": 0.6177,
    "A8o": 0.5992,
    "A7s": 0.6145,
    "A7o": 0.5891,
    "A6s": 0.5937,
    "A6o": 0.5766,
    "A5s": 0.6017,
    "A5o": 0.5766,
    "A4s": 0.5900,
    "A4o": 0.5682,
    "A3s": 0.5807,
    "A3o": 0.5609,
    "A2s": 0.5761,
    "A2o": 0.5516,
    "KK": 0.8230,
    "KQs": 0.6334,
    "KQo": 0.6122,
    "KJs": 0.6275,
    "KJo": 0.6070,
    "KTs": 0.6172,
    "KTo": 0.5974,
    "K9s": 0.5970,
    "K9o": 0.5788,
    "K8s": 0.5862,
    "K8o": 0.5640,
    "K7s": 0.5751,
    "K7o": 0.5540,
    "K6s": 0.5641,
    "K6o": 0.5433,
    "K5s": 0.5597,
    "K5o": 0.5347,
    "K4s": 0.5482,
    "K4o": 0.5240,
    "K3s": 0.5452,
    "K3o": 0.5109,
    "K2s": 0.5347,
    "K2o": 0.5060,
    "QQ": 0.7992,
    "QJs": 0.6001,
    "QJo": 0.5824,
    "QTs": 0.5907,
    "QTo": 0.5699,
    "Q9s": 0.5763,
    "Q9o": 0.5614,
    "Q8s": 0.5556,
    "Q8o": 0.5356,
    "Q7s": 0.5432,
    "Q7o": 0.5184,
    "Q6s": 0.5372,
    "Q6o": 0.5068,
    "Q5s": 0.5278,
    "Q5o": 0.5085,
    "Q4s": 0.5139,
    "Q4o": 0.4911,
    "Q3s": 0.5082,
    "Q3o": 0.4812,
    "Q2s": 0.5059,
    "Q2o": 0.4721,
    "JJ": 0.7771,
    "JTs": 0.5739,
    "JTo": 0.5506,
    "J9s": 0.5581,
    "J9o": 0.5321,
    "J8s": 0.5429,
    "J8o": 0.5115,
    "J7s": 0.5214,
    "J7o": 0.5000,
    "J6s": 0.5077,
    "J6o": 0.4804,
    "J5s": 0.5000,
    "J5o": 0.4686,
    "J4s": 0.4955,
    "J4o": 0.4605,
    "J3s": 0.4804,
    "J3o": 0.4520,
    "J2s": 0.4746,
    "J2o": 0.4399,
    "TT": 0.7527,
    "T9s": 0.5416,
    "T9o": 0.5196,
    "T8s": 0.5236,
    "T8o": 0.4989,
    "T7s": 0.5073,
    "T7o": 0.4808,
    "T6s": 0.4911,
    "T6o": 0.4627,
    "T5s": 0.4699,
    "T5o": 0.4458,
    "T4s": 0.4694,
    "T4o": 0.4372,
    "T3s": 0.4569,
    "T3o": 0.4270,
    "T2s": 0.4451,
    "T2o": 0.4153,
    "99": 0.7213,
    "98s": 0.5043,
    "98o": 0.4769,
    "97s": 0.4897,
    "97o": 0.4702,
    "96s": 0.4720,
    "96o": 0.4484,
    "95s": 0.4558,
    "95o": 0.4264,
    "94s": 0.4355,
    "94o": 0.4124,
    "93s": 0.4335,
    "93o": 0.4024,
    "92s": 0.4251,
    "92o": 0.3901,
    "88": 0.6871,
    "87s": 0.4788,
    "87o": 0.4500,
    "86s": 0.4612,
    "86o": 0.4319,
    "85s": 0.4432,
    "85o": 0.4181,
    "84s": 0.4290,
    "84o": 0.3949,
    "83s": 0.4057,
    "83o": 0.3735,
    "82s": 0.4022,
    "82o": 0.3674,
    "77": 0.6613,
    "76s": 0.4525,
    "76o": 0.4176,
    "75s": 0.4368,
    "75o": 0.4022,
    "74s": 0.4189,
    "74o": 0.3840,
    "73s": 0.3981,
    "73o": 0.3627,
    "72s": 0.3803,
    "72o": 0.3462,
    "66": 0.6287,
    "65s": 0.4314,
    "65o": 0.3967,
    "64s": 0.4127,
    "64o": 0.3816,
    "63s": 0.3949,
    "63o": 0.3629,
    "62s": 0.3770,
    "62o": 0.3367,
    "55": 0.5988,
    "54s": 0.4141,
    "54o": 0.3820,
    "53s": 0.3953,
    "53o": 0.3618,
    "52s": 0.3814,
    "52o": 0.3449,
    "44": 0.5691,
    "43s": 0.3882,
    "43o": 0.3513,
    "42s": 0.3636,
    "42o": 0.3281,
    "33": 0.5362,
    "32s": 0.3589,
    "32o": 0.3231,
    "22": 0.4999,
}


COMBOS = [(a, b) for a in range(52) for b in range(a)]
NCOMBO = len(COMBOS)
COMBO_INDEX = {c: i for i, c in enumerate(COMBOS)}
CARD_COMBOS = [[i for i, c in enumerate(COMBOS) if k in c] for k in range(52)]


def class_name(a, b):
    ra, rb = a >> 2, b >> 2
    hi, lo = max(ra, rb), min(ra, rb)
    if hi == lo:
        return RANKS[hi] + RANKS[lo]
    return RANKS[hi] + RANKS[lo] + ("s" if a & 3 == b & 3 else "o")


def _score(name):
    s = EQ[name]
    if len(name) == 3:
        gap = RANKS.index(name[0]) - RANKS.index(name[1])
        if name[2] == "s":
            s += 0.015
        if gap <= 2:
            s += 0.006 * (3 - gap)
    return s


_SCORE = [_score(class_name(a, b)) for a, b in COMBOS]
PREFLOP_ORDER = sorted(range(NCOMBO), key=_SCORE.__getitem__, reverse=True)


def _percentiles():
    pct = [0.0] * NCOMBO
    i = 0
    while i < NCOMBO:
        j = i
        while j < NCOMBO and _SCORE[PREFLOP_ORDER[j]] == _SCORE[PREFLOP_ORDER[i]]:
            j += 1
        for k in range(i, j):
            pct[PREFLOP_ORDER[k]] = (i + j) / 2 / NCOMBO
        i = j
    return pct


COMBO_PCT = _percentiles()


def combo_index(a, b):
    return COMBO_INDEX[(a, b) if a > b else (b, a)]


def percentile(a, b):
    return COMBO_PCT[combo_index(a, b)]


Rec = namedtuple("Rec", "player street kind amount to")
Action = namedtuple("Action", "kind amount")
Action.__new__.__defaults__ = (0,)


class GameState:
    __slots__ = ("hand_id", "hero", "hole", "board", "pot", "to_call", "my_bet", "my_stack",
                 "min_raise_to", "max_raise_to", "big_blind", "players", "active", "history",
                 "stacks")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def street(self):
        return {0: 0, 3: 1, 4: 2, 5: 3}[len(self.board)]


Event = namedtuple("Event", "player street sit act jam rec")

PRIORS = {
    ("unopened", "raise"): (0.45, 0.18),
    ("unopened", "call"): (0.15, 0.10),
    ("vs_raise", "fold"): (0.50, 0.75),
    ("vs_raise", "call"): (0.38, 0.18),
    ("vs_raise", "raise"): (0.12, 0.07),
    ("vs_3bet", "fold"): (0.55, 0.60),
    ("vs_3bet", "call"): (0.30, 0.27),
    ("vs_3bet", "raise"): (0.15, 0.13),
    ("p_no_bet", "raise"): (0.40, 0.30),
    ("p_vs_bet", "fold"): (0.42, 0.50),
    ("p_vs_bet", "call"): (0.46, 0.40),
    ("p_vs_bet", "raise"): (0.12, 0.10),
    ("p_vs_raise", "fold"): (0.50, 0.55),
    ("p_vs_raise", "call"): (0.40, 0.36),
    ("p_vs_raise", "raise"): (0.10, 0.09),
    ("jam", "jam"): (0.03, 0.02),
}


def classify(history, bb):
    out = []
    street = None
    level = 0
    raises = 0
    bets = {}
    for r in history:
        if r.street != street:
            street = r.street
            level = 0
            raises = 0
            bets = {}
        if r.kind in ("sb", "bb"):
            bets[r.player] = r.to
            level = max(level, r.to)
            continue
        if street == 0:
            sit = "unopened" if raises == 0 else "vs_raise" if raises == 1 else "vs_3bet"
        else:
            sit = "p_no_bet" if raises == 0 else "p_vs_bet" if raises == 1 else "p_vs_raise"
        jam = street == 0 and r.kind == "raise" and r.to >= 25 * bb
        out.append(Event(r.player, street, sit, r.kind, jam, r))
        if r.kind == "raise":
            raises += 1
            level = max(level, r.to)
        if r.kind in ("call", "raise"):
            bets[r.player] = r.to
    return out


class Model:
    def __init__(self, strength=6.0):
        self.opp = defaultdict(int)
        self.cnt = defaultdict(int)
        self.hands = defaultdict(int)
        self.strength = strength

    def observe(self, events, hero):
        seen = set()
        for e in events:
            if e.player == hero:
                continue
            seen.add(e.player)
            self.opp[(e.player, e.sit)] += 1
            self.cnt[(e.player, e.sit, e.act)] += 1
            if e.street == 0:
                self.opp[(e.player, "jam")] += 1
                if e.jam:
                    self.cnt[(e.player, "jam", "jam")] += 1
        for p in seen:
            self.hands[p] += 1

    def freq(self, player, sit, act, n=2):
        prior = PRIORS[(sit, act)][0 if n <= 2 else 1]
        k = 4.0 if sit == "jam" else self.strength
        return (self.cnt[(player, sit, act)] + prior * k) / (self.opp[(player, sit)] + k)


_Q = [0.25 + 0.75 * (1 - p) ** 2 for p in COMBO_PCT]
_QCUM = []
_t = 0.0
for _q in _Q:
    _t += _q
    _QCUM.append(_t)
_ALL = range(NCOMBO)


class Sample:
    def __init__(self, hero, rng, k):
        h0, h1 = hero
        idx = [i for i in rng.choices(_ALL, cum_weights=_QCUM, k=k)
               if h0 not in COMBOS[i] and h1 not in COMBOS[i]]
        self.combos = [COMBOS[i] for i in idx]
        self.base = [1.0 / _Q[i] for i in idx]
        pct = [COMBO_PCT[i] for i in idx]
        self.size = len(idx)
        self.pre_order = sorted(range(self.size), key=pct.__getitem__)
        self._boards = {}

    def board(self, board):
        hit = self._boards.get(len(board))
        if hit is None:
            dead = set(board)
            b = list(board)
            vals = [-1 if x in dead or y in dead else evaluate([x, y] + b) for x, y in self.combos]
            order = sorted((i for i in range(self.size) if vals[i] >= 0),
                           key=vals.__getitem__, reverse=True)
            hit = self._boards[len(board)] = (vals, order)
        return hit


def narrow(w, order, lo, hi, inner, floor):
    total = 0.0
    for i in order:
        total += w[i]
    if total <= 0:
        return
    cum = 0.0
    for i in order:
        x = w[i]
        if x:
            mid = (cum + x * 0.5) / total
            cum += x
            if mid < lo:
                w[i] = x * inner
            elif mid > hi:
                w[i] = x * floor


def keep_top(w, order, hi, floor):
    mult = [1.0] * len(w)
    total = 0.0
    for i in order:
        total += w[i]
    if total <= 0:
        return mult
    cum = 0.0
    for i in order:
        x = w[i]
        if x:
            if (cum + x * 0.5) / total > hi:
                mult[i] = floor
            cum += x
    return mult


def simulate(hero, board, sample, ranges, trials, rng):
    hero = list(hero)
    board = list(board)
    dead = set(hero) | set(board)
    deck = [c for c in range(52) if c not in dead]
    nd = len(deck)
    need = 5 - len(board)
    combos = sample.combos
    idx = range(sample.size)
    picks = []
    for w in ranges:
        cum = []
        t = 0.0
        for x in w:
            t += x
            cum.append(t)
        if t <= 0:
            cum = None
        picks.append(rng.choices(idx, cum_weights=cum, k=trials))
    rnd = rng.random
    out = []
    for t in range(trials):
        chosen = [p[t] for p in picks]
        used = set()
        clash = False
        for i in chosen:
            a, b = combos[i]
            if a in used or b in used:
                clash = True
                break
            used.add(a)
            used.add(b)
        if clash:
            continue
        full = board
        if need:
            run = []
            while len(run) < need:
                c = deck[int(rnd() * nd)]
                if c not in used:
                    used.add(c)
                    run.append(c)
            full = board + run
        hv = evaluate(hero + full)
        res = 1.0
        for i in chosen:
            a, b = combos[i]
            v = evaluate([a, b] + full)
            if v > hv:
                res = 0.0
                break
            if v == hv:
                res = 0.5
        out.append((chosen, res))
    return out


def sim_equity(sim, mults=None):
    won = tot = 0.0
    for chosen, res in sim:
        x = 1.0
        if mults:
            for m, i in zip(mults, chosen):
                x *= m[i]
        tot += x
        won += x * res
    return won / tot if tot > 0 else 0.5


def river_equity(hv, vals, ranges, mults=None):
    eq = 1.0
    for k, w in enumerate(ranges):
        m = mults[k] if mults else None
        won = tot = 0.0
        for i, v in enumerate(vals):
            x = w[i]
            if x and v >= 0:
                if m:
                    x *= m[i]
                tot += x
                if hv > v:
                    won += x
                elif hv == v:
                    won += x * 0.5
        eq *= won / tot if tot > 0 else 0.5
    return eq



FLOOR = {1: 0.25, 2: 0.18, 3: 0.10}
BOARD_LEN = {1: 3, 2: 4, 3: 5}


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class Bot:
    def __init__(self, seed=None, trials=160, strict=False, samples=260):
        self.rng = random.Random(seed)
        self.trials = trials
        self.samples = samples
        self._sample = None
        self.strict = strict
        self.model = Model()
        self._hand = None
        self._hist = []
        self._hero = None
        self._bb = 20

    def decide(self, s):
        if s.hand_id != self._hand:
            self._commit()
            self._hand = s.hand_id
            self._sample = None
        self._hist = list(s.history)
        self._hero = s.hero
        self._bb = s.big_blind
        try:
            a = self._postflop(s) if s.board else self._preflop(s)
        except Exception:
            if self.strict:
                raise
            a = Action("check")
        return self._legal(s, a)

    def end_hand(self, history=None, showdown=None):
        if history:
            self._hist = list(history)
        self._commit()

    def _commit(self):
        if self._hist:
            self.model.observe(classify(self._hist, self._bb), self._hero)
        self._hist = []

    def _legal(self, s, a):
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        if a.kind == "raise" and can_raise:
            amt = int(round(a.amount))
            return Action("raise", int(clamp(amt, s.min_raise_to, s.max_raise_to)))
        if a.kind == "fold" and s.to_call > 0:
            return Action("fold")
        return Action("call") if s.to_call > 0 else Action("check")

    def _raise(self, s, to):
        if to >= 0.4 * (s.my_stack + s.my_bet):
            to = s.max_raise_to
        return Action("raise", to)

    def _in_position(self, s):
        live = [p for p in s.players if p in s.active]
        return bool(live) and live[-1] == s.hero

    def _update(self, w, e, s, n, sample):
        f = lambda act: self.model.freq(e.player, e.sit, act, n)
        if e.street == 0:
            order = sample.pre_order
            if e.jam:
                narrow(w, order, 0, self.model.freq(e.player, "jam", "jam", n), 1, 0.02)
            elif e.act == "raise":
                narrow(w, order, 0, f("raise"), 1, 0.04)
            elif e.act == "call":
                fr = f("raise")
                narrow(w, order, fr * 0.6, fr + f("call"), 0.35, 0.04)
            return
        _, order = sample.board(s.board[:BOARD_LEN[e.street]])
        floor = FLOOR[e.street]
        if e.sit == "p_no_bet":
            if e.act == "raise":
                narrow(w, order, 0, f("raise"), 1, floor)
            elif e.act == "check":
                narrow(w, order, f("raise"), 1, 0.35, 1)
        elif e.act == "raise":
            narrow(w, order, 0, f("raise"), 1, floor * 0.6)
        elif e.act == "call":
            narrow(w, order, f("raise"), 1 - f("fold"), 0.5, 0.05)

    def _ranges(self, s, events):
        if self._sample is None:
            self._sample = Sample(s.hole, self.rng, self.samples)
        sample = self._sample
        n = len(s.players)
        vals = sample.board(s.board)[0] if s.board else None
        out = {}
        for v in s.active:
            if v == s.hero:
                continue
            w = list(sample.base)
            for e in events:
                if e.player == v:
                    self._update(w, e, s, n, sample)
            if vals:
                w = [0.0 if vals[i] < 0 else x for i, x in enumerate(w)]
            out[v] = w
        return out

    def _preflop(self, s):
        bb = s.big_blind
        n = len(s.players)
        allev = classify(s.history, bb)
        events = [e for e in allev if e.street == 0]
        raises = [e for e in events if e.act == "raise"]
        p = percentile(*s.hole)
        villains = [v for v in s.active if v != s.hero]
        level = s.my_bet + s.to_call
        freq = self.model.freq
        rnd = self.rng.random

        if raises and (s.to_call >= 0.3 * s.my_stack or raises[-1].jam or level >= 25 * bb):
            ranges = self._ranges(s, events)
            committed = [w for v, w in ranges.items()
                         if any(e.player == v and e.act in ("raise", "call") for e in events)]
            sim = simulate(s.hole, [], self._sample, committed or list(ranges.values()),
                           self.trials, self.rng)
            eq = sim_equity(sim)
            if eq * (s.pot + s.to_call) - s.to_call > 0.04 * s.pot:
                if eq > 0.62:
                    return Action("raise", s.max_raise_to)
                return Action("call")
            return Action("fold")

        if not raises:
            limpers = sum(1 for e in events if e.act == "call")
            if n == 2:
                v = villains[0]
                if s.to_call > 0:
                    fold_f = freq(v, "vs_raise", "fold", 2)
                    width, size = 0.82, 2.5
                    if fold_f > 0.6:
                        width = 1.0
                    elif fold_f < 0.25:
                        width, size = 0.65, 3.0
                    if freq(v, "vs_raise", "raise", 2) > 0.3:
                        width = min(width, 0.55)
                    return self._raise(s, size * bb) if p < width else Action("fold")
                return self._raise(s, 3.5 * bb) if p < 0.40 else Action("check")
            acted = {e.player for e in events}
            behind = [v for v in villains if v not in acted]
            pct = {0: 0.22, 1: 0.45, 2: 0.42, 3: 0.26, 4: 0.19, 5: 0.15, 6: 0.12}.get(len(behind), 0.10)
            loose = sum(1 - freq(v, "vs_raise", "fold", n) for v in villains) / max(1, len(villains))
            steal = 1.0
            for v in behind:
                steal *= freq(v, "vs_raise", "fold", n)
            if behind and steal > 0.6:
                pct = max(pct, min(1.0, 2.2 * steal - 0.7))
            else:
                pct *= clamp(1.3 - 1.0 * loose, 0.55, 1.1)
            if limpers:
                pct *= 0.8
            size = 2.5 + limpers + 7 * max(0.0, loose - 0.3)
            if p < pct:
                return self._raise(s, min(size, 9) * bb)
            if s.to_call <= 0:
                return Action("check")
            if p < 0.35 and s.to_call <= bb and (limpers or s.my_bet > 0):
                return Action("call")
            return Action("fold")

        r = raises[-1].player
        ip = self._in_position(s)
        if len(raises) == 1:
            base = 0.45 if n == 2 else 0.18
            width = clamp(freq(r, "unopened", "raise", n) / base, 0.5, 2.2)
            sizeadj = clamp((2.5 * bb / level) ** 0.5, 0.45, 1.2)
            to = level * (3.2 if ip else 3.8)
            if n == 2:
                bluff = 0.45 < p < 0.52 and freq(r, "vs_3bet", "fold", 2) > 0.5 and rnd() < 0.5
                if p < 0.08 * width or bluff:
                    return self._raise(s, to)
                if p < min(0.92, 0.62 * width * sizeadj):
                    return Action("call")
                return Action("fold")
            if p < 0.045 * width:
                return self._raise(s, to)
            if p < (0.24 if s.my_bet >= bb else 0.11) * width * sizeadj:
                return Action("call")
            return Action("fold")

        if len(raises) == 2:
            width = clamp(freq(r, "vs_raise", "raise", n) / (0.12 if n == 2 else 0.07), 0.5, 3.0)
            invested = any(e.player == s.hero and e.act == "raise" for e in events)
            if p < 0.03 * width:
                return self._raise(s, 2.3 * level)
            if p < ((0.30 if n == 2 else 0.14) if invested else 0.05) * width:
                return Action("call")
            return Action("fold")

        width = clamp(freq(r, "vs_3bet", "raise", n) / 0.15, 0.5, 3.0)
        if p < 0.022 * width:
            return Action("raise", s.max_raise_to)
        if p < 0.045 * width:
            return Action("call")
        return Action("fold")

    def _postflop(self, s):
        n = len(s.players)
        events = classify(s.history, s.big_blind)
        ranges = self._ranges(s, events)
        sample = self._sample
        rl = list(ranges.values())
        st = s.street
        P = float(s.pot)
        c = s.to_call
        freq = self.model.freq
        vals, order = sample.board(s.board)
        if st == 3:
            hv = evaluate(list(s.hole) + list(s.board))
            eq_with = lambda mults=None: river_equity(hv, vals, rl, mults)
        else:
            sim = simulate(s.hole, s.board, sample, rl, self.trials, self.rng)
            eq_with = lambda mults=None: sim_equity(sim, mults)
        eq = eq_with()
        ip = self._in_position(s)
        can_raise = s.max_raise_to > s.my_bet + c and any(
            s.stacks.get(v, 1) > 0 for v in ranges)

        def response(sit, x, ref):
            phi = 1.0
            mults = []
            for v, w in ranges.items():
                ff = clamp(freq(v, sit, "fold", n) * (x / ref) ** 0.7, 0.02, 0.95)
                phi *= ff
                mults.append(keep_top(w, order, 1 - ff, 0.02))
            return phi, eq_with(mults)

        if c <= 0:
            real = (1.0 if ip else 0.93) if st == 3 else (0.95 if ip else 0.85)
            best, best_ev = Action("check"), eq * P * real
            if not can_raise:
                return best
            fr = max(freq(v, "p_vs_bet", "raise", n) for v in ranges)
            for frac in (0.33, 0.7, 1.1):
                b = frac * P
                if b >= 0.6 * s.my_stack:
                    b = s.my_stack
                b = clamp(b, s.min_raise_to - s.my_bet, s.my_stack)
                phi, eqc = response("p_vs_bet", b / (P + b), 0.4)
                ev = phi * P + (1 - phi) * (eqc * (P + 2 * b) - b)
                if eqc < 0.8:
                    ev -= (1 - phi) * fr * b * 0.5
                if ev > best_ev + 0.02 * P:
                    best, best_ev = Action("raise", s.my_bet + b), ev
                if b >= s.my_stack:
                    break
            return best

        real = 1.0 if st == 3 else (0.96 if ip else 0.90)
        ev_call = eq * real * (P + c) - c
        best, best_ev = (Action("call"), ev_call) if ev_call > 0 else (Action("fold"), 0.0)
        if can_raise:
            rr = max(freq(v, "p_vs_raise", "raise", n) for v in ranges)
            for frac in (0.6, 1.0):
                a = c + frac * (P + c)
                if a >= 0.6 * s.my_stack:
                    a = s.my_stack
                a = clamp(a, s.min_raise_to - s.my_bet, s.my_stack)
                phi, eqc = response("p_vs_raise", (a - c) / (P + a), 0.3)
                ev = phi * P + (1 - phi) * (eqc * (P + 2 * a - c) - a)
                if eqc < 0.8:
                    ev -= (1 - phi) * rr * a * 0.5
                if ev > best_ev + 0.15 * P:
                    best, best_ev = Action("raise", s.my_bet + a), ev
                if a >= s.my_stack:
                    break
        return best



STREETS = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
KINDS = {"small_blind": "sb", "big_blind": "bb"}


def convert_history(history):
    out = []
    street = None
    bets = {}
    for h in history:
        st = STREETS[h["street"]]
        if st != street:
            street = st
            bets = {}
        seat = h["seat"]
        kind = KINDS.get(h["action"], h["action"])
        amount = h.get("amount") or 0
        prev = bets.get(seat, 0)
        if kind in ("sb", "bb", "raise"):
            to = amount
        elif kind == "call":
            to = prev + amount
        else:
            to = prev
        bets[seat] = to
        out.append(Rec(seat, st, kind, to - prev, to))
    return out


def convert_state(state):
    n = len(state["stacks"])
    seat = state["seat"]
    button = state["button"]
    players = [(button + 1 + i) % n for i in range(n)]
    folded = state["folded"]
    return GameState(
        hand_id=state["hand_number"], hero=seat,
        hole=[parse_card(c) for c in state["hole_cards"]],
        board=[parse_card(c) for c in state["board"]],
        pot=state["pot"], to_call=state["to_call"], my_bet=state["bets"][seat],
        my_stack=state["stacks"][seat], min_raise_to=state.get("min_raise_to") or 0,
        max_raise_to=state.get("max_raise_to") or 0, big_blind=state["big_blind"],
        players=players, active=[p for p in players if not folded[p]],
        history=convert_history(state["history"]),
        stacks=dict(enumerate(state["stacks"])))


class Agent:
    BANK = 8.5
    OVERHEAD = 0.0004

    def __init__(self):
        self.bot = Bot()
        self.base_trials = self.bot.trials
        self.spent = 0.0
        self.hands = 1000

    def on_table_start(self, info):
        self.hands = info.get("hands", 1000)

    def act(self, state):
        t = time.perf_counter()
        legal = state.get("legal_actions", ())
        try:
            left = max(1, self.hands - state.get("hand_number", 1) + 1)
            per_hand = (self.BANK - self.spent) / left
            self.bot.trials = (self.base_trials if per_hand > 0.004 else
                               60 if per_hand > 0.002 else 24 if per_hand > 0.0008 else 0)
            if self.bot.trials == 0:
                out = {"action": "check" if "check" in legal else "fold"}
            else:
                a = self.bot.decide(convert_state(state))
                out = {"action": a.kind}
                if a.kind == "raise":
                    out["amount"] = int(a.amount)
        except Exception:
            out = {"action": "check" if "check" in legal else "fold"}
        self.spent += time.perf_counter() - t + self.OVERHEAD
        return out

    def on_hand_end(self, summary):
        t = time.perf_counter()
        try:
            self.bot.end_hand(convert_history(summary["history"]))
        except Exception:
            pass
        self.spent += time.perf_counter() - t

