import itertools
import random
import time
import unittest

from pokerbot.cards import category, evaluate, parse_cards


def brute(cards):
    return max(evaluate(list(c)) for c in itertools.combinations(cards, 5))


class CardsTest(unittest.TestCase):
    def test_categories(self):
        cases = [
            ("As Ks Qs Js Ts 2d 3c", 8), ("5s 4s 3s 2s As Kd Kc", 8),
            ("9s 9d 9h 9c 2s 2d 3c", 7), ("9s 9d 9h 2c 2s 2d 3c", 6),
            ("As 9s 7s 4s 2s 2d 3c", 5), ("5s 4d 3s 2s Ac Kd Kc", 4),
            ("9s 9d 9h Ac 2s 4d 3c", 3), ("9s 9d 8h 8c 2s 2d Ac", 2),
            ("9s 9d 8h 7c 2s 3d Ac", 1), ("9s Jd 8h 7c 2s 3d Ac", 0),
        ]
        for text, cat in cases:
            self.assertEqual(category(evaluate(parse_cards(text))), cat, text)

    def test_ordering(self):
        better = evaluate(parse_cards("As Ad Kh Kc Qs 2d 3c"))
        worse = evaluate(parse_cards("As Ad Kh Kc Js 2d 3c"))
        self.assertGreater(better, worse)
        wheel = evaluate(parse_cards("5s 4d 3s 2s Ac 9d Kc"))
        six = evaluate(parse_cards("6s 5d 4s 3s 2c 9d Kc"))
        self.assertGreater(six, wheel)

    def test_seven_matches_best_five(self):
        rng = random.Random(1)
        deck = list(range(52))
        for _ in range(3000):
            cards = rng.sample(deck, rng.choice((5, 6, 7)))
            self.assertEqual(evaluate(cards), brute(cards))

    def test_speed(self):
        rng = random.Random(2)
        hands = [rng.sample(range(52), 7) for _ in range(20000)]
        for h in hands:
            evaluate(h)
        t = time.perf_counter()
        for h in hands:
            evaluate(h)
        self.assertLess((time.perf_counter() - t) / len(hands), 2e-5)


if __name__ == "__main__":
    unittest.main()
