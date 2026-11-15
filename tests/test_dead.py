import unittest

from arena.abtest import registry
from arena.engine import Table
from arena.opponents import ALL, dying
from pokerbot import Bot
from pokerbot.model import Model, classify
from pokerbot.state import Action, GameState, Rec

FOLD = [Rec("v", 0, "sb", 10, 10), Rec("h", 0, "bb", 20, 20), Rec("x", 0, "raise", 40, 40),
        Rec("v", 0, "fold", 0, 10), Rec("h", 0, "fold", 0, 20)]
CHECK = [Rec("h", 0, "sb", 10, 10), Rec("v", 0, "bb", 20, 20), Rec("x", 0, "call", 20, 20),
         Rec("h", 0, "fold", 0, 10), Rec("v", 0, "check", 0, 20), Rec("v", 1, "check", 0, 0),
         Rec("x", 1, "raise", 20, 20), Rec("v", 1, "fold", 0, 0)]
WALK = [Rec("h", 0, "sb", 10, 10), Rec("v", 0, "bb", 20, 20), Rec("x", 0, "fold", 0, 0), Rec("h", 0, "fold", 0, 10)]
CALL = [Rec("v", 0, "sb", 10, 10), Rec("h", 0, "bb", 20, 20), Rec("x", 0, "fold", 0, 0),
        Rec("v", 0, "call", 10, 20), Rec("h", 0, "check", 0, 20), Rec("v", 1, "check", 0, 0),
        Rec("h", 1, "check", 0, 0)]
RAISE = [Rec("v", 0, "sb", 10, 10), Rec("h", 0, "bb", 20, 20), Rec("x", 0, "fold", 0, 0),
         Rec("v", 0, "raise", 50, 60), Rec("h", 0, "fold", 0, 20)]


def see(model, hist, times=1):
    for _ in range(times):
        model.observe(classify(hist, 20, n=3), "h")


class Watch(Bot):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.log = []
        self.cut = []

    def decide(self, s):
        before = list(s.active)
        a = super().decide(s)
        can = s.max_raise_to > s.my_bet + s.to_call
        ok = ((a.kind == "check" and s.to_call <= 0) or (a.kind in ("call", "fold") and s.to_call > 0)
              or (a.kind == "raise" and can and s.min_raise_to <= a.amount <= s.max_raise_to))
        assert ok, (a, s.to_call, s.min_raise_to, s.max_raise_to)
        self.log.append((s.hand_id, s.street, s.players.index(s.hero), a, s.min_raise_to))
        gone = [p for p in before if p != s.hero and self.model.gone(p)]
        self.cut.append((s.street, len(before) - len(s.active), len(gone), len(before) - 1))
        return a


