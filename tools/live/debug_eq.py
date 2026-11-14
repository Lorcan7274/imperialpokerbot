import json, sys
sys.path.insert(0, "/home/user/imperialpokerbot")
from tools.replay import Hand
import pokerbot.agent as A
import pokerbot.bot as B
from pokerbot.cards import card_str, evaluate
from pokerbot.preflop import percentile
from pokerbot.model import classify, tell_key
from pokerbot.ranges import sim_equity, simulate, river_equity
path, target = sys.argv[1], int(sys.argv[2])
data = json.load(open(path)); hands = data["hands"]; me = data["seat"]; teams = data["players"]
agent = A.Agent(); agent.CALIBRATE = False
agent.bot.rng.seed(1)
agent.on_table_start({"seat": me, "num_players": len(teams), "hands": len(hands)})
bot = agent.bot
orig_post = bot._postflop
orig_upd = bot._update
trace = []
def upd(w, e, s, n, sample):
    if s.hand_id == target and e.street:
        flags = sample.flags(s.board[:B.BOARD_LEN[e.street]])
        tot = sum(w) or 1e-12
        before = sum(x for x, k in zip(w, flags) if k) / tot
    orig_upd(w, e, s, n, sample)
    if s.hand_id == target and e.street:
        tot = sum(w) or 1e-12
        after = sum(x for x, k in zip(w, flags) if k) / tot
        trace.append("        %s street %d %-13s %-5s frac %.2f tell %s freq(bet/raise) %.2f | strong share %.2f -> %.2f" % (teams[e.player][:10], e.street, e.sit, e.act, e.frac, tell_key(e), bot.model.freq(e.player, e.sit, "raise", n) if (e.sit, "raise") in B.Model.__init__.__globals__["PRIORS"] else -1, before, after))
bot._update = upd
def traced(s):
    del trace[:]
    out = orig_post(s)
    if s.hand_id == target:
        n = len(s.players); ctx = {}
        ev = classify(s.history, s.big_blind, ctx=ctx, n=n, now=s.street)
        roles = bot._roles(s, ev)
        del trace[:]
        ranges = bot._ranges(s, ev, roles)
        sample = bot._sample
        vals = sample.board(s.board)[0]
        hv = evaluate(list(s.hole) + list(s.board))
        print("  street", s.street, "board", " ".join(card_str(c) for c in s.board), "to_call", s.to_call, "pot", s.pot, "->", out.kind, getattr(out, "amount", ""))
        for t in trace: print(t)
        for v, w in ranges.items():
            tot = sum(w) or 1e-12
            ahead = sum(x for x, vv in zip(w, vals) if vv > hv) / tot
            tie = sum(x for x, vv in zip(w, vals) if vv == hv) / tot
            top = sorted(((x, sample.combos[i]) for i, x in enumerate(w) if x > 0), reverse=True)[:8]
            print("    vs %-12s currently ahead of us %.2f, tied %.2f, live combos %d; heaviest: %s" % (teams[v][:12], ahead, tie, sum(1 for x in w if x > 0), " ".join("%s%s:%.2f" % (card_str(a), card_str(b), x / tot) for x, (a, b) in top)))
        rl = list(ranges.values())
        eqs = [sim_equity(simulate(s.hole, s.board, sample, rl, 400, bot.rng)) for _ in range(3)] if s.street < 3 else [river_equity(hv, vals, rl)]
        print("    equity vs these ranges (400 trials x3): %s ; price needs %.2f" % (" ".join("%.3f" % e for e in eqs), s.to_call / (s.pot + s.to_call) if s.to_call else 0))
    return out
bot._postflop = traced
for rec in hands:
    if rec["n"] > target:
        break
    h = Hand(rec)
    for state, kind, amount in h.steps():
        if state["seat"] == me:
            agent.act(state)
    agent.on_hand_end(h.summary())
