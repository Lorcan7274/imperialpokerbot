import argparse
import gc
import glob
import importlib.util
import json
import math
import multiprocessing
import os
import sys
import time
import traceback
from collections import Counter

STREETS = ["preflop", "flop", "turn", "river"]
KINDS = ["fold", "check", "call", "raise"]
RAISES = ("raise", "bet", "all_in", "allin")
STARTERS = "FisherMen,Phil AIvey,Attention Is All In,Joca"
PARTS = ["convert_state", "classify", "Sample.__init__", "Sample.board", "narrow", "keep_top",
         "simulate", "sim_equity", "river_equity"]
now = time.perf_counter
cpu = time.process_time


def results(rec):
    r = rec["results"]
    return [r[str(i)] for i in range(len(r))] if isinstance(r, dict) else list(r)


class Hand:
    def __init__(self, rec):
        self.rec = rec
        self.history = []
        self.winners = []
        self.problems = []

    def steps(self):
        rec, history, bad = self.rec, self.history, self.problems.append
        n = len(rec["start_stacks"])
        bb, button = rec["bb"], rec["button"]
        stacks = list(rec["start_stacks"])
        folded = [x <= 0 for x in stacks]
        contrib = [0] * n
        bets = [0] * n
        board = []
        street = "preflop"
        current = min_inc = raises = turn = 0
        pending = set()
        may_raise = {}

        def put(i, amt):
            amt = min(amt, stacks[i])
            stacks[i] -= amt
            bets[i] += amt
            contrib[i] += amt

        def open_round(first):
            nonlocal current, min_inc, raises, turn, pending, may_raise
            actors = [i for i in range(n) if not folded[i] and stacks[i] > 0]
            entered = folded.count(False) > 1 and (
                len(actors) > 1 or any(bets[i] < max(bets) for i in actors))
            current, min_inc, raises, turn = max(bets), bb, 0, first
            pending = set(actors) if entered else set()
            may_raise = dict.fromkeys(pending, True)

        def unfinished():
            return bool(pending) and folded.count(False) > 1

        for ev in rec["events"]:
            kind = ev[0]
            if kind == "post":
                put(ev[1], ev[2])
                history.append({"seat": ev[1], "street": street,
                                "action": "big_blind" if history else "small_blind",
                                "amount": bets[ev[1]]})
                if len(history) == 2:
                    open_round((ev[1] + 1) % n)
            elif kind == "board":
                top = sorted(bets)
                if unfinished() or top[-1] != top[-2]:
                    bad("%s closed with action or an uncalled bet outstanding" % street)
                street, board = ev[1], list(ev[2])
                bets[:] = [0] * n
                open_round((button + 1) % n)
            elif kind == "act":
                i, act, amt = ev[1], ev[2], ev[3] or 0
                due = next((s for s in ((turn + k) % n for k in range(n)) if s in pending), None)
                if due != i or folded.count(False) < 2:
                    bad("seat %d acted on the %s but the engine would ask %s" % (i, street, due))
                to_call = min(current - bets[i], stacks[i])
                others = any(not folded[j] and stacks[j] > 0 for j in range(n) if j != i)
                max_to = bets[i] + stacks[i]
                can_raise = may_raise.get(i, True) and max_to > current and others
                min_to = min(current + min_inc, max_to)
                yield {
                    "type": "act", "hand_number": rec["n"], "street": street, "seat": i,
                    "button": button, "hole_cards": list(rec["hole"].get(str(i), [])),
                    "board": list(board), "small_blind": rec["sb"], "big_blind": bb,
                    "blind_level": 0, "pot": sum(contrib), "stacks": list(stacks),
                    "bets": list(bets), "folded": list(folded), "to_call": to_call,
                    "min_raise_to": min_to if can_raise else None,
                    "max_raise_to": max_to if can_raise else None,
                    "legal_actions": (["fold", "call"] if to_call > 0 else ["check"])
                    + (["raise"] if can_raise else []),
                    "betting": "no_limit", "raise_cap": None, "raises_this_street": raises,
                    "history": list(history)}, act, amt
                if act == "raise":
                    if not can_raise or not min_to <= amt <= max_to:
                        bad("seat %d raised to %d outside [%d, %d] (raise allowed: %s)" % (
                            i, amt, min_to, max_to, can_raise))
                    put(i, amt - bets[i])
                    full = amt - current >= min_inc
                    if full:
                        min_inc = amt - current
                    current = amt
                    raises += 1
                    pending = {j for j in range(n) if j != i and not folded[j] and stacks[j] > 0}
                    for j in pending:
                        if full:
                            may_raise[j] = True
                        else:
                            may_raise.setdefault(j, True)
                elif act == "call":
                    if amt != to_call or to_call <= 0:
                        bad("seat %d called %d with %d to call" % (i, amt, to_call))
                    put(i, amt)
                elif act in ("check", "fold"):
                    if (to_call > 0) != (act == "fold"):
                        bad("seat %d %ss with %d to call" % (i, act, to_call))
                    folded[i] = folded[i] or act == "fold"
                else:
                    bad("seat %d: unknown action %r" % (i, act))
                pending.discard(i)
                may_raise[i] = False
                history.append({"seat": i, "street": street, "action": act, "amount": amt})
                turn = (i + 1) % n
            elif kind == "refund":
                top = sorted(bets)
                if unfinished() or bets[ev[1]] != top[-1] or ev[2] != top[-1] - top[-2]:
                    bad("refund of %d to seat %d does not match the bets" % (ev[2], ev[1]))
                stacks[ev[1]] += ev[2]
                contrib[ev[1]] -= ev[2]
                bets[ev[1]] -= ev[2]
            elif kind == "win":
                self.winners.append({"seat": ev[1], "amount": ev[2], "hand": ev[3]})
        won = Counter()
        for w in self.winners:
            won[w["seat"]] += w["amount"]
        top = sorted(bets)
        if unfinished() or top[-1] != top[-2] or board != rec["board"]:
            bad("the hand ended with action, an uncalled bet or board cards outstanding")
        if [won[i] - contrib[i] for i in range(n)] != results(rec):
            bad("chip results do not match the rebuilt pot")

    def summary(self):
        rec = self.rec
        res = results(rec)
        return {"type": "hand_end", "hand_number": rec["n"], "board": list(rec["board"]),
                "shown": {s: rec["hole"][s] for s in sorted(rec.get("showdown") or {}, key=int)
                          if s in rec["hole"]},
                "winners": self.winners,
                "stacks": [x + res[i] for i, x in enumerate(rec["start_stacks"])],
                "history": self.history}


