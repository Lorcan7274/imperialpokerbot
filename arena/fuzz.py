import argparse
import collections
import gc
import importlib.util
import random
import sys
import time
import traceback

sys.path.insert(0, ".")
from arena.faithful import Table, normalise
from arena.zoo import ZOO

FIELDS = {
    "house": "station,random,tag,starter,station,random,tag",
    "wild": "maniac,shover,minraiser,checkraiser,weird,random,maniac",
    "limp": "limper,station,limper,station,limper,station,limper",
    "raisewar": "minraiser,minraiser,minraiser,station,station,checkraiser,maniac",
    "tight": "nit,tag,nit,folder,tag,nit,starter",
    "mixed": "station,random,tag,starter,maniac,limper,nit",
    "self": "self,self,self,station,random,tag,self",
}


def load(path, name="bot"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Probe:
    """Counts what Agent.act swallows, what it answers illegally and what it costs."""

    def __init__(self, mod):
        self.mod = mod
        self.errors = collections.Counter()
        self.samples = {}
        self.flags = collections.Counter()
        self.flag_samples = {}
        self.cpu = collections.defaultdict(list)
        self.worst = []
        self.sims = collections.defaultdict(list)
        self.end_cpu = []
        self.gc_in_act = []
        self.in_act = False
        self.sim_calls = 0
        self.decisions = 0
        for owner, name in ((mod.Bot, "_preflop"), (mod.Bot, "_postflop"), (mod.Bot, "decide"),
                            (mod.Bot, "end_hand"), (mod, "convert_state"), (mod, "convert_history")):
            self.wrap(owner, name)
        sim = mod.simulate
        probe = self

        def simulate(hero, board, sample, ranges, trials, rng, *a, **k):
            out = sim(hero, board, sample, ranges, trials, rng, *a, **k)
            probe.sim_calls += 1
            probe.sims[(len(board), len(ranges))].append((trials, len(out)))
            return out

        mod.simulate = simulate
        self._t = 0
        gc.callbacks.append(self.on_gc)

    def on_gc(self, phase, info):
        if phase == "start":
            self._t = time.perf_counter_ns()
        elif self.in_act:
            self.gc_in_act.append((info["generation"], time.perf_counter_ns() - self._t))

    def wrap(self, owner, name):
        fn = getattr(owner, name)
        probe = self

        def inner(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:
                key = (name, type(e).__name__, str(e)[:90])
                probe.errors[key] += 1
                probe.samples.setdefault(key, traceback.format_exc(limit=8))
                raise

        setattr(owner, name, inner)

    def flag(self, what, state, out):
        self.flags[what] += 1
        if what not in self.flag_samples:
            brief = {k: v for k, v in state.items() if k != "history"}
            self.flag_samples[what] = (brief, state["history"][-8:], out)

    def judge(self, state, out, raised):
        legal = state["legal_actions"]
        kind = out.get("action")
        amount = out.get("amount")
        if kind not in ("fold", "check", "call", "raise", "all_in"):
            self.flag("unknown action", state, out)
        elif kind == "check" and state["to_call"] > 0:
            self.flag("check facing a bet (engine folds)", state, out)
        elif kind == "fold" and state["to_call"] == 0:
            self.flag("fold with nothing to call", state, out)
        elif kind == "call" and state["to_call"] == 0:
            self.flag("call with nothing to call", state, out)
        elif kind in ("raise", "all_in") and "raise" not in legal:
            self.flag("raise when not allowed (engine calls)", state, out)
        elif kind == "raise":
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            if not isinstance(amount, int) or isinstance(amount, bool):
                self.flag("raise amount not an int", state, out)
            elif amount < lo:
                self.flag("raise below min (engine raises it)", state, out)
            elif amount > hi:
                self.flag("raise above max (engine lowers it)", state, out)
        if raised and kind in ("call", "raise", "all_in") and state["to_call"] > 0:
            self.flag("chips committed after a swallowed exception", state, out)
        elif raised:
            self.flag("swallowed exception, check or fold", state, out)

    def record(self, state, out, cpu, sims, first_post):
        self.decisions += 1
        live = sum(1 for f in state["folded"] if not f) - 1
        street = state["street"]
        if street == "preflop":
            key = ("preflop all-in sim" if sims else "preflop", live)
        else:
            key = (street + (" first" if first_post else ""), live)
        self.cpu[key].append(cpu)
        self.worst.append((cpu, key, len(state["history"]), state["hand_number"]))
        if len(self.worst) > 400:
            self.worst = sorted(self.worst, reverse=True)[:40]


class Hero:
    def __init__(self, mod, probe, seed=None):
        self.mod = mod
        self.probe = probe
        self.seed = seed
        self.agent = None
        self.hand = None
        self.post = False

    def start_table(self, seat, info):
        self.agent = self.mod.Agent()
        if self.seed is not None:
            self.agent.bot.rng.seed(self.seed)
        self.agent.on_table_start(info)

    def act(self, state):
        p = self.probe
        if state["hand_number"] != self.hand:
            self.hand = state["hand_number"]
            self.post = False
        first_post = state["street"] != "preflop" and not self.post
        if state["street"] != "preflop":
            self.post = True
        before = sum(p.errors.values())
        sims = p.sim_calls
        p.in_act = True
        t = time.process_time_ns()
        try:
            out = normalise(self.agent.act(state))
        except Exception as e:
            out = {"action": None, "amount": None}
            key = ("Agent.act", type(e).__name__, str(e)[:90])
            p.errors[key] += 1
            p.samples.setdefault(key, traceback.format_exc(limit=8))
        cpu = time.process_time_ns() - t
        p.in_act = False
        p.judge(state, out, sum(p.errors.values()) > before)
        p.record(state, out, cpu, p.sim_calls - sims, first_post)
        return out

    def hand_end(self, summary):
        t = time.process_time_ns()
        self.agent.on_hand_end(summary)
        self.probe.end_cpu.append(time.process_time_ns() - t)


class Copy:
    def __init__(self, mod):
        self.mod = mod

    def start_table(self, seat, info):
        self.agent = self.mod.Agent()
        self.agent.on_table_start(info)

    def act(self, state):
        return normalise(self.agent.act(state))

    def hand_end(self, summary):
        self.agent.on_hand_end(summary)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def run(mod, probe, field, players, betting, cap, hands, seed):
    rng = random.Random(seed)
    names = field.split(",")[:players - 1]
    seats = [Copy(mod) if k == "self" else ZOO[k](seed=rng.random()) for k in names]
    hero = Hero(mod, probe, seed=seed)
    seats.insert(rng.randrange(players), hero)
    table = Table(seats, hands=hands, betting=betting, raise_cap=cap, seed=seed)
    chips = table.play()
    return chips[seats.index(hero)], table.max_history


def report(probe, top=12):
    print(f"\ndecisions {probe.decisions}")
    print("swallowed exceptions:", sum(probe.errors.values()))
    for key, k in probe.errors.most_common():
        print(f"  {k:6d}  {key}")
        print("      " + probe.samples[key].replace("\n", "\n      "))
    print("flags:")
    for what, k in probe.flags.most_common():
        print(f"  {k:6d}  {what}")
        brief, hist, out = probe.flag_samples[what]
        print(f"      state {brief}\n      last history {hist}\n      answer {out}")
    print("\nCPU ms per decision   n      mean    p50    p99    max")
    for key in sorted(probe.cpu, key=lambda k: (k[0], k[1])):
        xs = probe.cpu[key]
        print(f"  {key[0]:22s} opp {key[1]}  {len(xs):6d}  {sum(xs) / len(xs) / 1e6:6.3f} "
              f"{pct(xs, 0.5) / 1e6:6.3f} {pct(xs, 0.99) / 1e6:6.3f} {max(xs) / 1e6:6.3f}")
    allx = [x for xs in probe.cpu.values() for x in xs]
    if allx:
        print(f"  all: mean {sum(allx) / len(allx) / 1e6:.3f}  p99 {pct(allx, 0.99) / 1e6:.3f}  "
              f"p999 {pct(allx, 0.999) / 1e6:.3f}  max {max(allx) / 1e6:.3f}  total {sum(allx) / 1e9:.2f} s")
    if probe.end_cpu:
        xs = probe.end_cpu
        print(f"  on_hand_end: mean {sum(xs) / len(xs) / 1e6:.3f}  max {max(xs) / 1e6:.3f}")
    print("worst decisions (cpu ms, situation, history length, hand):")
    for cpu, key, hl, hand in sorted(probe.worst, reverse=True)[:top]:
        print(f"  {cpu / 1e6:6.3f}  {key}  history {hl}  hand {hand}")
    if probe.gc_in_act:
        by = collections.defaultdict(list)
        for g, ns in probe.gc_in_act:
            by[g].append(ns)
        print("gc pauses inside act (ms):", {g: (len(v), round(max(v) / 1e6, 3)) for g, v in by.items()})
    print("valid simulation trials (board cards, opponents): runs, mean asked, mean valid, min valid, zero")
    for key in sorted(probe.sims):
        xs = probe.sims[key]
        print(f"  {key}: {len(xs):6d}  {sum(a for a, _ in xs) / len(xs):6.1f}  "
              f"{sum(v for _, v in xs) / len(xs):6.1f}  {min(v for _, v in xs):4d}  "
              f"{sum(1 for _, v in xs if v == 0):5d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="bot.py")
    ap.add_argument("--hands", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fields", default=",".join(FIELDS))
    ap.add_argument("--betting", default="no_limit,pot_limit,fixed_limit")
    ap.add_argument("--caps", default="0,1,3")
    ap.add_argument("--players", default="7,8")
    a = ap.parse_args()
    mod = load(a.bot)
    probe = Probe(mod)
    seed = a.seed
    for name in a.fields.split(","):
        for betting in a.betting.split(","):
            for cap in (int(c) for c in a.caps.split(",")):
                for players in (int(p) for p in a.players.split(",")):
                    seed += 1
                    t = time.time()
                    chips, longest = run(mod, probe, FIELDS[name], players, betting, cap, a.hands, seed)
                    print(f"{name:9s} {betting:11s} cap {cap} players {players}: "
                          f"{100 * chips / 20 / a.hands:+8.1f} bb/100  longest history {longest:3d}  "
                          f"errors {sum(probe.errors.values())}  {time.time() - t:.1f}s", flush=True)
    report(probe)


if __name__ == "__main__":
    main()
