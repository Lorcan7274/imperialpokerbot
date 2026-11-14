from bisect import bisect
from itertools import accumulate
from time import perf_counter

from .cards import _CACHE, RANK_KEY, SUIT_KEY, _rank_value, evaluate
from .preflop import COMBO_PCT, COMBOS, NCOMBO

_Q = [0.25 + 0.75 * (1 - p) ** 2 for p in COMBO_PCT]
_QCUM = []
_t = 0.0
for _q in _Q:
    _t += _q
    _QCUM.append(_t)
_ALL = range(NCOMBO)
STRATIFY = True
_BASE = [1.0 / q for q in _Q]
_RANK = [RANK_KEY[a] + RANK_KEY[b] for a, b in COMBOS]
_SUIT = [SUIT_KEY[a] + SUIT_KEY[b] for a, b in COMBOS]
_MASK = [1 << a | 1 << b for a, b in COMBOS]
_STRONG = [a >> 2 == b >> 2 or a >> 2 >= 11 or b >> 2 >= 11 for a, b in COMBOS]


def made(a, b, br, top):
    if a == b:
        return a > top or a in br
    return (a == top or b == top or (a in br and b in br)
            or (a in br and br.count(a) > 1) or (b in br and br.count(b) > 1))


def strong_hand(hole, board):
    br = [c >> 2 for c in board]
    if evaluate(list(hole) + list(board)) >> 20 >= 4:
        return True
    return made(hole[0] >> 2, hole[1] >> 2, br, max(br))


class Sample:
    def __init__(self, hero, rng, k):
        dead = 1 << hero[0] | 1 << hero[1]
        idx = [i for i in rng.choices(_ALL, cum_weights=_QCUM, k=k) if not _MASK[i] & dead]
        self.combos = [COMBOS[i] for i in idx]
        self.base = [_BASE[i] for i in idx]
        self.rank = [_RANK[i] for i in idx]
        self.suit = [_SUIT[i] for i in idx]
        self.mask = [_MASK[i] for i in idx]
        self.strong = [_STRONG[i] for i in idx]
        pct = [COMBO_PCT[i] for i in idx]
        self.size = len(idx)
        self.pre_order = sorted(range(self.size), key=pct.__getitem__)
        self._boards = {}
        self._flags = {}

    def flags(self, board):
        hit = self._flags.get(len(board))
        if hit is None:
            vals = self.board(board)[0]
            br = [c >> 2 for c in board]
            top = max(br)
            hit = self._flags[len(board)] = [
                v >= 0 and (v >> 20 >= 4 or made(x >> 2, y >> 2, br, top))
                for v, (x, y) in zip(vals, self.combos)]
        return hit

    def board(self, board):
        hit = self._boards.get(len(board))
        if hit is None:
            b = list(board)
            dead = rk = sk = 0
            for c in b:
                dead |= 1 << c
                rk += RANK_KEY[c]
                sk += SUIT_KEY[c]
            sk += 0x3333
            get = _CACHE.get
            vals = []
            add = vals.append
            for m, r, u, xy in zip(self.mask, self.rank, self.suit, self.combos):
                if m & dead:
                    add(-1)
                elif (sk + u) & 0x8888:
                    add(evaluate(list(xy) + b))
                else:
                    v = get(rk + r)
                    if v is None:
                        v = _CACHE[rk + r] = _rank_value(rk + r)
                    add(v)
            order = sorted((i for i in range(self.size) if vals[i] >= 0),
                           key=vals.__getitem__, reverse=True)
            hit = self._boards[len(board)] = (vals, order)
        return hit


def _cut(xs, cums, total, bound, above):
    lo, hi = 0, len(xs)
    while lo < hi:
        k = (lo + hi) // 2
        mid = ((cums[k - 1] if k else 0.0) + xs[k] * 0.5) / total
        if mid > bound or (mid == bound and not above):
            hi = k
        else:
            lo = k + 1
    return lo


def narrow(w, order, lo, hi, inner, floor, rare=0.0):
    xs = [w[i] for i in order]
    cums = list(accumulate(xs))
    total = cums[-1] if cums else 0.0
    if total <= 0:
        return
    # shares of the range are cumulative, so each band is a prefix or a suffix of the order
    p = _cut(xs, cums, total, lo, False)
    q = max(p, _cut(xs, cums, total, hi, True))
    if not q and rare and 0 < xs[0] < total:
        # a share smaller than one sampled hand would keep nothing: the best hand stays, the rest share `rare`
        q = 1
        floor = min(1.0, rare * xs[0] / ((1 - rare) * (total - xs[0])))
    if inner != 1:
        for i, x in zip(order[:p], xs):
            w[i] = x * inner
    if floor != 1:
        for i, x in zip(order[q:], xs[q:]):
            w[i] = x * floor


