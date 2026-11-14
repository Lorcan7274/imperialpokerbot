import json, sys, glob
sys.path.insert(0, "/home/user/imperialpokerbot")
from tools.replay import Hand
import pokerbot.agent as A
import pokerbot.bot as B
from pokerbot.cards import evaluate, parse_card
from pokerbot.model import classify
from pokerbot.ranges import sim_equity, simulate, river_equity
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
pairs = 0
rows = []
for path in sorted(glob.glob(S + "/hands/saturday_r0*.json")):
    data = json.load(open(path)); hands = data["hands"]; me = data["seat"]; teams = data["players"]
    agent = A.Agent(); agent.CALIBRATE = False
    agent.bot.rng.seed(7)
    agent.on_table_start({"seat": me, "num_players": len(teams), "hands": len(hands)})
    bot = agent.bot
    cur = {}
    orig = bot._postflop
    def traced(s, orig=orig, bot=bot, cur=cur):
        out = orig(s)
        if s.to_call > 0 and len(s.active) == 2:
            n = len(s.players); ctx = {}
            ev = classify(s.history, s.big_blind, ctx=ctx, n=n, now=s.street)
            last = [e for e in ev if e.player != s.hero and e.street == s.street and e.act == "raise"]
            if last and (last[-1].sit[:8] != "p_no_bet" or last[-1].shove):
                roles = bot._roles(s, ev)
                if not any(roles.values()):
                    ranges = bot._ranges(s, ev, roles); sample = bot._sample; rl = list(ranges.values())
                    if s.street == 3:
                        vals = sample.board(s.board)[0]
                        eq = river_equity(evaluate(list(s.hole) + list(s.board)), vals, rl)
                    else:
                        eq = sim_equity(simulate(s.hole, s.board, sample, rl, 300, bot.rng))
                    cur["x"] = (s.street, eq, s.to_call, s.pot, last[-1].sit[:8] != "p_no_bet", last[-1].player, out.kind)
        return out
    bot._postflop = traced
    for rec in hands:
        h = Hand(rec); cur.clear(); got = []
        for state, kind, amount in h.steps():
            if state["seat"] == me:
                cur.pop("x", None)
                agent.act(state)
                if "x" in cur and kind == "call":
                    got.append(cur["x"])
        agent.on_hand_end(h.summary())
        sd = rec.get("showdown") or {}
        if got and str(me) in sd:
            board = [parse_card(c) for c in rec["board"]]
            mine = evaluate([parse_card(c) for c in rec["hole"][str(me)]] + board)
            for st, eq, c, pot, israise, v, newact in got:
                if str(v) in sd and str(v) in rec["hole"]:
                    theirs = evaluate([parse_card(x) for x in rec["hole"][str(v)]] + board)
                    won = 1.0 if mine > theirs else 0.5 if mine == theirs else 0.0
                    rows.append((st, eq, won, c, pot, israise, newact, path[-9:-5], rec["n"], "".join(rec["hole"][str(me)]), "".join(rec["board"]), "".join(rec["hole"][str(v)]), teams[v][:10]))
def rep(label, sel):
    for name, keep in (("still calls", lambda r: r[6] != "fold"), ("now folds", lambda r: r[6] == "fold")):
        xs = [r for r in rows if sel(r) and keep(r)]
        if xs:
            ev = sum(r[2] * (r[4] + r[3]) - r[3] for r in xs)
            print("  %-18s %-12s n=%3d  model equity %.3f  actual win rate %.3f  value of those calls %+7.0f chips (%+.0f each)" % (
                label, name, len(xs), sum(r[1] for r in xs) / len(xs), sum(r[2] for r in xs) / len(xs), ev, ev / len(xs)))
print("calls the released build now folds:")
for r in sorted(rows, key=lambda r: (r[0], r[7], r[8])):
    if r[6] == "fold":
        print("  %s #%-4d street %d %s board %-12s vs %-10s %s | %s to call %4d into %4d | model equity %.2f | really %s" % (
            r[7], r[8], r[0], r[9], r[10], r[12], r[11], "raise over our bet" if r[5] else "all-in bet", r[3], r[4], r[1], "WON" if r[2] == 1 else "lost" if r[2] == 0 else "split"))
print("summary on our real calls of raises and shoves that reached showdown heads-up:")
rep("all", lambda r: True)
rep("raise over a bet", lambda r: r[5])
rep("all-in bet", lambda r: not r[5])
rep("flop", lambda r: r[0] == 1); rep("turn", lambda r: r[0] == 2); rep("river", lambda r: r[0] == 3)
