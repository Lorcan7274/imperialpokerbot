import json, sys, importlib.util, glob
sys.path.insert(0, "/home/user/imperialpokerbot")
from tools.replay import Hand
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
A = load(S + "/bot_v6h.py", "bh"); B = load(S + "/bot_v6k.py", "bk")
tot = {"n": 0, "net": 0.0, "won": 0}
for rn in sys.argv[1:]:
    data = json.load(open(S + "/hands/saturday_r%s.json" % rn)); me = data["seat"]; names = data["players"]
    ags = []
    for m in (A, B):
        ag = m.Agent(); ag.CALIBRATE = False
        ag.on_table_start({"seat": me, "num_players": len(names), "hands": 1000}); ags.append(ag)
    for rec in data["hands"]:
        h = Hand(rec)
        for state, kind, amount in h.steps():
            if state["seat"] == me:
                for ag in ags: ag.bot.rng.seed(rec["n"] * 31 + len(state["history"]))
                oa = ags[0].act(state); ob = ags[1].act(state)
                if len(state["board"]) == 5 and oa["action"] != ob["action"]:
                    sd = {names[int(k)][:8]: "".join(rec["hole"][k]) for k in (rec.get("showdown") or {}) if k in rec["hole"] and int(k) != me}
                    res = rec["results"][me]
                    print("r%s #%-4d %s board %s to call %4d into %4d | v6.3 %-5s final %-5s | really %-5s result %+6d %s" % (
                        rn, rec["n"], "".join(rec["hole"][str(me)]), "".join(rec["board"]), state["to_call"], state["pot"], oa["action"], ob["action"], kind, res, sd))
                    if oa["action"] == "fold" and ob["action"] == "call" and kind == "call":
                        tot["n"] += 1; tot["net"] += res; tot["won"] += res > 0
        for ag in ags: ag.on_hand_end(h.summary())
print("river calls the final build makes that v6.3 would fold, where the live bot did call: n=%d, won %d, net of those hands %+d chips" % (tot["n"], tot["won"], tot["net"]))
