import argparse
import collections
import random
import sys
import time

sys.path.insert(0, ".")
from arena.faithful import Table, normalise
from arena.fuzz import FIELDS, fill, load, pct
from arena.zoo import ZOO


class Timed:
    """Hero seat that keeps CPU and wall time per decision, keyed by decision number."""

    def __init__(self, mod, seed, clock):
        self.mod = mod
        self.seed = seed
        self.clock = clock
        self.rows = []
        self.ends = []
        self.hand = None
        self.post = False
        self.pending_end = 0

    def start_table(self, seat, info):
        self.agent = self.mod.Agent()
        self.agent.bot.rng.seed(self.seed)
        self.agent.on_table_start(info)

    def act(self, state):
        if state["hand_number"] != self.hand:
            self.hand = state["hand_number"]
            self.post = False
        street = state["street"]
        first = street != "preflop" and not self.post
        if street != "preflop":
            self.post = True
        t = self.clock()
        out = normalise(self.agent.act(state))
        dt = self.clock() - t
        live = sum(1 for f in state["folded"] if not f) - 1
        self.rows.append((dt, street, first, live, len(state["history"]), state["hand_number"],
                          out["action"], state["to_call"], self.pending_end))
        self.pending_end = 0
        return out

    def hand_end(self, summary):
        t = self.clock()
        self.agent.on_hand_end(summary)
        dt = self.clock() - t
        self.ends.append(dt)
        self.pending_end = dt


class Copy:
    def __init__(self, mod, seed):
        self.mod = mod
        self.seed = seed

    def start_table(self, seat, info):
        self.agent = self.mod.Agent()
        self.agent.bot.rng.seed(self.seed)
        self.agent.on_table_start(info)

    def act(self, state):
        return normalise(self.agent.act(state))

    def hand_end(self, summary):
        self.agent.on_hand_end(summary)


def once(mod, field, players, betting, cap, hands, seed, clock):
    rng = random.Random(seed)
    names = fill(field, players)
    seats = [Copy(mod, rng.random()) if k == "self" else ZOO[k](seed=rng.random()) for k in names]
    hero = Timed(mod, seed, clock)
    seats.insert(rng.randrange(players), hero)
    Table(seats, hands=hands, betting=betting, raise_cap=cap, seed=seed).play()
    return hero


def best_of(mod, repeats, *cfg, clock=time.process_time_ns):
    runs = [once(mod, *cfg, clock) for _ in range(repeats)]
    base = runs[0].rows
    for r in runs[1:]:
        if [x[1:8] for x in r.rows] != [x[1:8] for x in base]:
            raise SystemExit("runs differ: not deterministic")
    rows = [(min(r.rows[i][0] for r in runs),) + base[i][1:8]
            + (min(r.rows[i][8] for r in runs),) for i in range(len(base))]
    ends = [min(r.ends[i] for r in runs) for i in range(len(runs[0].ends))]
    return rows, ends


def situation(row):
    _, street, first, live, hist, hand, action, to_call, _ = row
    if street == "preflop":
        return "preflop"
    return street + (" first" if first else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="bot.py")
    ap.add_argument("--hands", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--fields", default="house,limp,wild,raisewar,mixed,self")
    ap.add_argument("--betting", default="no_limit")
    ap.add_argument("--cap", type=int, default=0)
    ap.add_argument("--players", default="8")
    ap.add_argument("--wall", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--slow", type=float, default=1.0)
    a = ap.parse_args()
    mod = load(a.bot)
    if a.slow != 1.0:
        real = time.perf_counter

        class Slow:
            perf_counter = staticmethod(lambda: real() * a.slow)

        mod.time = Slow
        if hasattr(mod, "perf_counter"):
            mod.perf_counter = Slow.perf_counter
    clock = time.perf_counter_ns if a.wall else time.process_time_ns
    table = collections.defaultdict(list)
    allrows = []
    allends = []
    seed = a.seed
    for name in a.fields.split(","):
        for players in (int(p) for p in a.players.split(",")):
            seed += 1
            t = time.time()
            rows, ends = best_of(mod, a.repeats, FIELDS[name], players, a.betting, a.cap,
                                 a.hands, seed, clock=clock)
            xs = [r[0] for r in rows]
            print(f"{name:9s} players {players}: decisions {len(rows):5d}  per hand "
                  f"{sum(xs) / a.hands / 1e6:6.3f} ms  mean {sum(xs) / len(xs) / 1e6:.3f}  "
                  f"p99 {pct(xs, 0.99) / 1e6:.3f}  max {max(xs) / 1e6:.3f}  "
                  f"hand_end max {max(ends) / 1e6:.3f}  ({time.time() - t:.0f}s)", flush=True)
            for r in rows:
                table[(situation(r), min(r[3], 7))].append(r[0])
                allrows.append(r + (name, players))
            allends += ends
    print("\nbest-of-%d %s ms per decision      n    mean    p50    p99    max"
          % (a.repeats, "wall" if a.wall else "CPU"))
    for key in sorted(table):
        xs = table[key]
        print(f"  {key[0]:12s} opp {key[1]}  {len(xs):6d}  {sum(xs) / len(xs) / 1e6:6.3f} "
              f"{pct(xs, 0.5) / 1e6:6.3f} {pct(xs, 0.99) / 1e6:6.3f} {max(xs) / 1e6:6.3f}")
    xs = [r[0] for r in allrows]
    print(f"  all: n {len(xs)}  mean {sum(xs) / len(xs) / 1e6:.3f}  p99 {pct(xs, 0.99) / 1e6:.3f}  "
          f"p999 {pct(xs, 0.999) / 1e6:.3f}  max {max(xs) / 1e6:.3f}")
    print(f"  over 2 ms: {sum(1 for x in xs if x > 2e6)}  over 3 ms: {sum(1 for x in xs if x > 3e6)}  "
          f"over 5 ms: {sum(1 for x in xs if x > 5e6)}")
    print(f"  on_hand_end: mean {sum(allends) / len(allends) / 1e6:.3f}  "
          f"p99 {pct(allends, 0.99) / 1e6:.3f}  max {max(allends) / 1e6:.3f}")
    both = [r[0] + r[8] for r in allrows]
    print(f"  act plus the on_hand_end just before it: max {max(both) / 1e6:.3f}")
    print("worst decisions: ms, street, first postflop, opponents, history, hand, answer, to_call, field")
    for r in sorted(allrows, reverse=True)[:a.top]:
        print(f"  {r[0] / 1e6:6.3f}  {r[1]:8s} {str(r[2]):5s} opp {r[3]}  hist {r[4]:3d}  hand {r[5]:4d}  "
              f"{r[6]:6s} to_call {r[7]:5d}  {r[9]} {r[10]}")


if __name__ == "__main__":
    main()
