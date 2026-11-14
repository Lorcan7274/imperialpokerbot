import random
import sys

sys.path.insert(0, ".")
from pokerbot.cards import RANKS, evaluate


def classes():
    for hi in range(12, -1, -1):
        for lo in range(hi, -1, -1):
            if hi == lo:
                yield RANKS[hi] + RANKS[lo], (hi * 4, lo * 4 + 1)
            else:
                yield RANKS[hi] + RANKS[lo] + "s", (hi * 4, lo * 4)
                yield RANKS[hi] + RANKS[lo] + "o", (hi * 4, lo * 4 + 1)


def equity(hand, trials, rng):
    deck = [c for c in range(52) if c not in hand]
    won = 0.0
    for _ in range(trials):
        d = rng.sample(deck, 7)
        a = evaluate([hand[0], hand[1]] + d[2:])
        b = evaluate(d)
        won += 1.0 if a > b else 0.5 if a == b else 0.0
    return won / trials


def main():
    rng = random.Random(7)
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
    rows = [(name, equity(hand, trials, rng)) for name, hand in classes()]
    with open("pokerbot/preflop_table.py", "w") as f:
        f.write("EQ = {\n")
        for name, eq in rows:
            f.write(f'    "{name}": {eq:.4f},\n')
        f.write("}\n")


if __name__ == "__main__":
    main()
