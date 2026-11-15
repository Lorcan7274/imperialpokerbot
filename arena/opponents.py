import random

from pokerbot.cards import evaluate
from pokerbot.preflop import percentile
from pokerbot.state import Action


def raw_equity(hole, board, rng, trials=120):
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    won = 0.0
    for _ in range(trials):
        d = rng.sample(deck, need + 2)
        full = board + d[2:]
        a, b = evaluate(hole + full), evaluate(d[:2] + full)
        won += 1.0 if a > b else 0.5 if a == b else 0.0
    return won / trials


class Base:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def bet(self, s, frac):
        if s.max_raise_to <= s.my_bet + s.to_call:
            return Action("call") if s.to_call else Action("check")
        to = s.my_bet + s.to_call + int(frac * (s.pot + s.to_call))
        return Action("raise", max(s.min_raise_to, min(to, s.max_raise_to)))

    def passive(self, s):
        return Action("call") if s.to_call else Action("check")

    def give_up(self, s):
        return Action("fold") if s.to_call else Action("check")


class Folder(Base):
    def decide(self, s):
        return self.give_up(s)


class Caller(Base):
    def decide(self, s):
        return self.passive(s)


class Random(Base):
    def decide(self, s):
        x = self.rng.random()
        if x < 0.2:
            return self.give_up(s)
        if x < 0.7:
            return self.passive(s)
        return self.bet(s, self.rng.choice((0.5, 1.0)))


class Maniac(Base):
    def decide(self, s):
        if self.rng.random() < 0.7:
            return self.bet(s, self.rng.choice((0.75, 1.0, 1.5)))
        return self.passive(s)


class AllIn(Base):
    def decide(self, s):
        if s.max_raise_to > s.my_bet + s.to_call:
            return Action("raise", s.max_raise_to)
        return self.passive(s)


class Nit(Base):
    def decide(self, s):
        if not s.board:
            p = percentile(*s.hole)
            if p < 0.05:
                return self.bet(s, 1.0)
            if p < 0.14 and s.to_call <= 4 * s.big_blind:
                return self.passive(s)
            return self.give_up(s)
        eq = raw_equity(s.hole, s.board, self.rng)
        if eq > 0.8:
            return self.bet(s, 0.75)
        if eq > 0.65 and s.to_call <= 0.5 * s.pot:
            return self.passive(s)
        return self.give_up(s)


class Starter(Base):
    def decide(self, s):
        eq = raw_equity(s.hole, s.board, self.rng)
        odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if eq > 0.72:
            return self.bet(s, 0.75)
        if eq > 0.58 and not s.to_call:
            return self.bet(s, 0.5)
        if eq > odds + 0.05:
            return self.passive(s)
        return self.give_up(s)


class Station(Base):
    def decide(self, s):
        eq = raw_equity(s.hole, s.board, self.rng)
        if eq > 0.85:
            return self.bet(s, 0.6)
        if eq > 0.3 or s.to_call <= 0.25 * s.pot:
            return self.passive(s)
        return self.give_up(s)


def dying(bot, at):
    # from hand `at` on the bot is played by the server: check when that is allowed, otherwise fold
    alive = bot.decide
    bot.decide = lambda s: alive(s) if s.hand_id < at else Action("fold" if s.to_call > 0 else "check")
    return bot


ALL = {"folder": Folder, "caller": Caller, "random": Random, "maniac": Maniac,
       "allin": AllIn, "nit": Nit, "starter": Starter, "station": Station}
