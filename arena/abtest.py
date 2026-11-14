import argparse
import importlib.util
import math
import multiprocessing
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arena.engine import Table
from arena.kitlike import House, KitSeat
from arena.opponents import ALL

BB = 20
_MODULES = {}


def registry():
    reg = dict(ALL, house=House)
    for mod, attr in (("arena.realfield", "REAL"), ("arena.rivals", "RIVALS"),
                      ("arena.exploiters", "EXPLOITERS")):
        try:
            reg.update(getattr(importlib.import_module(mod), attr))
        except Exception:
            pass
    return reg


def load(path):
    path = os.path.abspath(path)
    if path not in _MODULES:
        spec = importlib.util.spec_from_file_location("variant_%d" % len(_MODULES), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[path] = mod
    return _MODULES[path]


def make_agent(path, seed, paced):
    agent = load(path).Agent()
    bot = getattr(agent, "bot", None)
    if bot is not None and hasattr(bot, "rng"):
        bot.rng.seed(seed)
        bot.strict = True
    if not paced and hasattr(agent, "BANK"):
        agent.BANK = 1e9
        agent.CALIBRATE = False
    return agent


def play_round(job):
    path, field, seed, hands, paced = job
    reg = registry()
    names = ["hero"] + ["%s#%d" % (k, i) for i, k in enumerate(field)]
    order = list(names)
    random.Random(seed).shuffle(order)
    bots = {}
    for nm in order:
        if nm == "hero":
            bots[nm] = hero = KitSeat(make_agent(path, seed, paced), order, nm, hands)
            continue
        kind, i = nm.rsplit("#", 1)
        if kind.startswith("bot:"):
            bots[nm] = KitSeat(make_agent(kind[4:], seed * 100 + int(i), False), order, nm, hands)
        else:
            bots[nm] = reg[kind](seed=seed * 100 + int(i))
    table = Table(bots, seed=seed)
    _, log = table.play(hands)
    others = {}
    for nm in names[1:]:
        kind = nm.rsplit("#", 1)[0]
        others.setdefault(kind, []).append(sum(log[nm]) / hands)
    return log["hero"], hero.worst, hero.total, others, table.fair_log["hero"]


def stats(rounds):
    means = [sum(r) / len(r) for r in rounds]
    m = sum(means) / len(means)
    if len(means) < 2:
        return m, float("nan")
    sd = math.sqrt(sum((x - m) ** 2 for x in means) / (len(means) - 1))
    return m, 1.96 * sd / math.sqrt(len(means))


def fmt(m, ci):
    return "%+8.1f ±%6.1f bb/100" % (100 * m / BB, 100 * ci / BB)


def main():
    ap = argparse.ArgumentParser(description="Paired comparison of bundled bot.py files on identical cards.")
    ap.add_argument("--a", default="bot.py")
    ap.add_argument("--b", default="")
    ap.add_argument("--field", default="house,house,caller,random,starter,nit,station",
                    help="comma list of registry names, bot:<path>, @a or @b; append *N to repeat")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--paced", action="store_true", help="keep the bot's own time-bank pacing on")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print(" ".join(sorted(registry())))
        return
    field = []
    for tok in a.field.split(","):
        tok, _, rep = tok.partition("*")
        tok = {"@a": "bot:" + a.a, "@b": "bot:" + (a.b or a.a)}.get(tok, tok)
        field += [tok] * int(rep or 1)
    variants = [("A", a.a)] + ([("B", a.b)] if a.b else [])
    jobs = [(path, field, a.seed + r, a.hands, a.paced) for _, path in variants for r in range(a.rounds)]
    if a.procs > 1:
        with multiprocessing.Pool(a.procs) as pool:
            res = pool.map(play_round, jobs, chunksize=1)
    else:
        res = [play_round(j) for j in jobs]
    print("field: %s   %d rounds x %d hands" % (",".join(field), a.rounds, a.hands))
    per = {}
    for vi, (label, path) in enumerate(variants):
        chunk = res[vi * a.rounds:(vi + 1) * a.rounds]
        per[label] = [c[0] for c in chunk]
        m, ci = stats(per[label])
        print("%s %-34s %s   worst %.1f ms   think %.2f s/round" % (
            label, path[-34:], fmt(m, ci), 1000 * max(c[1] for c in chunk),
            sum(c[2] for c in chunk) / a.rounds))
    fair = {label: [c[4] for c in res[vi * a.rounds:(vi + 1) * a.rounds]]
            for vi, (label, _) in enumerate(variants)}
    for label, _ in variants:
        m, ci = stats(fair[label])
        print("%s all-in luck removed: %s" % (label, fmt(m, ci)))
    if a.b:
        diffs = [[y - x for x, y in zip(ra, rb)] for ra, rb in zip(per["A"], per["B"])]
        m, ci = stats(diffs)
        print("B - A %s (paired by round)" % fmt(m, ci))
        diffs = [[y - x for x, y in zip(ra, rb)] for ra, rb in zip(fair["A"], fair["B"])]
        m, ci = stats(diffs)
        print("B - A %s (paired, all-in luck removed)" % fmt(m, ci))
    kinds = {}
    for c in res[:a.rounds]:
        for k, xs in c[3].items():
            kinds.setdefault(k, []).extend(xs)
    print("opponents in A's rounds: " + "  ".join(
        "%s %+.0f" % (k[-20:], 100 * sum(xs) / len(xs) / BB) for k, xs in sorted(kinds.items())))


if __name__ == "__main__":
    main()
