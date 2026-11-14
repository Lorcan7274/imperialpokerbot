from itertools import accumulate
from time import perf_counter

from .cards import evaluate
from .preflop import COMBO_PCT, COMBOS, NCOMBO

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
        self.strong = [a >> 2 == b >> 2 or a >> 2 >= 11 or b >> 2 >= 11 for a, b in self.combos]
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


def simulate(hero, board, sample, ranges, trials, rng, deadline=None):
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
        cum = list(accumulate(w))
        picks.append(rng.choices(idx, cum_weights=cum if cum and cum[-1] > 0 else None, k=trials))
    rnd = rng.random
    out = []
    for t in range(trials):
        if deadline and t & 7 == 7 and perf_counter() > deadline:
            break
        chosen = []
        used = set()
        for p in picks:
            i = p[t]
            a, b = combos[i]
            if a in used or b in used:
                # a hand sharing a card with an earlier opponent is redrawn from the same range
                for k in (t - 1, t - 2, t - 3):
                    i = p[k]
                    a, b = combos[i]
                    if a not in used and b not in used:
                        break
                else:
                    chosen = None
                    break
            used.add(a)
            used.add(b)
            chosen.append(i)
        if chosen is None:
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
