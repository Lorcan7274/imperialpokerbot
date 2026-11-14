import gc
import random
import time

from .bot import Bot
from .cards import parse_card
from .ranges import Sample, simulate
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


def workload():
    rng = random.Random(1)
    hero = [50, 45]
    board = [3, 17, 30]
    best = 1.0
    for _ in range(4):
        t = time.perf_counter()
        sample = Sample(hero, rng, 100)
        vals = sample.board(board)[0]
        w = [0.0 if v < 0 else x for v, x in zip(vals, sample.base)]
        simulate(hero, board, sample, [w, w], 40, rng)
        best = min(best, time.perf_counter() - t)
    return best


class Agent:
    BANK = 8.0
    OVERHEAD = 0.0008
    LIMIT = 0.004
    REFERENCE = 0.00018
    TARGET = 0.0012
    CALIBRATE = True

    def __init__(self):
        self.bot = Bot()
        self.base_trials = self.bot.trials
        self.spent = 0.0
        self.hands = 1000
        self.speed = 1.0
        self.heavy = self.TARGET

    def on_table_start(self, info):
        self.hands = info.get("hands", 1000)
        if not self.CALIBRATE:
            return
        try:
            self.speed = min(1.0, max(0.15, self.REFERENCE / workload()))
            gc.collect()
            gc.freeze()
            gc.disable()
        except Exception:
            pass

    def act(self, state):
        t = time.perf_counter()
        legal = state.get("legal_actions", ())
        bot = self.bot
        try:
            left = max(1, self.hands - state.get("hand_number", 1) + 1)
            per_hand = (self.BANK - self.spent) / left
            bot.trials = (self.base_trials if per_hand > 0.004 else
                          45 if per_hand > 0.002 else 24 if per_hand > 0.0008 else 0)
            if bot.trials == 0:
                out = {"action": "check" if "check" in legal else "fold"}
            else:
                bot.scale = self.speed
                bot.deadline = t + self.LIMIT if self.CALIBRATE else None
                a = bot.decide(convert_state(state))
                out = {"action": a.kind}
                if a.kind == "raise":
                    out["amount"] = int(a.amount)
        except Exception:
            out = {"action": "check" if "check" in legal else "fold"}
        dt = time.perf_counter() - t
        self.spent += dt + self.OVERHEAD
        if self.CALIBRATE and dt > 0.0004:
            self.heavy += 0.15 * (min(dt, 3 * self.heavy) - self.heavy)
            if self.heavy > 1.5 * self.TARGET:
                self.speed = max(0.15, self.speed * 0.9)
            elif self.heavy < 0.7 * self.TARGET:
                self.speed = min(1.0, self.speed * 1.04)
        return out

    def on_hand_end(self, summary):
        t = time.perf_counter()
        try:
            shown = {int(k): [parse_card(c) for c in v]
                     for k, v in (summary.get("shown") or {}).items()}
            self.bot.end_hand(convert_history(summary["history"]), shown)
        except Exception:
            pass
        if self.CALIBRATE and summary.get("hand_number", 1) % 128 == 0:
            gc.collect()
        self.spent += time.perf_counter() - t
