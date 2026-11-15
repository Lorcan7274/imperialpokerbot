from time import perf_counter

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


_STOP = perf_counter() + 1.5


def _warm(r, left, key):
    if r == 13:
        if left <= 2 and perf_counter() < _STOP:
            _CACHE[key] = _rank_value(key)
        return
    for k in range(min(4, left) + 1):
        _warm(r + 1, left - k, key + (k << (3 * r)))


_warm(0, 7, 0)


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