def keep_top(w, order, hi, floor):
    mult = [1.0] * len(w)
    xs = [w[i] for i in order]
    cums = list(accumulate(xs))
    total = cums[-1] if cums else 0.0
    if total <= 0:
        return mult
    q = _cut(xs, cums, total, hi, True)
    for i, x in zip(order[q:], xs[q:]):
        if x:
            mult[i] = floor
    return mult


def simulate(hero, board, sample, ranges, trials, rng, deadline=None):
    hero = list(hero)
    board = list(board)
    dead = set(hero) | set(board)
    deck = [c for c in range(52) if c not in dead]
    nd = len(deck)
    need = 5 - len(board)
    combos, masks, ranks, suits = sample.combos, sample.mask, sample.rank, sample.suit
    idx = range(sample.size)
    picks = []
    order = sample.board(board)[1] if board else sample.pre_order
    for w in ranges:
        cum = list(accumulate([w[i] for i in order]))
        total = cum[-1] if cum else 0.0
        if total <= 0 or not STRATIFY:
            flat = list(accumulate(w))
            picks.append(rng.choices(idx, cum_weights=flat if flat and flat[-1] > 0 else None, k=trials))
            continue
        # evenly spaced draws along the range from strongest to weakest hand steady a short simulation
        step = total / trials
        u = rng.random()
        top = len(order) - 1
        pick = [order[min(top, bisect(cum, (j + u) * step))] for j in range(trials)]
        rng.shuffle(pick)
        picks.append(pick)
    rnd = rng.random
    get = _CACHE.get
    rk0 = RANK_KEY[hero[0]] + RANK_KEY[hero[1]]
    sk0 = SUIT_KEY[hero[0]] + SUIT_KEY[hero[1]] + 0x3333
    for c in board:
        rk0 += RANK_KEY[c]
        sk0 += SUIT_KEY[c]
    hrk = RANK_KEY[hero[0]] + RANK_KEY[hero[1]]
    hsk = SUIT_KEY[hero[0]] + SUIT_KEY[hero[1]]
    out = []
    for t in range(trials):
        if deadline and t & 7 == 7 and perf_counter() > deadline:
            break
        chosen = []
        used = 0
        for p in picks:
            i = p[t]
            if masks[i] & used:
                # a hand sharing a card with an earlier opponent is redrawn from the same range
                for k in (t - 1, t - 2, t - 3):
                    i = p[k]
                    if not masks[i] & used:
                        break
                else:
                    chosen = None
                    break
            used |= masks[i]
            chosen.append(i)
        if chosen is None:
            continue
        rk, sk = rk0, sk0
        full = board
        if need:
            run = []
            while len(run) < need:
                c = deck[int(rnd() * nd)]
                if not used >> c & 1:
                    used |= 1 << c
                    run.append(c)
                    rk += RANK_KEY[c]
                    sk += SUIT_KEY[c]
            full = board + run
        if sk & 0x8888:
            hv = evaluate(hero + full)
        else:
            hv = get(rk)
            if hv is None:
                hv = _CACHE[rk] = _rank_value(rk)
        rk -= hrk
        sk -= hsk
        res = 1.0
        for i in chosen:
            if (sk + suits[i]) & 0x8888:
                v = evaluate(list(combos[i]) + full)
            else:
                v = get(rk + ranks[i])
                if v is None:
                    v = _CACHE[rk + ranks[i]] = _rank_value(rk + ranks[i])
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


def runout_equity(hero, board, runs, sample, w, deadline=None):
    hero = list(hero)
    board = list(board)
    rows = [(x, sample.mask[i], sample.rank[i], sample.suit[i], sample.combos[i])
            for i, x in enumerate(w) if x]
    rk0 = 0
    sk0 = 0x3333
    for c in board:
        rk0 += RANK_KEY[c]
        sk0 += SUIT_KEY[c]
    hrk = RANK_KEY[hero[0]] + RANK_KEY[hero[1]]
    hsk = SUIT_KEY[hero[0]] + SUIT_KEY[hero[1]]
    get = _CACHE.get
    out = []
    for run in runs:
        if deadline and perf_counter() > deadline:
            break
        rk, sk, dead = rk0, sk0, 0
        for c in run:
            rk += RANK_KEY[c]
            sk += SUIT_KEY[c]
            dead |= 1 << c
        full = board + run
        if (sk + hsk) & 0x8888:
            hv = evaluate(hero + full)
        else:
            hv = get(rk + hrk)
            if hv is None:
                hv = _CACHE[rk + hrk] = _rank_value(rk + hrk)
        won = tot = 0.0
        for x, m, r, u, xy in rows:
            if m & dead:
                continue
            if (sk + u) & 0x8888:
                v = evaluate(list(xy) + full)
            else:
                v = get(rk + r)
                if v is None:
                    v = _CACHE[rk + r] = _rank_value(rk + r)
            tot += x
            if hv > v:
                won += x
            elif hv == v:
                won += 0.5 * x
        out.append(won / tot if tot else 0.5)
    return out
