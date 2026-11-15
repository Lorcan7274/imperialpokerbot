import time
import unittest

from arena.engine import Table
from arena.opponents import ALL
from pokerbot import Bot
from pokerbot.agent import Agent
from pokerbot.model import Model, classify
from pokerbot.state import Rec


class Timed(Bot):
    worst = 0.0

    def decide(self, s):
        t = time.perf_counter()
        a = super().decide(s)
        self.worst = max(self.worst, time.perf_counter() - t)
        return a


class PlayTest(unittest.TestCase):
    def test_zero_sum_and_legal(self):
        for names in (["random"], ["maniac"], ["allin"], ["random", "maniac", "station", "allin", "nit"]):
            bots = {"hero": Timed(seed=1, strict=True, trials=120)}
            bots.update({k: ALL[k](seed=2) for k in names})
            totals, _ = Table(bots, seed=3).play(300)
            self.assertEqual(sum(totals.values()), 0)
            self.assertLess(bots["hero"].worst, 0.25)

    def test_beats_folder_and_caller(self):
        for name, floor in (("folder", 70), ("caller", 300)):
            totals, _ = Table({"hero": Bot(seed=1, strict=True, trials=120), name: ALL[name](seed=2)}, seed=4).play(600)
            self.assertGreater(100 * totals["hero"] / 600 / 20, floor)

    def test_model_learns_folding(self):
        m = Model()
        hist = [Rec("v", 0, "sb", 10, 10), Rec("h", 0, "bb", 20, 20), Rec("v", 0, "fold", 0, 10)]
        base = m.freq("v", "unopened", "raise")
        for _ in range(30):
            m.observe(classify(hist, 20), "h")
        self.assertLess(m.freq("v", "unopened", "raise"), base / 3)

    def test_long_table_bank(self):
        state = {"hole_cards": ["7c", "2d"], "board": [], "seat": 2, "button": 0, "stacks": [2000, 1990, 1980],
                 "bets": [0, 10, 20], "folded": [False] * 3, "pot": 30, "to_call": 20, "min_raise_to": 40,
                 "max_raise_to": 2000, "big_blind": 20, "hand_number": 4000, "legal_actions": ["fold", "call", "raise"],
                 "history": [{"seat": 1, "street": "preflop", "action": "small_blind", "amount": 10},
                             {"seat": 2, "street": "preflop", "action": "big_blind", "amount": 20}]}
        for final, hands, spent, hand, trials in (
                ("flat", 5000, 0.0, 4000, 16), ("flat", 5000, 99.0, 4000, 16), ("flat", 1000, 0.0, 1000, 90),
                ("flat", 1000, 0.0, 1001, 16), ("scaled", 1000, 0.0, 1001, 90), ("scaled", 5000, 0.0, 4000, 90),
                ("scaled", 5000, 39.0, 4000, 24)):
            a = Agent()
            a.CALIBRATE = False
            a.FINAL = final
            a.on_table_start({"hands": hands, "num_players": 3})
            a.spent = spent
            state["hand_number"] = hand
            self.assertIn(a.act(state)["action"], ("fold", "call", "raise"))
            self.assertEqual(a.bot.trials, trials)
            self.assertIsNone(a.bot.deadline)
        # half-way through a round, a spend heading for 4.0, 6.4 and 8.0 s of the bot's 8 s
        for spent, scale in ((2.0, 1.0), (3.2, 0.5), (4.0, 0.2)):
            a = Agent()
            a.CALIBRATE = False
            a.on_table_start({"hands": 1000, "num_players": 3})
            a.spent = spent
            state["hand_number"] = 501
            a.act(state)
            self.assertEqual(a.bot.trials, 90)
            self.assertAlmostEqual(a.bot.scale, scale)


if __name__ == "__main__":
    unittest.main()