def normalise(result):
    if isinstance(result, dict):
        return result.get("action"), result.get("amount")
    if isinstance(result, (tuple, list)):
        return (result[0] if result else None), (result[1] if len(result) > 1 else None)
    if isinstance(result, str):
        return result, None
    return None, None


def settle(action, amount, state):
    lo, hi, to_call = state["min_raise_to"], state["max_raise_to"], state["to_call"]
    action = str(action).lower()
    if action in RAISES and lo is not None:
        try:
            target = hi if action in ("all_in", "allin") else int(amount)
        except (TypeError, ValueError, OverflowError):
            target = lo
        return "raise", max(lo, min(target, hi))
    if action in ("call",) + RAISES and to_call > 0:
        return "call", to_call
    return ("check", 0) if to_call == 0 else ("fold", 0)


def fault(action, amount, state):
    if action == "all_in":
        return None
    if action not in state["legal_actions"]:
        return "%r is not in %s" % (action, state["legal_actions"])
    lo, hi = state["min_raise_to"], state["max_raise_to"]
    if action == "raise" and not (type(amount) is int and lo <= amount <= hi):
        return "raise to %r is outside [%d, %d]" % (amount, lo, hi)
    return None


def starter_move(state):
    ranks = sorted("23456789TJQKA".index(c[0]) for c in state["hole_cards"])
    strong = ranks[0] == ranks[1] or ranks[1] >= 11
    if strong and "raise" in state["legal_actions"]:
        return "raise", min(state["min_raise_to"] + state["pot"] // 2, state["max_raise_to"])
    if "check" in state["legal_actions"]:
        return "check", 0
    if state["to_call"] <= 2 * state["big_blind"] or strong:
        return "call", state["to_call"]
    return "fold", 0


def load(path):
    spec = importlib.util.spec_from_file_location("bot", path)
    mod = importlib.util.module_from_spec(spec)
    exec(spec.loader.source_to_code(spec.loader.get_data(path), path), mod.__dict__)
    return mod


def trap(path):
    mon = sys.monitoring
    caught = []

    def handled(code, offset, exc):
        if code.co_filename == path:
            caught.append(exc)

    # fires whenever an except clause inside the bundle takes an error, so none is swallowed unseen
    mon.use_tool_id(mon.DEBUGGER_ID, "replay")
    mon.register_callback(mon.DEBUGGER_ID, mon.events.EXCEPTION_HANDLED, handled)
    mon.set_events(mon.DEBUGGER_ID, mon.events.EXCEPTION_HANDLED)
    return caught


def skew(mod, factor):
    fast = lambda: factor * cpu()
    clock = type(time)("time")
    vars(clock).update(vars(time), perf_counter=fast, monotonic=fast)
    for name, value in list(vars(mod).items()):
        if value is time:
            setattr(mod, name, clock)
        elif value is time.perf_counter or value is time.monotonic:
            setattr(mod, name, fast)


def meter(mod):
    spent = {}

    def timed(label, fn):
        def run(*args, **kw):
            t = now()
            try:
                return fn(*args, **kw)
            finally:
                seconds, calls = spent.get(label, (0.0, 0))
                spent[label] = (seconds + now() - t, calls + 1)
        return run

    for label in PARTS:
        *path, attr = label.split(".")
        owner = mod
        for name in path:
            owner = getattr(owner, name, None)
        if callable(getattr(owner, attr, None)):
            setattr(owner, attr, timed(label, getattr(owner, attr)))
    return spent


def replay_round(job):
    path, a = job
    with open(path) as f:
        data = json.load(f)
    hands, me, teams = data["hands"], data["seat"], data["players"]
    meta = data.get("round") or {}
    starters = {s for s, t in enumerate(teams) if t in a.starters.split(",")}
    # freezing keeps this tool's own heap out of the bot's garbage collections, as in the bare runner
    gc.collect()
    gc.freeze()
    c0 = cpu()
    mod = load(a.bundle)
    loaded = cpu() - c0
    caught = trap(a.bundle)
    if a.emulate:
        skew(mod, a.emulate)
    spent = meter(mod) if a.explain else {}
    agent = mod.Agent()
    bot = getattr(agent, "bot", None)
    if hasattr(bot, "strict"):
        bot.strict = True
    if hasattr(bot, "rng"):
        bot.rng.seed(a.seed)
    model = getattr(bot, "model", None)
    is_clone = getattr(model, "is_clone", None)
    errors, decisions, ends, problems = [], [], [], []

    def call(where, fn, arg):
        c0 = cpu()
        t0 = now()
        try:
            out = fn(arg)
        except Exception as exc:
            out = None
            caught.append(exc)
        wall = now() - t0
        used = cpu() - c0
        for exc in {id(e): e for e in caught}.values():
            errors.append((where, "".join(traceback.format_exception(exc))))
        caught.clear()
        return out, wall, used

    first = hands[0]
    info = {"seat": me, "num_players": len(teams), "format": "fixed_hands",
            "hands": meta.get("hands", len(hands)), "starting_stack": first["start_stacks"][me],
            "stacks_reset_each_hand": True, "small_blind": first["sb"], "big_blind": first["bb"],
            "betting": "no_limit", "raise_cap": None}
    started = call("table start", agent.on_table_start, info)[2] if hasattr(agent, "on_table_start") else 0.0
    speed0 = getattr(agent, "speed", None)
    flags = {s: {"spans": [], "sized": [0, 0]} for s in range(len(teams)) if s != me}
    fit = [0, 0, 0, 0]
    odd = []
    rebuilt = 0
    tag = os.path.basename(path).rsplit("_", 1)[-1].split(".")[0]
    for rec in hands:
        hand = Hand(rec)
        no = rec["n"]
        same = True
        seen = Counter()
        for state, old, old_to in hand.steps():
            rebuilt += 1
            seat = state["seat"]
            if seat != me:
                if old == "raise" and state["min_raise_to"] is not None:
                    sized = flags[seat]["sized"]
                    sized[1] += 1
                    sized[0] += old_to == min(state["min_raise_to"] + state["pot"] // 2,
                                              state["max_raise_to"])
                if seat in starters and state["hole_cards"]:
                    want = starter_move(state)
                    fit[3] += 1
                    fit[2] += want == (old, old_to)
                    if want != (old, old_to):
                        odd.append("hand %d seat %d %s with %s: played %s %d, the starter code says %s %d" % (
                            (no, seat, state["street"], "".join(state["hole_cards"]), old, old_to) + want))
                continue
            # the runner hands the bot a JSON-decoded copy and encodes its reply; both count as its time
            line = json.dumps({"id": len(decisions) + 1, "type": "act", "state": state})
            t = now()
            view = json.loads(line)["state"]
            codec = now() - t
            spent.clear()
            out, wall, used = call("hand %d %s" % (no, state["street"]), agent.act, view)
            action, amount = normalise(out)
            t = now()
            json.dumps({"action": action, "amount": amount, "id": len(decisions) + 1,
                        "type": "action"}, default=repr)
            codec += now() - t
            new, new_to = settle(action, amount, state)
            street = STREETS.index(state["street"])
            d = {"round": tag, "hand": no, "street": street, "wall": wall, "cpu": used,
                 "codec": codec, "old": old, "old_to": old_to, "new": new, "new_to": new_to,
                 "fault": fault(action, amount, state), "same": same, "first": not sum(seen.values()),
                 "nth": seen[street], "opps": state["folded"].count(False) - 1,
                 "acts": len(state["history"]) - 2, "to_call": state["to_call"],
                 "pot": state["pot"], "cards": "".join(state["hole_cards"] + ["|"] + state["board"]),
                 "speed": getattr(agent, "speed", None)}
            if spent:
                d["parts"] = dict(spent)
            if not d["acts"] and ends:
                d["end_wall"], d["end_cpu"] = ends[-1]
            decisions.append(d)
            same = same and new == old
            seen[street] += 1
        problems += ["hand %d: %s" % (no, p) for p in hand.problems]
        if hasattr(agent, "on_hand_end"):
            summary = json.loads(json.dumps(hand.summary()))
            ends.append(call("hand %d end" % no, agent.on_hand_end, summary)[1:])
        if is_clone:
            for s, f in flags.items():
                if is_clone(s):
                    if f["spans"] and f["spans"][-1][1] == no - 1:
                        f["spans"][-1][1] = no
                    else:
                        f["spans"].append([no, no])
    for s, f in flags.items():
        f["final"] = bool(is_clone and is_clone(s))
        f["model"] = [getattr(model, k).get(s, 0) if hasattr(model, k) else -1
                      for k in ("rfit", "rtot", "viol", "badshow")]
        if s in starters:
            fit[0] += f["sized"][0]
            fit[1] += f["sized"][1]
    return {"file": os.path.basename(path), "seat": me, "teams": teams, "meta": meta,
            "hands": len(hands), "decisions": decisions, "ends": ends, "loaded": loaded,
            "started": started, "speed0": speed0, "errors": errors, "problems": problems,
            "fit": fit, "odd": odd, "rebuilt": rebuilt, "flags": flags, "can_flag": bool(is_clone)}


def pick(xs, q):
    return xs[max(0, math.ceil(q * len(xs)) - 1)]


def spread(xs, k):
    xs = sorted(xs)
    return tuple(1000 * k * x for x in (sum(xs) / len(xs), pick(xs, 0.5), pick(xs, 0.99), xs[-1]))


def timings(ds, ends, k, a):
    rows = [(name, [(d["wall"], d["cpu"]) for d in ds if d["street"] == i])
            for i, name in enumerate(STREETS)]
    rows.append(("all", [(d["wall"], d["cpu"]) for d in ds]))
    rows.append(("hand_end", ends))
    rows.append(("end+lead", [(d["wall"] + d["end_wall"], d["cpu"] + d["end_cpu"])
                              for d in ds if "end_cpu" in d]))
    print("   ms %-9s      n | wall mean     p50     p99     max |  cpu mean     p50     p99     max"
          " | over %g ms: wall cpu" % ("x%g" % k if k != 1 else "as run", a.budget))
    for label, pairs in rows:
        if pairs:
            over = tuple(sum(1000 * k * p[j] > a.budget for p in pairs) for j in (0, 1))
            print("   %-12s %6d | %9.3f %7.3f %7.3f %7.3f | %9.3f %7.3f %7.3f %7.3f | %15d %3d" % (
                (label, len(pairs)) + spread([p[0] for p in pairs], k)
                + spread([p[1] for p in pairs], k) + over))


def clock_report(ds, ends, a, rounds=1):
    timings(ds, ends, 1, a)
    timings(ds, ends, a.factor, a)
    wall, used = sum(d["wall"] for d in ds), sum(d["cpu"] for d in ds)
    codec = sorted(d["codec"] for d in ds)
    tail = sum(e[0] for e in ends)
    print("   per round: decisions %.3f s wall, %.3f s cpu; hand ends %.3f s; runner JSON %.3f s"
          " (per decision mean %.3f, max %.3f ms); all x%g = %.2f s of the 10 s bank" % (
              wall / rounds, used / rounds, tail / rounds, sum(codec) / rounds,
              1000 * sum(codec) / max(1, len(codec)), 1000 * codec[-1] if codec else 0.0, a.factor,
              a.factor * (wall + tail + sum(codec)) / rounds))
    on = [d for d in ds if d["same"]]
    print("   over %g ms after x%g on lines the new bot also takes: %d of %d decisions (wall), %d (cpu)" % (
        a.budget, a.factor, sum(1000 * a.factor * d["wall"] > a.budget for d in on), len(on),
        sum(1000 * a.factor * d["cpu"] > a.budget for d in on)))


def trouble(errors, ds):
    print("   exceptions: %d" % len(errors))
    groups = {}
    for where, text in errors:
        groups.setdefault(text, []).append(where)
    for text, where in groups.items():
        print("   %d x, at %s%s" % (len(where), ", ".join(where[:8]), " ..." if len(where) > 8 else ""))
        for line in text.rstrip().split("\n"):
            print("      " + line)
    faults = [d for d in ds if d["fault"]]
    print("   illegal answers: %d" % len(faults))
    for d in faults[:40]:
        print("      %s hand %d %s: %s; the engine plays %s %s" % (
            d["round"], d["hand"], STREETS[d["street"]], d["fault"], d["new"], d["new_to"] or ""))


def actions(ds):
    print("   actions       n | old: fold check  call raise | new: fold check  call raise | same kind")
    for i, name in enumerate(STREETS):
        sub = [d for d in ds if d["street"] == i]
        old, new = Counter(d["old"] for d in sub), Counter(d["new"] for d in sub)
        print("   %-8s %6d |      %4d %5d %5d %5d |      %4d %5d %5d %5d | %7.1f%%" % (
            (name, len(sub)) + tuple(old[k] for k in KINDS) + tuple(new[k] for k in KINDS)
            + (100.0 * sum(d["old"] == d["new"] for d in sub) / max(1, len(sub)),)))
    for i, name in enumerate(STREETS):
        moves = Counter((d["old"], d["new"]) for d in ds if d["street"] == i and d["old"] != d["new"])
        if moves:
            print("   %s changes (old>new): %s" % (name, ", ".join(
                "%s>%s %d" % (o, n, c) for (o, n), c in moves.most_common())))
    pre = [d for d in ds if d["street"] == 0]
    for label, sub in (("every preflop decision", pre),
                       ("first decision of each hand", [d for d in pre if d["first"]])):
        for who in ("new", "old"):
            c = Counter(d[who] for d in sub)
            print("   preflop mix, %s, %s (%d): raise %.1f%%  call %.1f%%  fold %.1f%%  check %.1f%%" % (
                (label, who, len(sub)) + tuple(100.0 * c[k] / max(1, len(sub))
                                               for k in ("raise", "call", "fold", "check"))))
    print("   decisions on lines the new bot also takes: %d of %d" % (
        sum(d["same"] for d in ds), len(ds)))


def slowest(ds, a):
    total = sum(d["wall"] for d in ds)
    parts = {}
    for d in ds:
        for k, (seconds, calls) in d.get("parts", {}).items():
            s, c = parts.get(k, (0.0, 0))
            parts[k] = (s + seconds, c + calls)
    if parts:
        named = sum(s for s, _ in parts.values())
        print("   where the time goes: %s, other %.0f%%" % (", ".join(
            "%s %.0f%% (%d calls)" % (k, 100 * s / total, c)
            for k, (s, c) in sorted(parts.items(), key=lambda kv: -kv[1][0])), 100 * (total - named) / total))
    print("   slowest decisions by cpu: ms as run (x%g) | wall | spot | old > new%s" % (
        a.factor, " | parts in ms" if parts else ""))
    for d in sorted(ds, key=lambda d: -d["cpu"])[:a.top]:
        inner = "  ".join("%s %.2f/%d" % (k, 1000 * s, c) for k, (s, c) in sorted(
            d.get("parts", {}).items(), key=lambda kv: -kv[1][0])[:5])
        print("   %6.3f (%5.2f) | %6.3f | %s #%-4d %-7s act %d of street, %d opp, %2d acts before, "
              "to call %4d, pot %4d, %s | %s > %s %s%s" % (
                  1000 * d["cpu"], 1000 * a.factor * d["cpu"], 1000 * d["wall"], d["round"], d["hand"],
                  STREETS[d["street"]], d["nth"] + 1, d["opps"], d["acts"], d["to_call"], d["pot"],
                  d["cards"], d["old"], d["new"], d["new_to"] or "", " | " + inner if inner else ""))


def flag_rows(r, known):
    out = []
    for s, f in sorted(r["flags"].items()):
        team = r["teams"][s]
        spans = ", ".join("%d-%d" % tuple(x) for x in f["spans"][:4]) + (
            " and %d more" % (len(f["spans"]) - 4) if len(f["spans"]) > 4 else "")
        out.append((team, f["final"], team in known, spans or "never", f["model"], f["sized"], s))
    return out


def show(r, a):
    ds, meta, known = r["decisions"], r["meta"], a.starters.split(",")
    print("== %s  seat %d of %d  %d hands  %d decisions" % (
        r["file"], r["seat"], len(r["teams"]), r["hands"], len(ds)))
    if meta:
        print("   on the server: upload version %s, %+.1f bb/100, %s timeouts, %s errors, think %s s" % (
            meta.get("version"), meta.get("bb100", float("nan")), meta.get("timeouts"),
            meta.get("errors"), meta.get("think_s")))
    print("   engine check: %d actions rebuilt, %d disagree with the record; starter raise sizes "
          "reproduced %d of %d, starter actions on shown hands %d of %d" % (
              (r["rebuilt"], len(r["problems"])) + tuple(r["fit"])))
    for p in r["problems"][:10] + r["odd"][:10]:
        print("      " + p)
    speeds = [d["speed"] for d in ds if d["speed"] is not None]
    print("   cpu to load %.0f ms, table start %.1f ms (x%g: %.0f and %.0f ms)%s" % (
        1000 * r["loaded"], 1000 * r["started"], a.factor, 1000 * a.factor * r["loaded"],
        1000 * a.factor * r["started"],
        "; speed %.2f at start, %.2f lowest, %.2f at the end" % (r["speed0"], min(speeds), speeds[-1])
        if speeds else ""))
    trouble(r["errors"], ds)
    clock_report(ds, r["ends"], a)
    if r["can_flag"]:
        print("   starter flags   seat team                      at end  known  raises of starter size: "
              "rebuilt  bot's count  viol  badshow  flagged after hands")
        for team, final, want, spans, m, sized, s in flag_rows(r, known):
            print("   %-15s %4d %-25s %-7s %-5s %26d/%-5d %5d/%-5d %5d  %7d  %s" % (
                "" if final == want else "MISMATCH", s, team[:25], "yes" if final else "no",
                "yes" if want else "no", sized[0], sized[1], m[0], m[1], m[2], m[3], spans))
    actions(ds)


def overall(rounds, a):
    ds = [d for r in rounds for d in r["decisions"]]
    ends = [e for r in rounds for e in r["ends"]]
    known = a.starters.split(",")
    print("== ALL %d ROUNDS  %s  %d decisions%s%s" % (
        len(rounds), os.path.basename(a.bundle), len(ds),
        "  bot clock = %g x cpu time" % a.emulate if a.emulate else "", "  metered" if a.explain else ""))
    print("   engine check: %d actions rebuilt, %d disagree with the record; starter raise sizes "
          "reproduced %d of %d, starter actions on shown hands %d of %d" % (
              (sum(r["rebuilt"] for r in rounds), sum(len(r["problems"]) for r in rounds))
              + tuple(sum(r["fit"][i] for r in rounds) for i in range(4))))
    trouble([("%s %s" % (r["file"], w), t) for r in rounds for w, t in r["errors"]], ds)
    clock_report(ds, ends, a, len(rounds))
    slowest(ds, a)
    actions(ds)
    if any(r["can_flag"] for r in rounds):
        wrong = 0
        teams = {}
        for r in rounds:
            for team, final, want, spans, m, sized, s in flag_rows(r, known):
                wrong += final != want
                teams.setdefault(team, []).append("%s %s%s (%d/%d)" % (
                    r["file"].rsplit("_", 1)[-1].split(".")[0], spans,
                    "" if final or spans == "never" else " but not at the end", sized[0], sized[1]))
        print("   starter flags at the end of each round against the known list: %s; per team, the hands "
              "after which it was flagged (raises of starter size / raises)" % (
                  "all match" if not wrong else "%d MISMATCHES" % wrong))
        for team, notes in sorted(teams.items(), key=lambda kv: (kv[0] not in known, kv[0])):
            print("   %-8s %-25s %s" % ("starter" if team in known else "other", team[:25], "; ".join(notes)))


def main():
    ap = argparse.ArgumentParser(
        description="Replay real rounds through a bundled bot. Every state our seat faced is rebuilt "
                    "as the organisers' engine sent it, on the real action sequence, one fresh "
                    "process and Agent per round. Needs Python 3.12 or later.")
    ap.add_argument("bundle", help="single-file bot to load")
    ap.add_argument("paths", nargs="*", help="round files; default is every round in --dir")
    ap.add_argument("--dir", default="hands")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--factor", type=float, default=4.0, help="how many times slower the server is")
    ap.add_argument("--budget", type=float, default=8.0, help="ms a decision may take on the server")
    ap.add_argument("--emulate", type=float, default=0.0, metavar="K",
                    help="give the bot a clock that is K x this process's cpu time, so its "
                         "calibration and time guard react as on a quiet machine K times slower "
                         "(1 = this machine with nobody else on it, 4 = the server)")
    ap.add_argument("--explain", action="store_true",
                    help="time the bundle's main functions inside every decision (adds overhead)")
    ap.add_argument("--top", type=int, default=12, help="how many of the slowest decisions to list")
    ap.add_argument("--starters", default=STARTERS,
                    help="comma list of teams known to run the unmodified starter bot")
    ap.add_argument("--json", default="", help="also write every decision to this file")
    a = ap.parse_args()
    a.bundle = os.path.abspath(a.bundle)
    paths = a.paths or sorted(p for p in glob.glob(os.path.join(a.dir, "*.json"))
                              if not os.path.basename(p).startswith("_"))
    if not paths:
        raise SystemExit("no round files")
    print("bundle %s  python %s  seed %d  load average %.1f on %d cores%s" % (
        a.bundle, sys.version.split()[0], a.seed, os.getloadavg()[0], os.cpu_count(),
        "  bot clock = %g x cpu time" % a.emulate if a.emulate else ""))
    rounds = []
    with multiprocessing.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:
        for r in pool.imap(replay_round, [(p, a) for p in paths]):
            show(r, a)
            rounds.append(r)
    overall(rounds, a)
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"bundle": a.bundle, "factor": a.factor, "emulate": a.emulate, "rounds": rounds}, f)


if __name__ == "__main__":
    main()
