import argparse
import math
import sys
import time

sys.path.insert(0, ".")
from arena.engine import Table
from arena.opponents import ALL
from pokerbot import Bot


def report(name, xs, bb):
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / max(1, n - 1))
    return f"{name:10s} {100 * mean / bb:+9.1f} bb/100  ±{100 * 1.96 * sd / math.sqrt(n) / bb:6.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    names = [x for x in a.only.split(",") if x] or list(ALL)
    if a.table:
        bots = {"hero": Bot(seed=a.seed, strict=True)}
        bots.update({k: ALL[k](seed=a.seed + i) for i, k in enumerate(names[:5])})
        t = time.time()
        _, log = Table(bots, seed=a.seed).play(a.hands)
        for k in bots:
            print(report(k, log[k], 20))
        print(f"{time.time() - t:.1f}s")
        return
    for k in names:
        hero = Bot(seed=a.seed, strict=True)
        t = time.time()
        _, log = Table({"hero": hero, k: ALL[k](seed=a.seed)}, seed=a.seed).play(a.hands)
        print(report("vs " + k, log["hero"], 20), f"  {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
