import random
from itertools import combinations, cycle

from pokerbot.cards import evaluate
from pokerbot.state import Action, GameState, Rec


BOARD_AT = {0: 0, 1: 3, 2: 4, 3: 5}


class Table:
    def __init__(self, bots, stack=2000, sb=10, bb=20, seed=0):
        self.bots = bots
        self.seats = list(bots)
        self.stack0 = stack
        self.sb = sb
        self.bb = bb
        self.rng = random.Random(seed)
        self.hand_no = 0
        self.fair = {}
        self.fair_log = {p: [] for p in self.seats}

    def play(self, hands):
        totals = {p: 0 for p in self.seats}
        log = {p: [] for p in self.seats}
        for h in range(hands):
            res = self.play_hand(h % len(self.seats))
            for p, x in res.items():
                totals[p] += x
                log[p].append(x)
        return totals, log

    def play_hand(self, button):
        self.hand_no += 1
        n = len(self.seats)
        order = [self.seats[(button + 1 + i) % n] for i in range(n)]
        deck = list(range(52))
        self.rng.shuffle(deck)
        hole = {p: [deck.pop(), deck.pop()] for p in order}
        stack = {p: self.stack0 for p in order}
        paid = {p: 0 for p in order}
        folded = set()
        history = []
        board = []
        if n == 2:
            sbp, bbp = order[1], order[0]
            pre = [order[1], order[0]]
        else:
            sbp, bbp = order[0], order[1]
            pre = order[2:] + order[:2]

        def put(p, amt):
            amt = min(amt, stack[p])
            stack[p] -= amt
            paid[p] += amt
            return amt

        def betting(street, acting, bets, level, last_raise):
            acted = set()
            for p in cycle(acting):
                live = [q for q in order if q not in folded]
                if len(live) == 1:
                    return
                can = [q for q in live if stack[q] > 0]
                if not [q for q in can if q not in acted or bets[q] < level]:
                    return
                if len(can) <= 1 and all(bets[q] >= level for q in can):
                    return
                if p in folded or stack[p] == 0 or (p in acted and bets[p] >= level):
                    continue
                to_call = min(level - bets[p], stack[p])
                max_to = bets[p] + stack[p]
                others = [q for q in can if q != p]
                min_to = min(level + last_raise, max_to)
                if max_to <= level or not others:
                    min_to = max_to = 0
                state = GameState(
                    hand_id=self.hand_no, hero=p, hole=list(hole[p]), board=list(board),
                    pot=sum(paid.values()), to_call=to_call, my_bet=bets[p], my_stack=stack[p],
                    min_raise_to=min_to, max_raise_to=max_to, big_blind=self.bb,
                    players=list(order), active=[q for q in order if q not in folded],
                    history=list(history), stacks=dict(stack))
                a = self.bots[p].decide(state)
                kind = a.kind
                if kind == "raise" and max_to and min_to <= a.amount <= max_to:
                    add = put(p, int(a.amount) - bets[p])
                    bets[p] += add
                    last_raise = max(last_raise, bets[p] - level)
                    level = bets[p]
                    history.append(Rec(p, street, "raise", add, bets[p]))
                elif kind in ("call", "raise") and to_call > 0:
                    add = put(p, to_call)
                    bets[p] += add
                    history.append(Rec(p, street, "call", add, bets[p]))
                elif to_call > 0:
                    folded.add(p)
                    history.append(Rec(p, street, "fold", 0, bets[p]))
                else:
                    history.append(Rec(p, street, "check", 0, bets[p]))
                acted.add(p)

        bets = {p: 0 for p in order}
        bets[sbp] = put(sbp, self.sb)
        history.append(Rec(sbp, 0, "sb", self.sb, self.sb))
        bets[bbp] = put(bbp, self.bb)
        history.append(Rec(bbp, 0, "bb", self.bb, self.bb))
        betting(0, pre, bets, self.bb, self.bb)
        for street, k in ((1, 3), (2, 1), (3, 1)):
            if len(order) - len(folded) == 1:
                break
            board.extend(deck.pop() for _ in range(k))
            betting(street, order, {p: 0 for p in order}, 0, self.bb)

        live = [p for p in order if p not in folded]
        won = {p: 0 for p in order}
        showdown = None
        if len(live) == 1:
            won[live[0]] = sum(paid.values())
        else:
            showdown = {p: list(hole[p]) for p in live}
            val = {p: evaluate(hole[p] + board) for p in live}
            prev = 0
            for lvl in sorted({paid[p] for p in live}):
                pot = sum(min(paid[q], lvl) - min(paid[q], prev) for q in order)
                elig = [p for p in live if paid[p] >= lvl]
                top = max(val[p] for p in elig)
                winners = [p for p in elig if val[p] == top]
                for i, p in enumerate(winners):
                    won[p] += pot // len(winners) + (1 if i < pot % len(winners) else 0)
                prev = lvl
            extra = sum(paid.values()) - sum(won.values())
            if extra:
                won[max(live, key=lambda p: paid[p])] += extra
        for p in order:
            end = getattr(self.bots[p], "end_hand", None)
            if end:
                if getattr(end, "__func__", end).__code__.co_argcount >= 4:
                    end(list(history), showdown, list(board))
                else:
                    end(list(history), showdown)
        result = {p: won[p] - paid[p] for p in order}
        self.fair = result
        known = BOARD_AT[history[-1].street]
        if showdown and known < 5:
            self.fair = self.expected(order, live, hole, board[:known], paid, self.hand_no)
        for p in order:
            self.fair_log[p].append(self.fair[p])
        return result

    def expected(self, order, live, hole, board, paid, seed):
        # with no betting left, replace the dealt run-out by the average over every run-out
        dead = set(board)
        for p in order:
            dead.update(hole[p])
        deck = [c for c in range(52) if c not in dead]
        need = 5 - len(board)
        if need <= 2:
            runs = list(combinations(deck, need))
        else:
            rng = random.Random(seed * 7919 + 13)
            runs = [rng.sample(deck, need) for _ in range(400)]
        levels = sorted({paid[p] for p in live})
        pots = []
        prev = 0
        for lvl in levels:
            pots.append((sum(min(paid[q], lvl) - min(paid[q], prev) for q in order),
                         [p for p in live if paid[p] >= lvl]))
            prev = lvl
        got = {p: 0.0 for p in order}
        for run in runs:
            full = board + list(run)
            val = {p: evaluate(hole[p] + full) for p in live}
            for pot, elig in pots:
                top = max(val[p] for p in elig)
                winners = [p for p in elig if val[p] == top]
                for p in winners:
                    got[p] += pot / len(winners)
        n = len(runs)
        return {p: got[p] / n - paid[p] for p in order}
