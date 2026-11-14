from arena.opponents import Base, raw_equity
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


REAL = {"kit_starter0": KitStarter, "tight_a": TightIso, "tight_b": TightIsoB}
