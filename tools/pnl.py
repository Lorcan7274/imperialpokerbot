import argparse
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pokerbot.model import classify
from tools.handstats import to_history

CLONE_SHARE = 0.85


def clones_of(data):
    n = len(data["players"])
    tot = [0] * n
    fit = [0] * n
    for h in data["hands"]:
        for e in classify(to_history(h), 20, n=n):
            if e.act == "raise":
                tot[e.player] += 1
                fit[e.player] += e.fit
    return {i for i in range(n) if tot[i] >= 20 and fit[i] >= CLONE_SHARE * tot[i]}


def label(h, me, n, clones):
    events = classify(to_history(h), 20, n=n)
    pre = [e for e in events if e.street == 0]
    mine = [e for e in events if e.player == me]
    mypre = [e for e in mine if e.street == 0]
    post = [e for e in mine if e.street > 0]
    strong = any(e.player in clones and e.act == "raise" for e in pre)
    weak = not strong and any(e.player in clones and e.act == "call" for e in pre)
    table = "starter raised" if strong else "starter limped" if weak else "no starter"
    if not mypre:
        return table, "walk", "-"
    first = mypre[0]
    acts = [e.act for e in mypre]
    if first.act == "fold":
        pre_line = "fold " + first.sit.split(":")[0]
    elif first.sit[:8] == "unopened":
        pos = {"": "early", ":l": "late", ":b": "sb", ":o": "bb"}[first.sit[8:]]
        if first.act == "raise":
            rest = acts[1:]
            pre_line = "open %s" % pos + (" > fold" if "fold" in rest else " > 4bet" if "raise" in rest
                                         else " > call 3bet" if "call" in rest else "")
        else:
            pre_line = "%s %s" % ("limp" if first.act == "call" else "check", pos) + (
                " > fold" if "fold" in acts[1:] else "")
    elif first.sit == "vs_raise":
        if first.act == "raise":
            pre_line = "3bet" + (" > fold" if "fold" in acts[1:] else " > more" if len(acts) > 1 else "")
        else:
            pre_line = "call open" + (" bb" if first.rec.to - first.rec.amount >= 20 else "") + (
                " > fold" if "fold" in acts[1:] else "")
    else:
        pre_line = "%s vs 3bet+" % first.act
    if not post:
        saw = any(e.street > 0 for e in events) and acts[-1] != "fold"
        post_line = "no flop" if not saw else "flop, no action"
    else:
        bets = sum(1 for e in post if e.act == "raise")
        calls = sum(1 for e in post if e.act == "call")
        last = post[-1]
        end = "fold" if last.act == "fold" else "showdown" if str(me) in (h.get("showdown") or {}) else "won unseen"
        post_line = "%s%s, %s" % ("bet" if bets else "passive", "+call" if calls and bets else "", end)
    return table, pre_line, post_line


def main():
    ap = argparse.ArgumentParser(description="Where our chips come from and go, by line, in downloaded rounds.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--min", type=int, default=15, help="smallest group to print")
    a = ap.parse_args()
    files = [f for p in a.paths for f in sorted(glob.glob(p))]
    groups = defaultdict(lambda: [0, 0, 0])
    hands = 0
    for f in files:
        data = json.load(open(f))
        me = data["seat"]
        n = len(data["players"])
        clones = clones_of(data)
        for h in data["hands"]:
            hands += 1
            res = h["results"][me]
            table, pre_line, post_line = label(h, me, n, clones)
            for key in ((table, "ALL", ""), (table, pre_line, ""), (table, pre_line, post_line)):
                g = groups[key]
                g[0] += 1
                g[1] += res
                g[2] += res * res
    print("%d rounds, %d hands; bb/100 is the group's contribution to the overall rate" % (len(files), hands))
    for key in sorted(groups, key=lambda k: (k[0], k[1] != "ALL", k[1], k[2])):
        cnt, net, sq = groups[key]
        if cnt < a.min and key[1] != "ALL":
            continue
        sd = (sq - net * net / cnt) ** 0.5 if cnt > 1 else 0.0
        indent = "" if key[1] == "ALL" else "  " if not key[2] else "      "
        print("%-52s n=%5d  net %+8d  %+7.1f bb/100  (+-%.1f)  avg %+6.1f bb" % (
            indent + (key[0] if key[1] == "ALL" else key[1] if not key[2] else key[2]),
            cnt, net, net / 20.0 / hands * 100, 1.96 * sd / 20.0 / hands * 100, net / 20.0 / cnt))


if __name__ == "__main__":
    main()
