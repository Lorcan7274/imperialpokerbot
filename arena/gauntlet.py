import argparse
import math
import random
import sys
import time

sys.path.insert(0, ".")
from arena.engine import Table
from arena.rivals import KIT, RIVALS, STRONG
from pokerbot import Bot

BB = 20
KIT7 = ["kit_starter", "kit_starter", "kit_station", "kit_station", "kit_tag", "kit_tag", "kit_random"]
PRESETS = {
    "robin": list(STRONG),
    "strong": ["adaptive", "tag", "lag", "trapper", "balanced", "tight_iso_a", "tight_iso_b"],
    "mixed": ["adaptive", "tag", "tight_iso_a", "kit_starter", "kit_station", "kit_tag", "kit_random"],
    "kit": KIT7,
    "real": ["kit_starter", "kit_starter", "kit_starter", "tight_iso_a", "tight_iso_b"],
}


def play(field, rounds, hands, seed, hero=True, seats=8):
    logs = {}
    for r in range(rounds):
        rng = random.Random(seed + r)
        kinds = list(field)
        room = seats - (1 if hero else 0)
        if len(kinds) > room:
            kinds = rng.sample(kinds, room)
        names = (["hero"] if hero else []) + ["%s#%d" % (k, i) for i, k in enumerate(kinds)]
        order = list(names)
        rng.shuffle(order)
        bots = {}
        for nm in order:
            kind, _, i = nm.partition("#")
            bots[nm] = Bot(seed=seed + r, strict=True) if nm == "hero" else RIVALS[kind](seed=(seed + r) * 100 + int(i))
        totals, log = Table(bots, seed=seed + r).play(hands)
        if sum(totals.values()):
            raise AssertionError("chips not conserved in round %d" % r)
        for nm in names:
            logs.setdefault(nm.partition("#")[0], []).extend(log[nm])
    return logs


def summary(xs):
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / max(1, n - 1))
    return 100 * mean / BB, 100 * 1.96 * sd / math.sqrt(n) / BB


def show(title, logs, t):
    hands = max(len(xs) for xs in logs.values())
    print("%s  (%d hands, %.0fs)" % (title, hands, t))
    for kind, xs in sorted(logs.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        mean, ci = summary(xs)
        print("  %-12s %+8.1f ±%6.1f bb/100   over %d hands" % (kind, mean, ci, len(xs)))


def main():
    ap = argparse.ArgumentParser(description="Round-by-round tables of rivals, with or without the bot.")
    ap.add_argument("--field", default="robin", help="preset (%s) or comma list of rival names, *N to repeat" % ", ".join(PRESETS))
    ap.add_argument("--no-hero", action="store_true")
    ap.add_argument("--versus-kit", action="store_true", help="seat each named rival alone with seven kit bots")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seats", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    field = []
    for tok in PRESETS.get(a.field) or a.field.split(","):
        kind, _, rep = tok.partition("*")
        field += [kind] * int(rep or 1)
    if a.versus_kit:
        for kind in field:
            t = time.time()
            logs = play([kind] + KIT7[:a.seats - 1], a.rounds, a.hands, a.seed, hero=False, seats=a.seats)
            show("%s with %d kit bots" % (kind, a.seats - 1), logs, time.time() - t)
        return
    t = time.time()
    logs = play(field, a.rounds, a.hands, a.seed, hero=not a.no_hero, seats=a.seats)
    show(("" if a.no_hero else "hero + ") + ",".join(field), logs, time.time() - t)


if __name__ == "__main__":
    main()
