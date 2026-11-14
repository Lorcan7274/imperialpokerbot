import argparse
import collections
import json
import sys
import time

sys.path.insert(0, ".")
from arena.faithful import Table, normalise
from arena.fuzz import load, pct
from arena.replay import Fixed, Replay, Script


class Hero(Script):
    """Our seat in a recorded round: the bot is asked and timed, the recorded action is played."""

    def __init__(self, seat, table, mod, slow, rows):
        super().__init__(seat, table)
        self.agent = mod.Agent()
        self.agent.bot.rng.seed(1)
        self.slow = slow
        self.rows = rows
        self.pending = 0.0
        self.post = None

    def act(self, state):
        if state["hand_number"] != self.post:
            self.post = None
        first = state["street"] != "preflop" and self.post is None
        if state["street"] != "preflop":
            self.post = state["hand_number"]
        wire = json.loads(json.dumps(state))
        t = time.process_time_ns()
        try:
            out = normalise(self.agent.act(wire))
        except Exception:
            out = {"action": None}
        dt = (time.process_time_ns() - t) / 1e6 * self.slow
        played = self.table.answer(self.seat, state)
        self.rows.append((dt, state["street"], first, state["hand_number"], out.get("action"),
                          played["action"] if played else None, self.pending,
                          sum(1 for f in state["folded"] if not f) - 1, state["to_call"]))
        self.pending = 0.0
        return played

    def hand_end(self, summary):
        self.table.summary = summary
        wire = json.loads(json.dumps(summary))
        t = time.process_time_ns()
        self.agent.on_hand_end(wire)
        self.pending = (time.process_time_ns() - t) / 1e6 * self.slow


def replay(mod, data, slow):
    me = data["seat"]
    hands = data["hands"]
    n = len(hands[0]["start_stacks"])
    r = Replay()
    rows = []
    seats = [Script(i, r) for i in range(n)]
    hero = seats[me] = Hero(me, r, mod, slow, rows)
    table = Table(seats, hands=len(hands), wire=False)
    table.rng = Fixed()
    hero.agent.on_table_start(table.info(me))
    for hand in hands:
        r.hand = hand
        table.rng.order = r.deck(hand, n)
        r.acts = collections.deque((e[1], e[2], e[3] or 0) for e in hand["events"] if e[0] == "act")
        table.stacks = list(hand["start_stacks"])
        table.hand(hand["n"], hand["button"])
    return rows, r.problems, hero.agent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--bot", default="bot.py")
    ap.add_argument("--slow", default="1")
    ap.add_argument("--overhead", type=float, default=0.6)
    ap.add_argument("--repeats", type=int, default=1)
    a = ap.parse_args()
    for slow in (float(x) for x in a.slow.split(",")):
        for path in a.files:
            data = json.load(open(path))
            best = None
            for _ in range(a.repeats):
                mod = load(a.bot)
                if slow != 1.0:
                    real = time.perf_counter

                    class Slow:
                        perf_counter = staticmethod(lambda: real() * slow)

                    mod.time = Slow
                    if hasattr(mod, "perf_counter"):
                        mod.perf_counter = Slow.perf_counter
                rows, problems, agent = replay(mod, data, slow)
                if best is None or sum(r[0] for r in rows) < sum(r[0] for r in best):
                    best = rows
            rows = best
            pre = sorted(r[0] for r in rows if r[1] == "preflop")
            post = sorted(r[0] for r in rows if r[1] != "preflop")
            total = sum(pre) + sum(post) + a.overhead * len(rows)
            late = [r for r in rows if r[0] + r[6] + a.overhead > 10]
            rd = data.get("round", {})
            print(f"{data['ref']} x{slow:g}: decisions {len(rows)} (postflop {len(post)})  "
                  f"postflop ms mean {sum(post) / len(post):.2f} p50 {pct(post, 0.5):.2f} "
                  f"p99 {pct(post, 0.99):.2f} max {post[-1]:.2f} | preflop mean {sum(pre) / len(pre):.2f} "
                  f"p99 {pct(pre, 0.99):.2f} max {pre[-1]:.2f} | predicted think {total / 1000:.2f} s "
                  f"(server said {rd.get('think_s')}) | decisions over 10 ms with {a.overhead} ms overhead "
                  f"and the hand_end before them: {len(late)} (server timeouts {rd.get('timeouts')}) "
                  f"| speed now {getattr(agent, 'speed', None)}", flush=True)
            if problems:
                print("   replay problems", dict(problems))


if __name__ == "__main__":
    main()
