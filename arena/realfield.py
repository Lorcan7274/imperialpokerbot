from arena.opponents import Base, raw_equity
from pokerbot.cards import evaluate
from pokerbot.preflop import percentile
from pokerbot.state import Action


class KitStarter(Base):
    """Exact port of the organisers' starter bot."""

    def decide(self, s):
        ranks = sorted(c >> 2 for c in s.hole)
        strong = ranks[0] == ranks[1] or ranks[1] >= 11
        if strong and s.max_raise_to > s.my_bet + s.to_call:
            return Action("raise", min(s.min_raise_to + s.pot // 2, s.max_raise_to))
        if s.to_call <= 0:
            return Action("check")
        if s.to_call <= 2 * s.big_blind or strong:
            return Action("call")
        return Action("fold")


class KitVariant(Base):
    """The starter bot as one team changed it: it also raises once both cards pair the board or one makes trips,
    and it loses about one action in fifty to a timeout."""

    def decide(self, s):
        if self.rng.random() < 0.02:
            return Action("check") if s.to_call <= 0 else Action("fold")
        a, b = (c >> 2 for c in s.hole)
        br = [c >> 2 for c in s.board]
        strong = a == b or max(a, b) >= 11 or (a in br and b in br) or (
            a in br and br.count(a) > 1) or (b in br and br.count(b) > 1)
        if strong and s.max_raise_to > s.my_bet + s.to_call:
            return Action("raise", min(s.min_raise_to + s.pot // 2, s.max_raise_to))
        if s.to_call <= 0:
            return Action("check")
        if s.to_call <= 2 * s.big_blind or strong:
            return Action("call")
        return Action("fold")


class TightIso(Base):
    """Tight bot that isolates limpers and value-bets, modelled on the round-one winners."""
    open_to = 70
    tight = 0.16

    def decide(self, s):
        bb = s.big_blind
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        if not s.board:
            p = percentile(*s.hole)
            pre = [r for r in s.history if r.street == 0 and r.kind in ("raise", "call")]
            raises = [r for r in pre if r.kind == "raise"]
            limpers = sum(1 for r in pre if r.kind == "call") if not raises else 0
            level = s.my_bet + s.to_call
            if not raises:
                if p < self.tight and can_raise:
                    return Action("raise", min(self.open_to + 20 * limpers, s.max_raise_to))
                return self.passive(s) if s.to_call <= 0 or (p < 0.3 and s.to_call <= bb // 2) else Action("fold")
            if p < 0.03 or (p < 0.05 and level > 25 * bb):
                return Action("raise", s.max_raise_to) if can_raise else Action("call")
            if p < 0.05 and can_raise and len(raises) == 1:
                return Action("raise", min(3 * level, s.max_raise_to))
            if p < 0.11 and s.to_call <= 6 * bb:
                return Action("call")
            return self.give_up(s)
        eq = raw_equity(s.hole, s.board, self.rng, 60)
        live = len(s.active) - 1
        eq = eq ** max(1, live)
        if s.to_call <= 0:
            if eq > 0.62 and can_raise:
                return self.bet(s, 0.6)
            return Action("check")
        odds = s.to_call / (s.pot + s.to_call)
        if eq > 0.9 and can_raise:
            return self.bet(s, 1.0)
        if eq > odds + 0.12:
            return Action("call")
        return Action("fold")


class TightIsoB(TightIso):
    open_to = 60
    tight = 0.12



def klass(hole, board):
    """0 nothing, 1 draw, 2 weak pair, 3 top pair, 4 overpair, 5 two pair or better (made with hole cards)."""
    a, b = hole[0] >> 2, hole[1] >> 2
    br = [c >> 2 for c in board]
    top = max(br)
    cat = evaluate(list(hole) + list(board)) >> 20
    if cat >= 4:
        return 5
    if a == b:
        if a in br:
            return 5
        return 4 if a > top else 2
    ina, inb = a in br, b in br
    if (ina and inb) or (ina and br.count(a) > 1) or (inb and br.count(b) > 1):
        return 5
    if a == top or b == top:
        return 3
    if ina or inb:
        return 2
    if len(board) < 5:
        suits = [c & 3 for c in list(hole) + list(board)]
        if max(suits.count(x) for x in set(suits)) >= 4:
            return 1
        ranks = sorted(set([a, b] + br))
        for i in range(len(ranks) - 3):
            if ranks[i + 3] - ranks[i] == 3:
                return 1
    return 0


class SizeTell(Base):
    """Shared frame for stand-ins of real bots whose bet size reveals their hand."""
    open_to = 50
    open_pct = (0.25, 0.38, 0.62, 0.74)
    iso_pct = 0.12
    call_pct = 0.26
    three_pct = 0.07
    stack_pct = 0.035
    fold_to_3bet = 0.87

    def seat_group(self, s):
        live = [p for p in s.players]
        k = len(live) - 1 - live.index(s.hero)
        return 3 if k == 0 else 2 if k == 1 else 1 if k == 2 else 0

    def preflop(self, s):
        bb = s.big_blind
        p = percentile(*s.hole)
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        pre = [r for r in s.history if r.street == 0 and r.kind in ("raise", "call")]
        raises = [r for r in pre if r.kind == "raise"]
        level = s.my_bet + s.to_call
        if not raises:
            limpers = sum(1 for r in pre if r.kind == "call")
            pct = self.iso_pct if limpers else self.open_pct[self.seat_group(s)]
            if p < pct and can_raise:
                return Action("raise", min(self.open_to + 10 + 20 * limpers if limpers else self.open_to, s.max_raise_to))
            return Action("check") if s.to_call <= 0 else Action("fold")
        mine = any(r.player == s.hero for r in raises)
        if len(raises) == 1 and not mine:
            if p < self.three_pct and can_raise:
                return Action("raise", min(3 * level, s.max_raise_to))
            if p < self.call_pct and s.to_call <= 5 * bb:
                return Action("call")
            return self.give_up(s)
        if p < self.stack_pct:
            return Action("raise", s.max_raise_to) if can_raise else Action("call")
        if mine and len(raises) == 2 and self.rng.random() > self.fold_to_3bet and s.to_call <= 12 * bb:
            return Action("call")
        return self.give_up(s)

    def decide(self, s):
        if not s.board:
            return self.preflop(s)
        k = klass(s.hole, s.board)
        live = len(s.active)
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        if s.to_call <= 0:
            chips = self.bet_size(s, k, live) if can_raise else 0
            if chips <= 0:
                return Action("check")
            return Action("raise", int(min(max(chips, s.min_raise_to), s.max_raise_to)))
        frac = s.to_call / max(1, s.pot - s.to_call)
        return self.facing(s, k, frac, s.my_bet > 0, can_raise)

    def shove(self, s, can_raise):
        return Action("raise", s.max_raise_to) if can_raise else Action("call")


class RealCPCF(SizeTell):
    """Stand-in for "Chinese people can fly": a third of the pot with weak hands, the pot with top pair or better."""

    def bet_size(self, s, k, live):
        if live > 2:
            return s.pot if k >= 5 else 0
        return s.pot if k >= 3 else max(s.big_blind, s.pot // 3)

    def facing(self, s, k, frac, bet_already, can_raise):
        if bet_already:
            return Action("call") if k >= 3 else self.give_up(s)
        if k >= 5 and can_raise:
            return Action("raise", min(s.my_bet + s.to_call + s.pot, s.max_raise_to))
        if frac > 1.5:
            return Action("call") if k >= 4 else Action("fold")
        if k >= 2 or (k == 1 and s.street < 3):
            return Action("call") if k >= 3 or frac < 0.9 or self.rng.random() < 0.6 else Action("fold")
        return Action("call") if frac < 0.4 and self.rng.random() < 0.7 else Action("fold")


class RealGamesGone(SizeTell):
    """Stand-in for "GamesGone": bets every heads-up street, half pot weak and pot strong, and traps on the river."""
    open_to = 60
    open_pct = (0.23, 0.26, 0.34, 0.42)
    iso_pct = 0.32
    call_pct = 0.20
    three_pct = 0.03
    stack_pct = 0.02
    fold_to_3bet = 0.66

    def bet_size(self, s, k, live):
        if live > 2:
            return s.pot if k >= 3 else 0
        if s.street == 3 and k >= 5:
            return 0
        return s.pot if k >= 3 or k == 1 else s.pot // 2

    def facing(self, s, k, frac, bet_already, can_raise):
        if k >= 5:
            return self.shove(s, can_raise)
        if bet_already:
            if k >= 3:
                return Action("call")
            x = self.rng.random()
            return Action("fold") if x < 0.33 else Action("call")
        if k >= 1:
            return Action("call") if k >= 3 or frac < 1.3 else Action("fold")
        return Action("call") if self.rng.random() < (0.75 if frac < 0.4 else 0.4) else Action("fold")


class RealMohil(RealGamesGone):
    """Stand-in for "Mohil'sPokerBot": re-raises most opens with any two cards and rarely gives up afterwards."""
    open_pct = (0.2, 0.22, 0.28, 0.35)

    def preflop(self, s):
        p = percentile(*s.hole)
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        pre = [r for r in s.history if r.street == 0 and r.kind in ("raise", "call")]
        raises = [r for r in pre if r.kind == "raise"]
        if not raises:
            return super().preflop(s)
        level = s.my_bet + s.to_call
        mine = any(r.player == s.hero for r in raises)
        if len(raises) == 1 and not mine:
            if can_raise and self.rng.random() < 0.78:
                if p < 0.17 and self.rng.random() < 0.35:
                    return Action("raise", s.max_raise_to)
                return Action("raise", min(3 * level, s.max_raise_to))
            return Action("call") if p < 0.15 else self.give_up(s)
        if s.to_call >= 0.5 * s.my_stack:
            return Action("call") if p < 0.2 else self.give_up(s)
        if p < 0.11:
            return Action("raise", s.max_raise_to) if can_raise else Action("call")
        return Action("call") if p < 0.45 else self.give_up(s)


class RealEE(SizeTell):
    """Stand-in for "Equity Engine": 0.8 pot with top pair or better, half pot weak, and a check is never strong."""
    open_to = 70
    open_pct = (0.17, 0.21, 0.29, 0.39)
    iso_pct = 0.30
    call_pct = 0.10
    three_pct = 0.06
    stack_pct = 0.03
    fold_to_3bet = 0.90

    def bet_size(self, s, k, live):
        if k >= 3:
            return int(0.8 * s.pot)
        raiser = any(r.player == s.hero and r.kind == "raise" for r in s.history if r.street == 0)
        if live == 2 and s.street == 1 and raiser and self.rng.random() < 0.6:
            return s.pot // 2
        return 0

    def facing(self, s, k, frac, bet_already, can_raise):
        if bet_already:
            return Action("call") if k >= 3 else self.give_up(s)
        if k >= 5 and can_raise:
            return Action("raise", min(s.my_bet + s.to_call + s.pot, s.max_raise_to))
        if k >= 3:
            return Action("call")
        if k >= 1 and frac < 0.7:
            return Action("call")
        return Action("call") if frac < 0.4 and self.rng.random() < 0.5 else Action("fold")


REAL = {"kit_starter0": KitStarter, "kit_variant": KitVariant, "tight_a": TightIso, "tight_b": TightIsoB,
        "real_cpcf": RealCPCF, "real_gg": RealGamesGone, "real_ee": RealEE, "real_mohil": RealMohil}
