import glob, json, os, sys
from collections import defaultdict
sys.path.insert(0, "/home/user/imperialpokerbot")
from tools.handstats import to_history
from tools.pnl import clones_of, label
from pokerbot.model import classify
from pokerbot.cards import parse_card
from pokerbot.preflop import percentile

def report(path, verbose=True):
    d = json.load(open(path)); names = d["players"]; n = len(names); me = d["seat"]; rd = d.get("round", {})
    clones = clones_of(d)
    tot = [0] * n
    groups = defaultdict(lambda: [0, 0])
    light = [0, 0, 0]; value3 = [0, 0, 0]; milk = [0, 0]; minr = [0, 0]; iso = [0, 0]
    for h in d["hands"]:
        res = h["results"]
        for i in range(n): tot[i] += res[i]
        table, pre, post = label(h, me, n, clones)
        g = groups[table]; g[0] += 1; g[1] += res[me]
        ev = classify(to_history(h), 20, n=n)
        mine = [e for e in ev if e.player == me]
        hole = h["hole"].get(str(me))
        for e in mine:
            if e.street == 0 and e.sit == "vs_raise" and e.act == "raise" and hole:
                p = percentile(*[parse_card(c) for c in hole])
                tgt = light if p >= 0.12 else value3
                tgt[0] += 1; tgt[1] += res[me]
                tgt[2] += not any(x.street > 0 for x in ev) and res[me] > 0
                break
        if any(e.street in (1, 2) and e.act == "raise" and e.sit[:8] == "p_no_bet" and e.rec.amount == 40 for e in mine):
            milk[0] += 1; milk[1] += res[me]
        if mine and mine[0].street == 0 and mine[0].act == "raise" and mine[0].sit[:8] == "unopened":
            k = mine[0].rec.to
            b = minr if k <= 45 else iso if k <= 65 and any(e.act == "call" and e.player in clones for e in ev if e.street == 0) else None
            if b is not None:
                b[0] += 1; b[1] += res[me]
    H = len(d["hands"])
    line = "%s v%s seat %d/%d: %+.1f bb/100, timeouts %s, think %ss" % (
        rd.get("ref", os.path.basename(path)), rd.get("version"), me, n, rd.get("bb100", tot[me] / 20 / H * 100), rd.get("timeouts"), rd.get("think_s"))
    print(line)
    if verbose:
        print("   table: " + " | ".join("%s%s %+.0f" % ("*" if i in clones else "", names[i][:14], tot[i] / 20 / H * 100) for i in sorted(range(n), key=lambda i: -tot[i])))
        print("   ours by hand type: " + ", ".join("%s: %d hands %+.1f bb/100" % (k, v[0], v[1] / 20 / H * 100) for k, v in sorted(groups.items())))
        print("   3-bets: value %d (net %+d, won preflop %d) | light %d (net %+d, won preflop %d) | 40-chip milk lines %d (net %+d)" % (
            value3[0], value3[1], value3[2], light[0], light[1], light[2], milk[0], milk[1]))
        print("   opens to 40 with a starter behind: %d (net %+d) | raises to 60 over a starter limp: %d (net %+d)" % (minr[0], minr[1], iso[0], iso[1]))
    return rd

if __name__ == "__main__":
    for f in sys.argv[1:]:
        report(f)
