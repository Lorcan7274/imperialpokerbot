from collections import defaultdict, namedtuple

Event = namedtuple("Event", "player street sit act jam rec fit big")

PRIORS = {
    ("unopened", "raise"): (0.45, 0.18),
    ("unopened", "call"): (0.15, 0.10),
    ("vs_raise", "fold"): (0.50, 0.75),
    ("vs_raise", "call"): (0.38, 0.18),
    ("vs_raise", "raise"): (0.12, 0.07),
    ("vs_3bet", "fold"): (0.55, 0.60),
    ("vs_3bet", "call"): (0.30, 0.27),
    ("vs_3bet", "raise"): (0.15, 0.13),
    ("p_no_bet", "raise"): (0.30, 0.25),
    ("p_no_bet:a", "raise"): (0.55, 0.55),
    ("p_vs_bet", "fold"): (0.42, 0.45),
    ("p_vs_bet", "call"): (0.46, 0.45),
    ("p_vs_bet", "raise"): (0.12, 0.10),
    ("p_vs_raise", "fold"): (0.45, 0.40),
    ("p_vs_raise", "call"): (0.42, 0.45),
    ("p_vs_raise", "raise"): (0.13, 0.15),
    ("jam", "jam"): (0.03, 0.02),
}
for _sit in ("p_vs_bet", "p_vs_raise"):
    for _tag, _f, _c, _r in ((":k", 0.55, 0.38, 0.07), (":a", 0.22, 0.60, 0.18), (":s", 0.28, 0.62, 0.10)):
        PRIORS[(_sit + _tag, "fold")] = (_f, _f)
        PRIORS[(_sit + _tag, "call")] = (_c, _c)
        PRIORS[(_sit + _tag, "raise")] = (_r, _r)


def line(p, raises, agg, stuck, checked):
    if raises == 0:
        return ":a" if p in agg else ""
    return ":k" if p in checked else ":a" if p in agg else ":s" if p in stuck else ""


def classify(history, bb, stack=2000, ctx=None):
    out = []
    agg, stuck, checked = set(), set(), set()
    street = None
    level = 0
    raises = 0
    last = bb
    pot = 0
    bets = {}
    paid = {}
    for r in history:
        if r.street != street:
            street = r.street
            level = 0
            raises = 0
            last = bb
            bets = {}
            checked = set()
        p = r.player
        prev = bets.get(p, 0)
        if r.kind in ("sb", "bb"):
            bets[p] = r.to
            paid[p] = paid.get(p, 0) + r.to
            pot += r.to
            level = max(level, r.to)
            continue
        if street == 0:
            sit = "unopened" if raises == 0 else "vs_raise" if raises == 1 else "vs_3bet"
        else:
            sit = ("p_no_bet" if raises == 0 else "p_vs_bet" if raises == 1 else "p_vs_raise") + line(
                p, raises, agg, stuck, checked)
        fit = False
        big = level - prev > 2 * bb
        if r.kind == "raise":
            cap = prev + stack - paid.get(p, 0)
            fit = r.to == min(min(level + last, cap) + pot // 2, cap)
        jam = street == 0 and r.kind == "raise" and r.to >= 25 * bb
        out.append(Event(p, street, sit, r.kind, jam, r, fit, big))
        if r.kind == "raise":
            raises += 1
            if r.to - level >= last:
                last = r.to - level
            level = max(level, r.to)
            agg.add(p)
        elif r.kind == "call" and street:
            stuck.add(p)
        elif r.kind == "check":
            checked.add(p)
        if r.kind in ("call", "raise"):
            bets[p] = r.to
            paid[p] = paid.get(p, 0) + r.to - prev
            pot += r.to - prev
    if ctx is not None:
        ctx.update(agg=agg, stuck=stuck, checked=checked)
    return out


class Model:
    def __init__(self, strength=6.0):
        self.opp = defaultdict(int)
        self.cnt = defaultdict(int)
        self.hands = defaultdict(int)
        self.strength = strength
        self.rtot = defaultdict(int)
        self.rfit = defaultdict(int)
        self.acts = defaultdict(int)
        self.viol = defaultdict(int)
        self.badshow = defaultdict(int)

    def observe(self, events, hero, shown=None):
        seen = set()
        hot = set()
        for e in events:
            p = e.player
            if p == hero:
                continue
            seen.add(p)
            self.acts[p] += 1
            self.opp[(p, e.sit)] += 1
            self.cnt[(p, e.sit, e.act)] += 1
            if e.street == 0:
                self.opp[(p, "jam")] += 1
                if e.jam:
                    self.cnt[(p, "jam", "jam")] += 1
            if e.act == "raise":
                self.rtot[p] += 1
                self.rfit[p] += e.fit
                hot.add(p)
            elif e.act == "call" and e.big:
                hot.add(p)
            elif e.act == "fold" and (p in hot or not e.big):
                self.viol[p] += 1
        for p in seen:
            self.hands[p] += 1
        for p, cards in (shown or {}).items():
            if p != hero and p in seen and len(cards) == 2:
                a, b = cards[0] >> 2, cards[1] >> 2
                if (a == b or a >= 11 or b >= 11) != (p in hot):
                    self.badshow[p] += 1

    def is_clone(self, p):
        n = self.rtot[p]
        return (n >= 2 and self.rfit[p] * 8 >= n * 7 and self.badshow[p] < 3
                and self.viol[p] <= 3 + 0.01 * self.acts[p])

    def freq(self, player, sit, act, n=2):
        prior = PRIORS[(sit, act)][0 if n <= 2 else 1]
        k = 4.0 if sit == "jam" or sit[1] == "_" else self.strength
        return (self.cnt[(player, sit, act)] + prior * k) / (self.opp[(player, sit)] + k)
