from collections import defaultdict, namedtuple

from .preflop import percentile

Event = namedtuple("Event", "player street sit act jam rec fit big frac")

EDGES = (0.36, 0.48, 0.58, 0.68, 0.88)


def tell_key(e):
    if e.street == 0:
        return None
    g = 1 if e.street == 3 else 0
    if e.act == "check" and e.sit[:8] == "p_no_bet":
        return (g, "x")
    if e.act != "raise":
        return None
    if e.sit[:8] != "p_no_bet":
        return (g, "r")
    k = 0
    for edge in EDGES:
        if e.frac >= edge:
            k += 1
    return (g, k)

PRIORS = {
    ("unopened", "raise"): (0.45, 0.17),
    ("unopened", "call"): (0.15, 0.05),
    ("unopened:l", "raise"): (0.45, 0.33),
    ("unopened:l", "call"): (0.15, 0.06),
    ("unopened:b", "raise"): (0.45, 0.42),
    ("unopened:b", "call"): (0.15, 0.12),
    ("unopened:o", "raise"): (0.30, 0.28),
    ("unopened:o", "call"): (0.01, 0.01),
    ("unopened:l", "jam"): (0.012, 0.012),
    ("unopened:b", "jam"): (0.012, 0.012),
    ("unopened:o", "jam"): (0.012, 0.012),
    ("vs_raise", "fold"): (0.50, 0.75),
    ("vs_raise", "call"): (0.38, 0.18),
    ("vs_raise", "raise"): (0.12, 0.07),
    ("vs_3bet", "fold"): (0.55, 0.83),
    ("vs_3bet", "call"): (0.30, 0.10),
    ("vs_3bet", "raise"): (0.15, 0.07),
    ("p_no_bet", "raise"): (0.30, 0.25),
    ("p_no_bet:a", "raise"): (0.55, 0.55),
    ("p_vs_bet", "fold"): (0.42, 0.45),
    ("p_vs_bet", "call"): (0.46, 0.45),
    ("p_vs_bet", "raise"): (0.12, 0.10),
    ("p_vs_raise", "fold"): (0.45, 0.40),
    ("p_vs_raise", "call"): (0.42, 0.45),
    ("p_vs_raise", "raise"): (0.13, 0.15),
    ("jam", "jam"): (0.03, 0.02),
    ("unopened", "jam"): (0.012, 0.012),
    ("vs_raise", "jam"): (0.02, 0.02),
    ("vs_3bet", "jam"): (0.08, 0.06),
    ("re_raised", "jam"): (0.08, 0.08),
    ("vs_hero", "raise"): (0.12, 0.06),
    ("re_raised", "fold"): (0.70, 0.70),
    ("re_raised", "call"): (0.18, 0.18),
    ("re_raised", "raise"): (0.12, 0.12),
}
for _sit in ("p_vs_bet", "p_vs_raise"):
    for _tag, _f, _c, _r in ((":k", 0.55, 0.38, 0.07), (":a", 0.22, 0.60, 0.18), (":s", 0.28, 0.62, 0.10),
                             (":x", 0.08, 0.62, 0.30), (":b", 0.08, 0.64, 0.28)):
        PRIORS[(_sit + _tag, "fold")] = (_f, _f)
        PRIORS[(_sit + _tag, "call")] = (_c, _c)
        PRIORS[(_sit + _tag, "raise")] = (_r, _r)


def line(p, raises, agg, stuck, checked, firm=(), bold=()):
    if raises == 0:
        return ":a" if p in agg else ""
    if raises > 1 and p in firm:
        return ":x"
    # in the real field a bet of 0.58 pot or more almost never folds to a raise, and smaller bets often do
    if raises > 1 and p in bold:
        return ":b"
    return ":k" if p in checked else ":a" if p in agg else ":s" if p in stuck else ""


