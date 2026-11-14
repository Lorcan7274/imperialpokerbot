import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pokerbot.model import classify
from pokerbot.state import Rec

STREETS = {"flop": 1, "turn": 2, "river": 3}
NAMES = "PFTR"


def to_history(hand):
    out = []
    street = 0
    bets = {}
    posts = 0
    for ev in hand["events"]:
        if ev[0] == "post":
            out.append(Rec(ev[1], 0, "sb" if posts == 0 else "bb", ev[2], ev[2]))
            bets[ev[1]] = ev[2]
            posts += 1
        elif ev[0] == "board":
            street = STREETS[ev[1]]
            bets = {}
        elif ev[0] == "act":
            seat, kind, amount = ev[1], ev[2], ev[3] or 0
            prev = bets.get(seat, 0)
            to = amount if kind == "raise" else prev + amount if kind == "call" else prev
            bets[seat] = to
            out.append(Rec(seat, street, kind, to - prev, to))
    return out


def results(hand):
    if "results" in hand:
        r = hand["results"]
        return {int(k): v for k, v in r.items()} if isinstance(r, dict) else dict(enumerate(r))
    return {i: e - s for i, (s, e) in enumerate(zip(hand["stacks"], hand["end"]))}


def describe(hand, me):
    parts = []
    street = None
    for r in to_history(hand):
        if r.kind in ("sb", "bb"):
            continue
        if r.street != street:
            street = r.street
            parts.append("| " + NAMES[street])
        who = "ME" if r.player == me else "s%d" % r.player
        parts.append("%s:%s%s" % (who, "x" if r.kind == "check" else r.kind[0],
                                  r.to if r.kind in ("raise", "call") else ""))
    return " ".join(parts)


class Seat:
    def __init__(self):
        self.hands = 0
        self.net = 0
        self.opp = Counter()
        self.cnt = Counter()
        self.vpip = self.pfr = self.showdowns = 0
        self.opens = Counter()
        self.shown = []

    def rate(self, sit, act):
        return 100.0 * self.cnt[(sit, act)] / self.opp[sit] if self.opp[sit] else float("nan")


def analyse(path, verbose):
    data = json.load(open(path))
    hands = data["hands"]
    rd = data.get("round", {})
    seats = defaultdict(Seat)
    me = data.get("seat", rd.get("seat"))
    if me is None:
        owners = Counter()
        for h in hands:
            for k in h.get("hole", {}):
                owners[int(k)] += 1
        me = owners.most_common(1)[0][0] if owners else None
    bb = hands[0].get("bb", 20)
    mine = []
    for h in hands:
        hist = to_history(h)
        res = results(h)
        events = classify(hist, bb)
        entered, raised, opened = set(), set(), False
        for e in events:
            s = seats[e.player]
            s.opp[e.sit] += 1
            s.cnt[(e.sit, e.act)] += 1
            if e.street == 0:
                s.opp["jam"] += 1
                if e.jam:
                    s.cnt[("jam", "jam")] += 1
                if e.act in ("call", "raise"):
                    entered.add(e.player)
                if e.act == "raise":
                    raised.add(e.player)
                    if not opened:
                        s.opens[e.rec.to] += 1
                    opened = True
        shown = h.get("showdown") or {}
        for seat, x in res.items():
            s = seats[seat]
            s.hands += 1
            s.net += x
            s.vpip += seat in entered
            s.pfr += seat in raised
            if str(seat) in shown:
                s.showdowns += 1
                cards = h.get("hole", {}).get(str(seat))
                if cards and seat != me:
                    s.shown.append("".join(cards))
        if me is not None:
            mine.append((res.get(me, 0), h))
    print("== %s  %s  hands=%d  me=seat %s" % (os.path.basename(path), {k: v for k, v in rd.items() if k != "ref"}, len(hands), me))
    names = data.get("seats") or data.get("teams") or rd.get("seats") or {}
    print("seat team             bb/100  VPIP  PFR  3bet fold>open limp  jam | bet  fold>bet raise>bet call>bet | SD  top open sizes")
    for seat in sorted(seats):
        s = seats[seat]
        nm = names[seat] if isinstance(names, list) and seat < len(names) else names.get(str(seat), "") if isinstance(names, dict) else ""
        if isinstance(nm, dict):
            nm = nm.get("team") or nm.get("name") or ""
        print("%s%-3d %-16s %+7.0f  %4.0f %4.0f  %4.0f  %6.0f %5.0f %4.0f | %3.0f  %6.0f %8.0f %7.0f | %3d  %s" % (
            "*" if seat == me else " ", seat, str(nm)[:16], 100.0 * s.net / bb / max(1, s.hands),
            100.0 * s.vpip / max(1, s.hands), 100.0 * s.pfr / max(1, s.hands),
            s.rate("vs_raise", "raise"), s.rate("vs_raise", "fold"), s.rate("unopened", "call"),
            s.rate("jam", "jam"), s.rate("p_no_bet", "raise"), s.rate("p_vs_bet", "fold"),
            s.rate("p_vs_bet", "raise"), s.rate("p_vs_bet", "call"), s.showdowns,
            " ".join("%d:%d" % kv for kv in s.opens.most_common(4))))
    if verbose and mine:
        mine.sort(key=lambda t: t[0])
        for label, chunk in (("worst", mine[:verbose]), ("best", mine[-verbose:][::-1])):
            print("-- my %s hands" % label)
            for x, h in chunk:
                hole = h.get("hole", {})
                shown = " ".join("s%s=%s" % (k, "".join(v)) for k, v in hole.items() if int(k) != me)
                print("%+6d #%-4s %s  board %s  btn %s  %s  %s" % (
                    x, h.get("n"), "".join(hole.get(str(me), [])), "".join(h.get("board", [])),
                    h.get("button"), describe(h, me), shown))
        for seat in sorted(seats):
            if seats[seat].shown:
                print("-- seat %d showed: %s" % (seat, " ".join(seats[seat].shown[:60])))
    return seats, me


def main():
    ap = argparse.ArgumentParser(description="Per-seat statistics from downloaded round files.")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--dir", default="hands")
    ap.add_argument("--verbose", type=int, default=0, help="also print this many best and worst hands")
    a = ap.parse_args()
    paths = a.paths or sorted(p for p in glob.glob(os.path.join(a.dir, "*.json"))
                              if not os.path.basename(p).startswith("_"))
    for p in paths:
        analyse(p, a.verbose)


if __name__ == "__main__":
    main()
