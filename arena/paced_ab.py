"""Paired A/B with each bundle's own time pacing on, under a clock that runs K times this process's CPU time.

Run from the repo root:
  python3 paced_ab.py --a <base> --b <cand> --field <comma list> --name solid7 --seeds 3000:3040 --out ab.jsonl
  python3 paced_ab.py --report ab.jsonl

Unlike arena/abtest.py --paced, the bot's calibration, speed controller and deadline see the server's speed
(K = 4), so each bundle plays at the depth it would reach there. One JSON line per (field, variant, seed);
a rerun skips lines already present.
"""
import argparse
import collections
import importlib.util
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.getcwd())
BB = 20
cpu = time.process_time


def load(path, clock):
    spec = importlib.util.spec_from_file_location("bot_%d" % len(sys.modules), path)
    mod = importlib.util.module_from_spec(spec)
    real = time.perf_counter, time.monotonic
    time.perf_counter = time.monotonic = clock
    try:
        exec(spec.loader.source_to_code(spec.loader.get_data(path), path), mod.__dict__)
    finally:
        time.perf_counter, time.monotonic = real
    proxy = type(time)("time")
    vars(proxy).update(vars(time), perf_counter=clock, monotonic=clock)
    for name, value in list(vars(mod).items()):
        if value is time:
            setattr(mod, name, proxy)
    return mod


def wrap(mod, errors):
    for name in ("_preflop", "_postflop", "end_hand"):
        fn = getattr(mod.Bot, name)

        def inner(*a, _fn=fn, _name=name, **k):
            try:
                return _fn(*a, **k)
            except Exception as e:
                errors[(_name, type(e).__name__, str(e)[:80])] += 1
                raise

        setattr(mod.Bot, name, inner)


def play(mod, field, seed, hands, k, transport):
    from arena.abtest import registry
    from arena.engine import Table
    from arena.kitlike import KitSeat

    class Watch(KitSeat):
        cpus = None

        def decide(self, s):
            t = cpu()
            a = super().decide(s)
            self.cpus.append(cpu() - t)
            return a

        def end_hand(self, *a, **kw):
            t = cpu()
            super().end_hand(*a, **kw)
            self.ends += cpu() - t

    reg = registry()
    names = ["hero"] + ["%s#%d" % (kind, i) for i, kind in enumerate(field)]
    order = list(names)
    random.Random(seed).shuffle(order)
    bots = {}
    for nm in order:
        if nm == "hero":
            agent = mod.Agent()
            agent.bot.rng.seed(seed)
            bots[nm] = hero = Watch(agent, order, nm, hands)
            hero.cpus = []
            hero.ends = 0.0
        else:
            kind, i = nm.rsplit("#", 1)
            bots[nm] = reg[kind](seed=seed * 100 + int(i))
    table = Table(bots, seed=seed)
    _, log = table.play(hands)
    xs = hero.cpus
    return {"raw": sum(log["hero"]) / hands, "fair": sum(table.fair_log["hero"]) / hands, "decisions": len(xs),
            "bank": k * (sum(xs) + hero.ends) + transport * len(xs), "max_ms": 1e3 * k * max(xs),
            "over15": sum(1e3 * k * x > 15 for x in xs), "over20": sum(1e3 * k * x > 20 for x in xs),
            "own": agent.spent, "speed": agent.speed, "trials": agent.bot.trials}


def report(paths, other="B"):
    rows = {}
    for path in paths:
        for line in open(path):
            r = json.loads(line)
            rows.setdefault(r["name"], {}).setdefault(r["variant"], {})[r["seed"]] = r
    pooled = []
    for name, per in rows.items():
        seeds = sorted(set(per.get("A", {})) & set(per.get(other, {})))
        n = len(seeds)
        if n < 2:
            continue
        out = "%-8s n=%3d" % (name, n)
        for key in ("fair", "raw"):
            d = [per[other][s][key] - per["A"][s][key] for s in seeds]
            m = sum(d) / n
            se = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1) / n)
            out += "  " + other + "-A %s %+6.1f se %4.1f" % (key, 100 * m / BB, 100 * se / BB)
            if key == "fair":
                pooled.append((100 * m / BB, 100 * se / BB))
        for v in "A" + other:
            got = [per[v][s] for s in seeds]
            out += "  | %s %+7.1f bb/100, bank mean %.2f max %.2f s, own max %.2f, max %.1f ms, >15: %d, >20: %d, " \
                   "speed %.2f, errors %d" % (
                       v, 100 * sum(g["fair"] for g in got) / n / BB, sum(g["bank"] for g in got) / n,
                       max(g["bank"] for g in got), max(g["own"] for g in got), max(g["max_ms"] for g in got),
                       sum(g["over15"] for g in got), sum(g["over20"] for g in got),
                       sum(g["speed"] for g in got) / n, sum(g["errors"] for g in got))
            out += ", ended on the quick rules %d" % sum(g["trials"] == 16 for g in got)
        print(out)
    if pooled:
        w = [1 / se ** 2 for _, se in pooled]
        print("pooled (inverse variance): %+.1f se %.1f bb/100" % (
            sum(x * m for x, (m, _) in zip(w, pooled)) / sum(w), 1 / math.sqrt(sum(w))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--field")
    ap.add_argument("--name")
    ap.add_argument("--seeds", default="3000:3010")
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--emulate", type=float, default=4.0)
    ap.add_argument("--transport", type=float, default=0.0015)
    ap.add_argument("--out")
    ap.add_argument("--report", nargs="*")
    ap.add_argument("--label", default="B", help="name of the --b bundle in the output; A rows already there are reused")
    a = ap.parse_args()
    if a.report:
        return report(a.report, a.label)
    field = []
    for tok in a.field.split(","):
        tok, _, rep = tok.partition("*")
        field += [tok] * int(rep or 1)
    k = a.emulate
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            r = json.loads(line)
            done.add((r["name"], r["variant"], r["seed"]))
    mods = {}
    errors = {}
    for v, path in (("A", a.a), (a.label, a.b)):
        mods[v] = load(path, lambda: k * cpu())
        errors[v] = collections.Counter()
        wrap(mods[v], errors[v])
    lo, hi = map(int, a.seeds.split(":"))
    with open(a.out, "a") as f:
        for seed in range(lo, hi):
            for v in "A" + a.label:
                if (a.name, v, seed) in done:
                    continue
                before = sum(errors[v].values())
                row = play(mods[v], field, seed, a.hands, k, a.transport)
                row.update(name=a.name, variant=v, seed=seed, errors=sum(errors[v].values()) - before,
                           what={str(key): n for key, n in errors[v].items()})
                f.write(json.dumps(row) + "\n")
                f.flush()


if __name__ == "__main__":
    main()