def classify(history, bb, stack=2000, ctx=None, n=0, now=None):
    out = []
    agg, stuck, checked, firm = set(), set(), set(), set()
    bold = set()
    street = None
    level = 0
    raises = 0
    last = bb
    pot = 0
    acted = 0
    bets = {}
    paid = {}
    for r in history:
        if r.street != street:
            street = r.street
            level = 0
            raises = 0
            last = bb
            # whoever checked the last street through is still read as having checked when bet into
            checked = {q for q in checked if not bets.get(q)}
            bets = {}
            bold = set()
        p = r.player
        prev = bets.get(p, 0)
        if r.kind in ("sb", "bb"):
            bets[p] = r.to
            paid[p] = paid.get(p, 0) + r.to
            pot += r.to
            level = max(level, r.to)
            continue
        if street == 0:
            if raises == 0:
                # seats still to act behind: the blinds are last, and earlier seats open tighter
                left = n - 1 - acted if n else 9
                sit = "unopened" + (":o" if left <= 0 else ":b" if left == 1 else ":l" if left <= 3 else "")
                acted += 1
            else:
                sit = "re_raised" if raises == 2 and p in agg else "vs_raise" if raises == 1 else "vs_3bet"
        else:
            sit = ("p_no_bet" if raises == 0 else "p_vs_bet" if raises == 1 else "p_vs_raise") + line(
                p, raises, agg, stuck, checked, firm, bold)
        fit = False
        big = level - prev > 2 * bb
        if r.kind == "raise":
            cap = prev + stack - paid.get(p, 0)
            fit = r.to == min(min(level + last, cap) + pot // 2, cap)
        jam = street == 0 and r.kind == "raise" and r.to >= 25 * bb
        frac = r.to / pot if r.kind == "raise" and raises == 0 and street and pot > 0 else 0.0
        out.append(Event(p, street, sit, r.kind, jam, r, fit, big, frac))
        if r.kind == "raise":
            if street and raises:
                firm.add(p)
            elif frac >= EDGES[2]:
                bold.add(p)
            raises += 1
            if r.to - level >= last:
                last = r.to - level
            level = max(level, r.to)
            agg.add(p)
            checked.discard(p)
        elif r.kind == "call" and street:
            stuck.add(p)
            checked.discard(p)
            if raises > 1:
                firm.add(p)
        elif r.kind == "check":
            checked.add(p)
        if r.kind in ("call", "raise"):
            bets[p] = r.to
            paid[p] = paid.get(p, 0) + r.to - prev
            pot += r.to - prev
    if ctx is not None:
        if now is not None and now != street:
            checked = {q for q in checked if not bets.get(q)}
        ctx.update(agg=agg, stuck=stuck, checked=checked, firm=firm, bold=bold)
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
        self.tell = {}
        self.jamx = {}

    def observe(self, events, hero, shown=None):
        seen = set()
        hot = set()
        jams = set()
        last = None
        raises = 0
        for e in events:
            p = e.player
            facing = last
            if e.street == 0 and e.act == "raise":
                last = p
                raises += 1
            if p == hero:
                continue
            # a player who re-raises our opens in particular is read apart from how it treats the table
            if e.sit == "vs_raise" and facing == hero:
                self.opp[(p, "vs_hero")] += 1
                if e.act == "raise":
                    self.cnt[(p, "vs_hero", "raise")] += 1
            seen.add(p)
            self.acts[p] += 1
            if e.jam:
                jams.add(p)
            # how an opener answers a starter bot's re-raise says little about how it answers ours
            if e.sit != "re_raised" or facing is None or not self.is_clone(facing):
                self.opp[(p, e.sit)] += 1
                self.cnt[(p, e.sit, e.act)] += 1
                if e.jam:
                    self.cnt[(p, e.sit, "jam")] += 1
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
                if p in jams:
                    t = self.jamx.setdefault(p, [0, 0.0])
                    t[0] += 1
                    t[1] += percentile(*cards)

    def is_clone(self, p):
        n = self.rtot[p]
        # a starter bot that runs slowly times out and folds out of turn on about 2% of its actions
        return (n >= 2 and self.rfit[p] * 8 >= n * 7 and self.badshow[p] < 4
                and self.viol[p] <= 3 + 0.04 * self.acts[p])

    def sticky(self, p):
        opp = fold = 0
        for tag in ("", ":a", ":s", ":k"):
            opp += self.opp[(p, "p_vs_bet" + tag)]
            fold += self.cnt[(p, "p_vs_bet" + tag, "fold")]
        return opp >= 12 and fold <= 0.25 * opp

    def gives_up(self, player, n=2):
        return min(self.freq(player, "vs_raise", "fold", n), 1.0 - self.freq(player, "vs_hero", "raise", n))

    def opens(self, player, n=2):
        opp = cnt = 0
        for tag in ("", ":l", ":b", ":o"):
            opp += self.opp[(player, "unopened" + tag)]
            cnt += self.cnt[(player, "unopened" + tag, "raise")]
        return (cnt + (0.45 if n <= 2 else 0.18) * self.strength) / (opp + self.strength)

    def freq(self, player, sit, act, n=2):
        prior = PRIORS[(sit, act)][0 if n <= 2 else 1]
        k = 4.0 if sit == "jam" or sit == "re_raised" or sit[1] == "_" else self.strength
        return (self.cnt[(player, sit, act)] + prior * k) / (self.opp[(player, sit)] + k)
