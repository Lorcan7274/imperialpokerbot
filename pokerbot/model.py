from collections import defaultdict, namedtuple

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
