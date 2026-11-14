import sys, random
sys.path.insert(0, "/home/user/imperialpokerbot")
from pokerbot.bot import Bot
from pokerbot.state import GameState, Rec
from pokerbot.cards import parse_card

def state(hole, hist, n=6, hero=5, button=5, hand=1):
    players = [(button + 1 + i) % n for i in range(n)]
    bets = {}
    folded = set()
    for r in hist:
        bets[r.player] = r.to
        if r.kind == "fold":
            folded.add(r.player)
    level = max(bets.values())
    mine = bets.get(hero, 0)
    pot = sum(bets.values())
    return GameState(hand_id=hand, hero=hero, hole=[parse_card(c) for c in hole], board=[], pot=pot,
                     to_call=min(level - mine, 2000 - mine), my_bet=mine, my_stack=2000 - mine,
                     min_raise_to=min(2000, 2 * level), max_raise_to=2000, big_blind=20, players=players,
                     active=[p for p in players if p not in folded], history=hist,
                     stacks={p: 2000 - bets.get(p, 0) for p in players})

def run(label, hist_fn, hands=("AsAh", "KsKh", "QsQh", "7c2d"), runs=60):
    out = []
    for h in hands:
        acts = {}
        for k in range(runs):
            bot = Bot(seed=k, strict=True)
            a = bot.decide(state([h[:2], h[2:]], hist_fn()))
            acts[a.kind] = acts.get(a.kind, 0) + 1
        out.append("%s %s" % (h, acts))
    print("%-44s %s" % (label, " | ".join(out)))

# seats: 0 sb, 1 bb, 2 utg, 3 hj, 4 co, 5 button (hero)
blinds = lambda: [Rec(0, 0, "sb", 10, 10), Rec(1, 0, "bb", 20, 20)]
run("cutoff shoves, nobody else in", lambda: blinds() + [Rec(2, 0, "fold", 0, 0), Rec(3, 0, "fold", 0, 0), Rec(4, 0, "raise", 2000, 2000)])
run("one limper, cutoff shoves", lambda: blinds() + [Rec(2, 0, "call", 20, 20), Rec(3, 0, "fold", 0, 0), Rec(4, 0, "raise", 2000, 2000)])
run("two limpers, cutoff shoves", lambda: blinds() + [Rec(2, 0, "call", 20, 20), Rec(3, 0, "call", 20, 20), Rec(4, 0, "raise", 2000, 2000)])
run("two limpers, cutoff raises to 600", lambda: blinds() + [Rec(2, 0, "call", 20, 20), Rec(3, 0, "call", 20, 20), Rec(4, 0, "raise", 600, 600)])
run("utg opens 60, cutoff shoves", lambda: blinds() + [Rec(2, 0, "raise", 60, 60), Rec(3, 0, "fold", 0, 0), Rec(4, 0, "raise", 2000, 2000)])
run("utg shoves, cutoff calls", lambda: blinds() + [Rec(2, 0, "raise", 2000, 2000), Rec(3, 0, "fold", 0, 0), Rec(4, 0, "call", 2000, 2000)])
