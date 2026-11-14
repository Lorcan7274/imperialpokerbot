import time
import unittest

from arena.engine import Table
from arena.opponents import ALL
from pokerbot import Bot
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
            self.assertLess(bots["hero"].worst, 0.01)

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


if __name__ == "__main__":
    unittest.main()
