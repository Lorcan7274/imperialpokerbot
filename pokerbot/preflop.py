from .cards import RANKS
from .preflop_table import EQ

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
