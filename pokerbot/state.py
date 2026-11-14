from collections import namedtuple

Rec = namedtuple("Rec", "player street kind amount to")
Action = namedtuple("Action", "kind amount")
Action.__new__.__defaults__ = (0,)


class GameState:
    __slots__ = ("hand_id", "hero", "hole", "board", "pot", "to_call", "my_bet", "my_stack",
                 "min_raise_to", "max_raise_to", "big_blind", "players", "active", "history",
                 "stacks")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def street(self):
        return {0: 0, 3: 1, 4: 2, 5: 3}[len(self.board)]
