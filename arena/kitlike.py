import argparse
import sys
import time

sys.path.insert(0, ".")
from arena.engine import Table
from arena.opponents import ALL, Base
from arena.run import report
from pokerbot.cards import card_str
from pokerbot.state import Action

STREET = ["preflop", "flop", "turn", "river"]
NAMES = {"sb": "small_blind", "bb": "big_blind"}


class House(Base):
    def decide(self, s):
        ranks = sorted(c >> 2 for c in s.hole)
        strong = ranks[0] == ranks[1] or ranks[1] >= 9
        if strong and s.max_raise_to > s.my_bet + s.to_call:
            return Action("raise", min(s.min_raise_to + s.pot // 2, s.max_raise_to))
        if not s.to_call:
            return Action("check")
        if s.to_call <= 2 * s.big_blind or strong:
            return Action("call")
        return Action("fold")


class KitSeat:
    def __init__(self, agent, seats, name="hero", hands=1000):
        self.agent = agent
        self.seats = seats
        self.worst = 0.0
        self.total = 0.0
        self.decisions = 0
        if hasattr(agent, "on_table_start"):
            agent.on_table_start({
                "seat": seats.index(name), "num_players": len(seats), "hands": hands,
                "starting_stack": 2000, "stacks_reset_each_hand": True, "small_blind": 10,
                "big_blind": 20, "betting": "no_limit", "raise_cap": None})

    def history(self, records):
        return [{"seat": self.seats.index(r.player), "street": STREET[r.street],
                 "action": NAMES.get(r.kind, r.kind),
                 "amount": r.to if r.kind in ("sb", "bb", "raise") else r.amount} for r in records]

    def decide(self, s):
        seats = self.seats
        bets = [0] * len(seats)
        for r in s.history:
            if r.street == s.street:
                bets[seats.index(r.player)] = r.to
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        legal = (["fold", "call"] if s.to_call else ["check"]) + (["raise"] if can_raise else [])
        state = {
            "hole_cards": [card_str(c) for c in s.hole], "board": [card_str(c) for c in s.board],
            "street": STREET[s.street], "seat": seats.index(s.hero),
            "button": seats.index(s.players[-1]), "stacks": [s.stacks[p] for p in seats],
            "bets": bets, "folded": [p not in s.active for p in seats], "pot": s.pot,
            "to_call": s.to_call, "min_raise_to": s.min_raise_to if can_raise else None,
            "max_raise_to": s.max_raise_to if can_raise else None, "legal_actions": legal,
            "small_blind": 10, "big_blind": s.big_blind, "hand_number": s.hand_id,
            "history": self.history(s.history)}
        t = time.perf_counter()
        out = self.agent.act(state)
        dt = time.perf_counter() - t
        self.worst = max(self.worst, dt)
        self.total += dt
        self.decisions += 1
        kind = out["action"]
        if kind == "all_in":
            return Action("raise", s.max_raise_to)
        return Action(kind, out.get("amount") or 0)

    def end_hand(self, history, showdown):
        if not hasattr(self.agent, "on_hand_end"):
            return
        t = time.perf_counter()
        shown = {str(self.seats.index(p)): [card_str(c) for c in cards]
                 for p, cards in (showdown or {}).items()}
        self.agent.on_hand_end({"history": self.history(history), "shown": shown})
        self.total += time.perf_counter() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="bot.py")
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--field", default="house,house,caller,random,starter,nit,station")
    a = ap.parse_args()
    import importlib.util
    spec = importlib.util.spec_from_file_location("submitted_bot", a.bot)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kinds = dict(ALL, house=House)
    allx = []
    for r in range(a.rounds):
        names = ["hero"] + [f"{k}{i}" for i, k in enumerate(a.field.split(","))]
        seat = KitSeat(mod.Agent(), names)
        bots = {"hero": seat}
        bots.update({nm: kinds[nm.rstrip("0123456789")](seed=a.seed + r * 10 + i)
                     for i, nm in enumerate(names[1:])})
        _, log = Table(bots, seed=a.seed + r).play(a.hands)
        allx += log["hero"]
        print(report(f"round {r + 1}", log["hero"], 20),
              f" worst {seat.worst * 1000:.2f} ms  think {seat.total:.2f} s  decisions {seat.decisions}")
        if r == a.rounds - 1:
            for nm in names[1:]:
                print("   ", report(nm, log[nm], 20))
    print(report("overall", allx, 20))


if __name__ == "__main__":
    main()