class DeadTest(unittest.TestCase):
    def test_detection_after_the_threshold(self):
        m = Model()
        see(m, FOLD, m.GONE // 2)
        see(m, WALK, 50)
        see(m, CHECK, m.GONE - m.GONE // 2 - 1)
        self.assertFalse(m.gone("v"))
        see(m, FOLD)
        self.assertTrue(m.gone("v"))
        self.assertFalse(m.gone("x"))
        self.assertFalse(m.gone("h"))

    def test_a_call_or_a_raise_makes_it_live(self):
        for hist in (CALL, RAISE):
            m = Model()
            see(m, FOLD, m.GONE + 5)
            self.assertTrue(m.gone("v"))
            see(m, hist)
            self.assertFalse(m.gone("v"))
            self.assertEqual(m.quiet["v"], 0)
            see(m, FOLD, m.GONE - 1)
            self.assertFalse(m.gone("v"))

    def state(self, history, **kw):
        base = dict(hand_id=99, hero="h", hole=[20, 3], board=[], pot=30, to_call=20, my_bet=0, my_stack=2000,
                    min_raise_to=40, max_raise_to=2000, big_blind=20, players=["v", "w", "x", "h"],
                    active=["v", "w", "h"], history=history,
                    stacks={"v": 1990, "w": 1980, "x": 2000, "h": 2000})
        base.update(kw)
        return GameState(**base)

    def test_live_again_within_the_hand(self):
        blinds = [Rec("v", 0, "sb", 10, 10), Rec("w", 0, "bb", 20, 20), Rec("x", 0, "fold", 0, 0)]
        bot = Bot(seed=1, strict=True)
        bot.model.quiet.update(v=bot.model.GONE, w=bot.model.GONE)
        s = self.state(blinds)
        self.assertEqual(bot.decide(s), Action("raise", 40))
        self.assertEqual(s.active, ["v", "w", "h"])
        # the small blind wakes up with a re-raise: seven-deuce is folded, and only the big blind is left out
        woke = blinds + [Rec("h", 0, "raise", 40, 40), Rec("v", 0, "raise", 110, 120), Rec("w", 0, "fold", 0, 20)]
        s = self.state(woke, active=["v", "h"], pot=180, to_call=80, my_bet=40, my_stack=1960, min_raise_to=200)
        self.assertEqual(bot._gone(s), set())
        self.assertEqual(bot.decide(s), Action("fold"))
        # with a live player still in, a flagged one changes nothing
        s = self.state(woke[:-1], active=["v", "w", "h"])
        self.assertEqual(bot._gone(s), {"w"})
        plain = Bot(seed=1, strict=True)
        self.assertEqual(bot.decide(s), plain.decide(self.state(woke[:-1], active=["v", "w", "h"])))
        self.assertEqual(s.active, ["v", "w", "h"])

    def test_smallest_bet_after_the_flop_and_only_when_nobody_has_bet(self):
        pre = [Rec("h", 0, "sb", 10, 10), Rec("w", 0, "bb", 20, 20), Rec("x", 0, "fold", 0, 0),
               Rec("v", 0, "fold", 0, 0), Rec("h", 0, "call", 10, 20), Rec("w", 0, "check", 0, 20)]
        bot = Bot(seed=1, strict=True)
        bot.model.quiet["w"] = bot.model.GONE
        kw = dict(players=["h", "w", "x", "v"], active=["h", "w"], board=[0, 21, 34], pot=40, my_stack=1980,
                  min_raise_to=20, max_raise_to=1980)
        self.assertEqual(bot.decide(self.state(pre, to_call=0, **kw)), Action("raise", 20))
        # no raise is legal: the usual logic answers, with the player still in the hand
        s = self.state(pre, to_call=0, **dict(kw, min_raise_to=0, max_raise_to=0))
        self.assertEqual(bot.decide(s).kind, "check")
        self.assertEqual(s.active, ["h", "w"])

    def test_takes_the_blinds_from_every_seat(self):
        for n in (2, 3, 8):
            hero = Watch(seed=1, strict=True)
            bots = {"hero": hero}
            bots.update({"f%d" % i: ALL["folder"](seed=i) for i in range(n - 1)})
            table = Table(bots, seed=5)
            warm = n * (hero.model.GONE + 8)
            table.play(warm)
            self.assertTrue(all(hero.model.gone(p) for p in bots if p != "hero"))
            del hero.log[:]
            totals, _ = table.play(4 * n)
            self.assertEqual({a for _, _, _, a, _ in hero.log}, {Action("raise", 40)})
            # heads-up the button is the small blind; otherwise every seat but the big blind has a decision
            self.assertEqual({seat for _, _, seat, _, _ in hero.log}, set(range(n)) - {0 if n == 2 else 1})
            self.assertEqual(totals["hero"], 4 * (n - 1) * 30)

    def test_legal_on_every_street_with_live_and_gone_players(self):
        reg = registry()
        hero = Watch(seed=2, strict=True, trials=60)
        bots = {"hero": hero, "d1": reg["random@1"](seed=1), "c1": reg["caller"](seed=2),
                "d2": reg["station@1"](seed=3), "r1": reg["random"](seed=4), "d3": reg["maniac@150"](seed=5),
                "s1": reg["station"](seed=6)}
        totals, _ = Table(bots, seed=6).play(700)
        self.assertEqual(sum(totals.values()), 0)
        m = hero.model
        self.assertTrue(m.gone("d1") and m.gone("d2") and m.gone("d3"))
        self.assertFalse(m.gone("c1") or m.gone("r1") or m.gone("s1"))
        for street in range(4):
            self.assertTrue(any(st == street and gone for st, _, gone, _ in hero.cut), street)
        # nobody is ever taken out of the hand
        self.assertFalse(any(cut for _, cut, _, _ in hero.cut))

    def test_no_change_where_nobody_is_flagged(self):
        logs = []
        for limit in (Model.GONE, 10 ** 9):
            hero = Watch(seed=3, strict=True, trials=60)
            hero.model.GONE = limit
            bots = {"hero": hero}
            bots.update({k: ALL[k](seed=7) for k in ("random", "maniac", "station", "caller", "starter")})
            Table(bots, seed=8).play(400)
            self.assertFalse(any(gone for _, _, gone, _ in hero.cut))
            logs.append(hero.log)
        self.assertEqual(logs[0], logs[1])
        self.assertGreater(len(logs[0]), 400)

    def test_dying_opponent(self):
        bot = dying(ALL["allin"](seed=1), 5)
        s = self.state([], hand_id=4)
        self.assertEqual(bot.decide(s).kind, "raise")
        self.assertEqual(bot.decide(self.state([], hand_id=5)), Action("fold"))
        self.assertEqual(bot.decide(self.state([], hand_id=6, to_call=0)), Action("check"))


if __name__ == "__main__":
    unittest.main()
