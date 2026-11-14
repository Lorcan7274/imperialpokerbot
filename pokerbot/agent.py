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
    OVERHEAD = 0.0018
    LIMIT = 0.004
    REFERENCE = 0.0003
    TARGET = 0.002
    CALIBRATE = True
    REPORT = False

    def __init__(self):
        self.bot = Bot()
        self.base_trials = self.bot.trials
        self.spent = 0.0
        self.hands = 1000
        self.speed = 1.0
        self.heavy = self.TARGET
        self.seen = {"cal": 0.0, "clock": 0.0, "end": 0.0, "endmax": 0.0, "late": 0, "told": False,
                     False: [0, 0.0, 0.0], True: [0, 0.0, 0.0], "hist": [0] * 8}

    def on_table_start(self, info):
        self.hands = info.get("hands", 1000)
        if not self.CALIBRATE:
            return
        try:
            self.seen["cal"] = cal = workload()
            t = time.perf_counter()
            for _ in range(200):
                time.perf_counter()
            self.seen["clock"] = (time.perf_counter() - t) / 200
            self.speed = min(1.0, max(0.15, self.REFERENCE / cal))
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
        post = bool(state.get("board"))
        if self.CALIBRATE and post:
            self.heavy += 0.15 * (min(dt, 3 * self.heavy) - self.heavy)
            if self.heavy > 1.5 * self.TARGET:
                self.speed = max(0.15, self.speed * 0.9)
            elif self.heavy < 0.7 * self.TARGET:
                self.speed = min(1.0, self.speed * 1.04)
        seen = self.seen
        row = seen[post]
        row[0] += 1
        row[1] += dt
        row[2] = max(row[2], dt)
        seen["late"] += dt > self.LIMIT
        if post:
            seen["hist"][min(7, int(dt * 1000))] += 1
        if (self.REPORT and not seen["told"] and out["action"] in ("check", "fold")
                and state.get("hand_number", 0) > self.hands - 20):
            seen["told"] = True
            raise RuntimeError(self.report())
        return out

    def report(self):
        seen = self.seen
        pre, post = seen[False], seen[True]
        return ("TIMING cal_ms=%.3f clock_us=%.2f speed=%.2f heavy_ms=%.2f pre n=%d sum_s=%.3f max_ms=%.2f "
                "post n=%d sum_s=%.3f max_ms=%.2f post_ms_hist=%s over_limit=%d hand_end sum_s=%.3f max_ms=%.2f "
                "spent=%.2f gc=%s" % (
                    seen["cal"] * 1e3, seen["clock"] * 1e6, self.speed, self.heavy * 1e3, pre[0], pre[1],
                    pre[2] * 1e3, post[0], post[1], post[2] * 1e3, seen["hist"], seen["late"], seen["end"],
                    seen["endmax"] * 1e3, self.spent, gc.isenabled()))

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
        dt = time.perf_counter() - t
        self.spent += dt
        self.seen["end"] += dt
        self.seen["endmax"] = max(self.seen["endmax"], dt)
