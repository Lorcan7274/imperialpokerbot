import unittest

from arena import fuzz


class EngineFuzzTest(unittest.TestCase):
    def test_no_swallowed_errors_or_illegal_answers(self):
        mod = fuzz.load("bot.py", "bot_under_fuzz")
        probe = fuzz.Probe(mod)
        seed = 300
        for name in ("house", "wild", "limp", "self"):
            for betting, cap in (("no_limit", 0), ("pot_limit", 2), ("fixed_limit", 0)):
                for players in (5, 8):
                    seed += 1
                    fuzz.run(mod, probe, fuzz.FIELDS[name], players, betting, cap, 30, seed)
        self.assertGreater(probe.decisions, 1000)
        self.assertEqual(dict(probe.errors), {})
        self.assertEqual(dict(probe.flags), {})


if __name__ == "__main__":
    unittest.main()
