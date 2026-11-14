import random

RANKS = "23456789TJQKA"


class Base:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def start_table(self, seat, info):
        self.seat = seat

    def hand_end(self, summary):
        pass

    def passive(self, state):
        return {"action": "check" if "check" in state["legal_actions"] else "call"}

    def give_up(self, state):
        return {"action": "check" if "check" in state["legal_actions"] else "fold"}

    def to(self, state, over=0, pot=0.0):
        if "raise" not in state["legal_actions"]:
            return self.passive(state)
        lo, hi = state["min_raise_to"], state["max_raise_to"]
        return {"action": "raise", "amount": max(lo, min(int(lo + over + pot * state["pot"]), hi))}


def strength(hole):
    a, b = sorted((RANKS.index(c[0]) for c in hole), reverse=True)
    if a == b:
        return 0.5 + a / 24
    return (a + b) / 24 + (0.06 if hole[0][1] == hole[1][1] else 0) - (0.04 if a - b > 4 else 0)


def paired(hole, board):
    ranks = [c[0] for c in hole + board]
    return any(ranks.count(r) >= 2 for r in {c[0] for c in hole})


class Station(Base):
    def act(self, state):
        return self.passive(state)


class Folder(Base):
    def act(self, state):
        return self.give_up(state)


class RandomLegal(Base):
    def act(self, state):
        action = self.rng.choice(state["legal_actions"])
        if action == "raise":
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            return {"action": "raise", "amount": self.rng.randint(lo, min(hi, lo * 3))}
        return {"action": action}


class Tag(Base):
    def act(self, state):
        legal = state["legal_actions"]
        bb = state["big_blind"]
        if state["street"] == "preflop":
            s = strength(state["hole_cards"])
            if s >= 0.8 and "raise" in legal:
                return self.to(state, 2 * bb)
            if s >= 0.62 and state["to_call"] <= 3 * bb:
                return self.passive(state)
        elif paired(state["hole_cards"], state["board"]):
            if "raise" in legal and state["to_call"] == 0:
                return self.to(state, pot=0.5)
            return self.passive(state)
        return self.give_up(state)


class Starter(Base):
    def act(self, state):
        ranks = sorted(RANKS.index(c[0]) for c in state["hole_cards"])
        strong = ranks[0] == ranks[1] or ranks[1] >= 11
        if strong and "raise" in state["legal_actions"]:
            return self.to(state, pot=0.5)
        if "check" in state["legal_actions"]:
            return {"action": "check"}
        if state["to_call"] <= state["big_blind"] * 2 or strong:
            return {"action": "call"}
        return {"action": "fold"}


class MinRaiser(Base):
    def act(self, state):
        if "raise" in state["legal_actions"]:
            return {"action": "raise", "amount": state["min_raise_to"]}
        return self.passive(state)


class Shover(Base):
    p = 0.25

    def act(self, state):
        if self.rng.random() < self.p:
            return {"action": "all_in"}
        return self.give_up(state) if self.rng.random() < 0.6 else self.passive(state)


class Maniac(Base):
    def act(self, state):
        if "raise" in state["legal_actions"] and self.rng.random() < 0.6:
            return self.to(state, pot=self.rng.choice((0, 0.5, 1, 3, 1000)))
        return self.passive(state)


class Limper(Base):
    def act(self, state):
        if state["street"] == "preflop":
            if state["to_call"] <= 6 * state["big_blind"]:
                return self.passive(state)
            return self.give_up(state)
        x = self.rng.random()
        if x < 0.25:
            return self.to(state, pot=0.5)
        if x < 0.85 or state["to_call"] <= state["pot"] // 3:
            return self.passive(state)
        return self.give_up(state)


class CheckRaiser(Base):
    def act(self, state):
        if state["to_call"] > 0 and "raise" in state["legal_actions"] and self.rng.random() < 0.5:
            return self.to(state, pot=1.0)
        if state["to_call"] > state["pot"]:
            return self.give_up(state) if self.rng.random() < 0.5 else self.passive(state)
        return self.passive(state)


class Weird(Base):
    """Legal histories from illegal answers: the engine normalises each of these."""

    def act(self, state):
        x = self.rng.random()
        if x < 0.1:
            return None
        if x < 0.2:
            return {"action": "raise"}
        if x < 0.3:
            return {"action": "raise", "amount": 10 ** 9}
        if x < 0.4:
            return {"action": "raise", "amount": -5}
        if x < 0.5:
            return {"action": "ALL_IN"}
        if x < 0.6:
            return {"action": "bet", "amount": "77"}
        if x < 0.7:
            return {"action": "check"}
        if x < 0.8:
            return {"action": "call"}
        if x < 0.9:
            return {"action": "raise", "amount": 3.7 * state["big_blind"]}
        return {"action": "fold"}


class Nit(Base):
    def act(self, state):
        s = strength(state["hole_cards"])
        if state["street"] == "preflop":
            if s >= 0.9:
                return self.to(state, pot=1.0)
            if s >= 0.75 and state["to_call"] <= 4 * state["big_blind"]:
                return self.passive(state)
            return self.give_up(state)
        if paired(state["hole_cards"], state["board"]) and s >= 0.6:
            return self.to(state, pot=0.5)
        return self.give_up(state)


ZOO = {"station": Station, "folder": Folder, "random": RandomLegal, "tag": Tag, "starter": Starter,
       "minraiser": MinRaiser, "shover": Shover, "maniac": Maniac, "limper": Limper,
       "checkraiser": CheckRaiser, "weird": Weird, "nit": Nit}
