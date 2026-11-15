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

    def test_full_tables_of_nine_and_ten(self):
        mod = fuzz.load("bot.py", "bot_under_fuzz_full")
        probe = fuzz.Probe(mod)
        seed = 700
        for name in ("house", "wild", "limp", "self"):
            for players in (9, 10):
                seed += 1
                fuzz.run(mod, probe, fuzz.FIELDS[name], players, "no_limit", 0, 40, seed)
        self.assertGreater(probe.decisions, 300)
        self.assertGreater(max(k[1] for k in probe.cpu), 7)
        self.assertEqual(dict(probe.errors), {})
        self.assertEqual(dict(probe.flags), {})


if __name__ == "__main__":
    unittest.main()
