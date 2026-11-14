import argparse
import random
import sys
import time

sys.path.insert(0, ".")
from arena.faithful import Table
from arena.fuzz import FIELDS, pct
from arena.proc import ProcSeat
from arena.zoo import ZOO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="bot.py")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--field", default="house")
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--betting", default="no_limit")
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--bank", type=float, default=10.0)
    a = ap.parse_args()
    for r in range(a.rounds):
        rng = random.Random(a.seed + r)
        seats = [ZOO[k](seed=rng.random()) for k in FIELDS[a.field].split(",")[:a.players - 1]]
        hero = ProcSeat(a.bot, python=a.python, timeout_ms=a.timeout, bank_ms=a.bank * 1000,
                        timing=True)
        seats.insert(rng.randrange(a.players), hero)
        t = time.time()
        try:
            chips = Table(seats, hands=a.hands, betting=a.betting, raise_cap=a.cap,
                          seed=a.seed + r, wire=False).play()
        finally:
            hero.close()
        xs = sorted(hero.spent)
        print(f"round {r + 1}: {100 * chips[seats.index(hero)] / 20 / a.hands:+8.1f} bb/100  "
              f"load {hero.load_s * 1000:.0f} ms  ready {hero.ready_s * 1000:.1f} ms  "
              f"decisions {len(xs)}  timeouts {hero.timeouts}  errors {len(hero.errors)}  "
              f"bank out {hero.bank_out}  bank used {sum(xs):.2f} s  "
              f"round trip ms mean {sum(xs) / len(xs) * 1000:.3f} p50 {pct(xs, 0.5) * 1000:.3f} "
              f"p99 {pct(xs, 0.99) * 1000:.3f} max {xs[-1] * 1000:.3f}  ({time.time() - t:.0f}s)",
              flush=True)
        over = sorted(d[0] - d[2] for d in hero.detail)
        think = sorted(d[2] for d in hero.detail)
        parse = sorted(d[1] for d in hero.detail)
        if over:
            print(f"         think ms mean {sum(think) / len(think) * 1000:.3f} p99 "
                  f"{pct(think, 0.99) * 1000:.3f} max {think[-1] * 1000:.3f} | overhead ms mean "
                  f"{sum(over) / len(over) * 1000:.3f} p50 {pct(over, 0.5) * 1000:.3f} p99 "
                  f"{pct(over, 0.99) * 1000:.3f} max {over[-1] * 1000:.3f} | state parse ms mean "
                  f"{sum(parse) / len(parse) * 1000:.3f} max {parse[-1] * 1000:.3f}")
        for e in hero.errors[:2]:
            print(e)


if __name__ == "__main__":
    main()
