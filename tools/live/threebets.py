import json, sys
from collections import defaultdict
sys.path.insert(0, "/home/user/imperialpokerbot")
from tools.handstats import to_history
from pokerbot.model import classify
from pokerbot.cards import parse_card
from pokerbot.preflop import percentile
for path in sys.argv[1:]:
    d = json.load(open(path)); names = d["players"]; n = len(names); me = d["seat"]
    agg = defaultdict(lambda: defaultdict(float))
    opp3 = defaultdict(lambda: defaultdict(float))
    for h in d["hands"]:
        ev = [e for e in classify(to_history(h), 20, n=n) if e.street == 0]
        raises = [e for e in ev if e.act == "raise"]
        if len(raises) >= 2 and raises[1].player == me and raises[0].player != me:
            op = names[raises[0].player]
            a = agg[op]
            hole = h["hole"].get(str(me))
            p = percentile(*[parse_card(c) for c in hole])
            kind = "light" if p >= 0.12 else "value"
            a[kind] += 1; a[kind + "_net"] += h["results"][me]
            i = ev.index(raises[1])
            resp = [x.act for x in ev[i + 1:] if x.player == raises[0].player]
            a[kind + "_" + (resp[0] if resp else "none")] += 1
            a["hand_at"] = a.get("hand_at", "") + ("%d " % h["n"] if kind == "light" else "")
        if raises and raises[0].player == me:
            for e in ev:
                if e.player != me and e.sit == "vs_raise":
                    o = opp3[names[e.player]]
                    o["n"] += 1; o[e.act] += 1
    print(path.split("/")[-1])
    for op, a in sorted(agg.items(), key=lambda kv: -(kv[1]["light"] + kv[1]["value"])):
        print("  vs %-20s value %2d (fold %2d call %2d 4bet %2d, net %+6d) | light %2d (fold %2d call %2d 4bet %2d, net %+6d) at hands %s" % (
            op[:20], a["value"], a["value_fold"], a["value_call"], a["value_raise"], a["value_net"],
            a["light"], a["light_fold"], a["light_call"], a["light_raise"], a["light_net"], a.get("hand_at", "")[:70]))
    print("  our opens faced by each: " + " | ".join("%s: %d (3bet %d, call %d)" % (k[:12], v["n"], v["raise"], v["call"]) for k, v in opp3.items()))
