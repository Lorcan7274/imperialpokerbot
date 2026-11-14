import random
import sys

sys.path.insert(0, ".")
from pokerbot.cards import evaluate
from pokerbot.preflop import COMBO_PCT, COMBOS
from tools.gen_preflop import classes

GRID = (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0)


def main():
    rng = random.Random(23)
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 2500
    order = sorted(range(len(COMBOS)), key=COMBO_PCT.__getitem__)
    rows = {}
    for name, hand in classes():
        hs = set(hand)
        row = []
        for x in GRID:
            top = [COMBOS[i] for i in order[:max(6, int(round(x * len(order))))]
                   if COMBOS[i][0] not in hs and COMBOS[i][1] not in hs]
            won = 0.0
            for _ in range(trials):
                v = top[int(rng.random() * len(top))]
                deck = [c for c in range(52) if c not in hs and c != v[0] and c != v[1]]
                board = rng.sample(deck, 5)
                a = evaluate(list(hand) + board)
                b = evaluate(list(v) + board)
                won += 1.0 if a > b else 0.5 if a == b else 0.0
            row.append(won / trials)
        rows[name] = row
    with open("pokerbot/topx_table.py", "w") as f:
        f.write("TOPX_GRID = %r\n" % (GRID,))
        f.write("TOPX = {\n")
        for name, row in rows.items():
            f.write('    "%s": (%s),\n' % (name, ", ".join("%.3f" % v for v in row)))
        f.write("}\n")


if __name__ == "__main__":
    main()
