import time

from .bot import Bot
from .cards import parse_card
from .state import GameState, Rec

STREETS = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
KINDS = {"small_blind": "sb", "big_blind": "bb"}


def convert_history(history):
    out = []
    street = None
    bets = {}
    for h in history:
        st = STREETS[h["street"]]
        if st != street:
            street = st
            bets = {}
        seat = h["seat"]
        kind = KINDS.get(h["action"], h["action"])
        amount = h.get("amount") or 0
        prev = bets.get(seat, 0)
        if kind in ("sb", "bb", "raise"):
            to = amount
        elif kind == "call":
            to = prev + amount
        else:
            to = prev
        bets[seat] = to
        out.append(Rec(seat, st, kind, to - prev, to))
    return out


def convert_state(state):
    n = len(state["stacks"])
    seat = state["seat"]
    button = state["button"]
    players = [(button + 1 + i) % n for i in range(n)]
    folded = state["folded"]
    return GameState(
        hand_id=state["hand_number"], hero=seat,
        hole=[parse_card(c) for c in state["hole_cards"]],
        board=[parse_card(c) for c in state["board"]],
        pot=state["pot"], to_call=state["to_call"], my_bet=state["bets"][seat],
        my_stack=state["stacks"][seat], min_raise_to=state.get("min_raise_to") or 0,
        max_raise_to=state.get("max_raise_to") or 0, big_blind=state["big_blind"],
        players=players, active=[p for p in players if not folded[p]],
        history=convert_history(state["history"]),
        stacks=dict(enumerate(state["stacks"])))


class Agent:
    BANK = 8.5
    OVERHEAD = 0.0004

    def __init__(self):
        self.bot = Bot()
        self.base_trials = self.bot.trials
        self.spent = 0.0
        self.hands = 1000

    def on_table_start(self, info):
        self.hands = info.get("hands", 1000)

    def act(self, state):
        t = time.perf_counter()
        legal = state.get("legal_actions", ())
        try:
            left = max(1, self.hands - state.get("hand_number", 1) + 1)
            per_hand = (self.BANK - self.spent) / left
            self.bot.trials = (self.base_trials if per_hand > 0.004 else
                               60 if per_hand > 0.002 else 24 if per_hand > 0.0008 else 0)
            if self.bot.trials == 0:
                out = {"action": "check" if "check" in legal else "fold"}
            else:
                a = self.bot.decide(convert_state(state))
                out = {"action": a.kind}
                if a.kind == "raise":
                    out["amount"] = int(a.amount)
        except Exception:
            out = {"action": "check" if "check" in legal else "fold"}
        self.spent += time.perf_counter() - t + self.OVERHEAD
        return out

    def on_hand_end(self, summary):
        t = time.perf_counter()
        try:
            self.bot.end_hand(convert_history(summary["history"]))
        except Exception:
            pass
        self.spent += time.perf_counter() - t
