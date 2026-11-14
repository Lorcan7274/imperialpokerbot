import json, sys, glob, itertools, random
sys.path.insert(0, "/home/user/imperialpokerbot")
from pokerbot.cards import parse_card, evaluate

def fair_result(h, me):
    """our result with the cards still to come averaged out, when the betting ended all-in before the river"""
    res = h["results"]
    sd = h.get("showdown") or {}
    hole = h.get("hole") or {}
    if str(me) not in sd or len(sd) < 2:
        return res[me], False
    board_seen = 0
    last_board = 0
    paid = [0] * len(res)
    for ev in h["events"]:
        if ev[0] == "board":
            board_seen = len(ev[2])
        elif ev[0] == "act" and ev[2] in ("call", "raise"):
            last_board = board_seen
    if last_board >= 5:
        return res[me], False
    # chips each showdown player put in: start - end is unknown, so rebuild from events
    bets = {}
    street_bets = {}
    for ev in h["events"]:
        if ev[0] == "post":
            street_bets[ev[1]] = ev[2]
        elif ev[0] == "board":
            for k, v in street_bets.items():
                bets[k] = bets.get(k, 0) + v
            street_bets = {}
        elif ev[0] == "act":
            if ev[2] == "raise":
                street_bets[ev[1]] = ev[3]
            elif ev[2] == "call":
                street_bets[ev[1]] = street_bets.get(ev[1], 0) + ev[3]
        elif ev[0] == "refund":
            street_bets[ev[1]] = street_bets.get(ev[1], 0) - ev[2]
    for k, v in street_bets.items():
        bets[k] = bets.get(k, 0) + v
    live = [int(k) for k in sd if k in hole]
    if me not in live or len(live) != len(sd):
        return res[me], False
    cards = {p: [parse_card(c) for c in hole[str(p)]] for p in live}
    board = [parse_card(c) for c in h["board"][:last_board]]
    dead = set(board)
    for c in cards.values():
        dead |= set(c)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    runs = list(itertools.combinations(deck, need))
    if len(runs) > 1200:
        runs = random.Random(h["n"]).sample(runs, 1200)
    total = sum(bets.values())
    exp = 0.0
    for run in runs:
        full = board + list(run)
        vals = {p: evaluate(cards[p] + full) for p in live}
        # side pots by contribution level
        levels = sorted(set(bets[p] for p in live))
        prev = 0
        won = 0.0
        for lv in levels:
            pot = sum(min(b, lv) - min(b, prev) for b in bets.values())
            elig = [p for p in live if bets[p] >= lv]
            best = max(vals[p] for p in elig)
            winners = [p for p in elig if vals[p] == best]
            if me in winners:
                won += pot / len(winners)
            prev = lv
        exp += won - bets.get(me, 0)
    return exp / len(runs), True

if __name__ == "__main__":
    S = "/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad"
    files = sys.argv[1:] or sorted(glob.glob(S + "/hands/saturday_r0*.json"))
    tot_raw = tot_fair = 0; n = 0
    for f in files:
        d = json.load(open(f)); me = d["seat"]
        raw = fair = 0.0; k = 0
        for h in d["hands"]:
            x, adj = fair_result(h, me)
            raw += h["results"][me]; fair += x; k += adj
        H = len(d["hands"])
        print("%s v%s: raw %+7.1f bb/100, all-in luck removed %+7.1f  (%d pots adjusted)" % (d["round"]["ref"][-4:], d["round"]["version"], raw / 20 / H * 100, fair / 20 / H * 100, k))
        tot_raw += raw / 20 / H * 100; tot_fair += fair / 20 / H * 100; n += 1
    print("mean over %d rounds: raw %+.1f, luck removed %+.1f" % (n, tot_raw / n, tot_fair / n))
