import argparse
import collections
import json
import sys

sys.path.insert(0, ".")
from arena.faithful import Table
from pokerbot.cards import parse_card


class Fixed:
    """Stands in for the table's rng: deals the cards the record shows."""

    def __init__(self):
        self.order = []

    def randrange(self, n):
        return 0

    def shuffle(self, deck):
        deck[:] = self.order


class Script:
    def __init__(self, seat, table):
        self.seat = seat
        self.table = table

    def start_table(self, seat, info):
        pass

    def act(self, state):
        return self.table.answer(self.seat, state)

    def hand_end(self, summary):
        self.table.summary = summary


class Replay:
    def __init__(self, betting="no_limit", cap=0):
        self.betting = betting
        self.cap = cap
        self.problems = collections.Counter()
        self.samples = {}
        self.seen = collections.Counter()

    def note(self, what, hand, detail):
        self.problems[what] += 1
        self.samples.setdefault(what, (hand["n"], detail))

    def answer(self, seat, state):
        hand = self.hand
        if not self.acts:
            self.note("asked for an action the record does not have", hand, (seat, state["street"]))
            return None
        want, kind, amount = self.acts.popleft()
        self.seen[kind] += 1
        if want != seat:
            self.note("wrong seat to act", hand, (seat, want, state["street"]))
        legal = state["legal_actions"]
        if kind == "raise":
            self.seen["raise all-in" if amount == state["max_raise_to"] else "raise"] += 0
            if "raise" not in legal:
                self.note("recorded raise where my table allows none", hand, (seat, amount))
            elif not state["min_raise_to"] <= amount <= state["max_raise_to"]:
                self.note("recorded raise outside my min/max", hand,
                          (seat, amount, state["min_raise_to"], state["max_raise_to"]))
        elif kind == "call":
            if state["to_call"] != amount:
                self.note("recorded call differs from my to_call", hand, (seat, amount, state["to_call"]))
        elif kind == "check":
            if state["to_call"] != 0:
                self.note("recorded check while my to_call > 0", hand, (seat, state["to_call"]))
        elif kind == "fold":
            if state["to_call"] == 0:
                self.note("recorded fold while my to_call is 0", hand, seat)
        return {"action": kind, "amount": amount}

    def deck(self, hand, n):
        known = {int(k): [parse_card(c) for c in v] for k, v in hand.get("hole", {}).items()}
        board = [parse_card(c) for c in hand.get("board", [])]
        used = set(board) | {c for v in known.values() for c in v}
        spare = [c for c in range(52) if c not in used]
        pops = []
        for seat in range(n):
            pops += known.get(seat) or [spare.pop(), spare.pop()]
        pops += board + [spare.pop() for _ in range(5 - len(board))]
        return spare + pops[::-1]

    def run(self, hands):
        for hand in hands:
            n = len(hand["start_stacks"])
            self.hand = hand
            seats = [Script(i, self) for i in range(n)]
            table = Table(seats, hands=1, betting=self.betting, raise_cap=self.cap, wire=False,
                          stack=hand["start_stacks"][0], sb=hand["sb"], bb=hand["bb"])
            table.rng = Fixed()
            table.rng.order = self.deck(hand, n)
            self.acts = collections.deque((e[1], e[2], e[3] or 0) for e in hand["events"] if e[0] == "act")
            self.summary = None
            table.stacks = list(hand["start_stacks"])
            try:
                table.hand(hand["n"], hand["button"])
            except Exception as e:
                self.note("my table raised " + type(e).__name__, hand, str(e)[:80])
                continue
            if self.acts:
                self.note("recorded actions left over", hand, list(self.acts)[:3])
            mine = [(h["seat"], h["action"], h["amount"]) for h in self.summary["history"]]
            posts = [e for e in hand["events"] if e[0] == "post"]
            theirs = [(posts[0][1], "small_blind", posts[0][2]), (posts[1][1], "big_blind", posts[1][2])]
            theirs += [(e[1], e[2], e[3] or 0) for e in hand["events"] if e[0] == "act"]
            if mine != theirs:
                self.note("history differs", hand, [(a, b) for a, b in zip(mine, theirs) if a != b][:2])
            results = hand["results"]
            results = [results[str(i)] for i in range(n)] if isinstance(results, dict) else results
            net = [table.stacks[i] - hand["start_stacks"][i] for i in range(n)]
            if net != list(results):
                self.note("chip results differ", hand, (net, results))
            wins = sorted((e[1], e[2]) for e in hand["events"] if e[0] == "win")
            if wins != sorted((w["seat"], w["amount"]) for w in self.summary["winners"]):
                self.note("winners differ", hand, (wins, self.summary["winners"]))
            shown = hand.get("showdown") or {}
            if sorted(shown) != sorted(self.summary["shown"]):
                self.note("showdown seats differ", hand, (sorted(shown), sorted(self.summary["shown"])))
            for seat, name in shown.items():
                got = [w["hand"] for w in self.summary["winners"] if str(w["seat"]) == seat]
                if got and got[0] != name:
                    self.note("hand name differs", hand, (seat, name, got[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    for path in a.files:
        data = json.load(open(path))
        hands = data["hands"]
        r = Replay()
        r.run(hands)
        sizes = collections.Counter(len(h["start_stacks"]) for h in hands)
        print(f"{path}: {len(hands)} hands, table sizes {dict(sizes)}, actions replayed {dict(r.seen)}")
        print("  showdowns", sum(1 for h in hands if h.get("showdown")),
              " refunds", sum(1 for h in hands for e in h["events"] if e[0] == "refund"),
              " all-in raises to 2000", sum(1 for h in hands for e in h["events"]
                                            if e[0] == "act" and e[2] == "raise" and e[3] == 2000),
              " split pots", sum(1 for h in hands if sum(1 for e in h["events"] if e[0] == "win") > 1))
        if not r.problems:
            print("  every hand replays identically: order of action, legal ranges, history, results, winners")
        for what, k in r.problems.most_common():
            print(f"  {k:5d}  {what}  e.g. hand {r.samples[what][0]}: {r.samples[what][1]}")


if __name__ == "__main__":
    main()
