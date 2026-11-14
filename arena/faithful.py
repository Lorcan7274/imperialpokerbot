import json
import random

from pokerbot.cards import RANKS, SUITS, evaluate

STREETS = ("preflop", "flop", "turn", "river")
HAND_NAMES = ("High Card", "Pair", "Two Pair", "Three of a Kind", "Straight", "Flush",
              "Full House", "Four of a Kind", "Straight Flush")
RAISE_WORDS = ("raise", "bet", "all_in", "allin")


def card(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def cap_of(betting, raise_cap):
    cap = int(raise_cap or 0)
    return 4 if betting == "fixed_limit" and not cap else cap


class Table:
    """Organiser-format table: same state dict, action normalisation, history and refunds."""

    def __init__(self, players, hands=1000, betting="no_limit", raise_cap=0, seed=None,
                 stack=2000, sb=10, bb=20, wire=True, on_state=None):
        self.players = players
        self.n = len(players)
        self.hands = hands
        self.betting = betting
        self.cap = cap_of(betting, raise_cap)
        self.rng = random.Random(seed)
        self.stack0, self.sb, self.bb = stack, sb, bb
        self.wire = wire
        self.on_state = on_state
        self.stacks = [stack] * self.n
        self.max_history = 0

    def info(self, seat):
        return {"seat": seat, "num_players": self.n, "format": "fixed_hands", "hands": self.hands,
                "starting_stack": self.stack0, "stacks_reset_each_hand": True,
                "small_blind": self.sb, "big_blind": self.bb, "betting": self.betting,
                "raise_cap": self.cap or None}

    def send(self, obj):
        return json.loads(json.dumps(obj)) if self.wire else obj

    def play(self):
        for seat, p in enumerate(self.players):
            p.start_table(seat, self.send(self.info(seat)))
        chips = [0] * self.n
        button = self.rng.randrange(self.n)
        for hand_no in range(1, self.hands + 1):
            self.stacks = [self.stack0] * self.n
            button = (button + 1) % self.n
            self.hand(hand_no, button)
            assert sum(self.stacks) == self.stack0 * self.n, (hand_no, self.stacks)
            for i in range(self.n):
                chips[i] += self.stacks[i] - self.stack0
        return chips

    def after(self, seat):
        for k in range(1, self.n + 1):
            s = (seat + k) % self.n
            if self.stacks[s] > 0:
                return s
        return seat

    def hand(self, hand_no, button):
        n, stacks = self.n, self.stacks
        deck = list(range(52))
        self.rng.shuffle(deck)
        hole = [[deck.pop(), deck.pop()] for _ in range(n)]
        board = []
        folded = [False] * n
        contrib = [0] * n
        history = []
        t = {"bets": [0] * n}

        def put(i, amt):
            amt = min(amt, stacks[i])
            stacks[i] -= amt
            t["bets"][i] += amt
            contrib[i] += amt
            return amt

        sb_seat = button if n == 2 else self.after(button)
        bb_seat = self.after(sb_seat)
        put(sb_seat, self.sb)
        put(bb_seat, self.bb)
        history.append({"seat": sb_seat, "street": "preflop", "action": "small_blind",
                        "amount": t["bets"][sb_seat]})
        history.append({"seat": bb_seat, "street": "preflop", "action": "big_blind",
                        "amount": t["bets"][bb_seat]})

        for si, street in enumerate(STREETS):
            if si == 1:
                board += [deck.pop(), deck.pop(), deck.pop()]
            elif si > 1:
                board.append(deck.pop())
            if si:
                t["bets"] = [0] * n
            bets = t["bets"]
            live = [i for i in range(n) if not folded[i]]
            actors = [i for i in live if stacks[i] > 0]
            if len(live) > 1 and (len(actors) > 1 or any(bets[i] < max(bets) for i in actors)):
                first = self.after(bb_seat) if si == 0 else self.after(button)
                self.round(street, first, hole, board, bets, contrib, folded, history,
                           hand_no, button, put)
            order = sorted(range(n), key=lambda i: -bets[i])
            top, second = order[0], order[1]
            if bets[top] > bets[second]:
                refund = bets[top] - bets[second]
                stacks[top] += refund
                contrib[top] -= refund
                bets[top] -= refund
            if sum(1 for f in folded if not f) == 1:
                break

        live = [i for i in range(n) if not folded[i]]
        winners = []
        shown = {}
        if len(live) == 1:
            pot = sum(contrib)
            stacks[live[0]] += pot
            winners.append({"seat": live[0], "amount": pot, "hand": None})
        else:
            score = {i: evaluate(hole[i] + board) for i in live}
            shown = {str(i): [card(c) for c in hole[i]] for i in live}
            won = [0] * n
            prev = 0
            for lvl in sorted({c for c in contrib if c > 0}):
                portion = sum(min(c, lvl) - min(c, prev) for c in contrib)
                elig = [i for i in live if contrib[i] >= lvl] or live
                best = max(score[i] for i in elig)
                ws = sorted((i for i in elig if score[i] == best), key=lambda i: (i - button - 1) % n)
                share, odd = divmod(portion, len(ws))
                for k, i in enumerate(ws):
                    won[i] += share + (1 if k < odd else 0)
                prev = lvl
            for i in range(n):
                if won[i]:
                    stacks[i] += won[i]
                    winners.append({"seat": i, "amount": won[i], "hand": HAND_NAMES[score[i] >> 20]})
        summary = {"type": "hand_end", "hand_number": hand_no, "board": [card(c) for c in board],
                   "shown": shown, "winners": winners, "stacks": list(stacks), "history": history}
        self.max_history = max(self.max_history, len(history))
        wire = self.send(summary)
        for p in self.players:
            p.hand_end(wire)

    def round(self, street, first, hole, board, bets, contrib, folded, history, hand_no, button, put):
        n, stacks = self.n, self.stacks
        current = max(bets)
        fixed = self.betting == "fixed_limit"
        min_inc = 2 * self.bb if fixed and street in ("turn", "river") else self.bb
        raises = 0
        pending = {i for i in range(n) if not folded[i] and stacks[i] > 0}
        may_raise = {i: True for i in pending}
        seat = first
        guard = 0
        while pending and guard < 10000:
            guard += 1
            if sum(1 for f in folded if not f) <= 1:
                return
            if seat not in pending:
                seat = (seat + 1) % n
                continue
            i = seat
            to_call = min(current - bets[i], stacks[i])
            others = any(not folded[j] and stacks[j] > 0 for j in range(n) if j != i)
            stack_to = bets[i] + stacks[i]
            if fixed:
                max_to = min(current + min_inc, stack_to)
            elif self.betting == "pot_limit":
                max_to = min(current + sum(contrib) + to_call, stack_to)
            else:
                max_to = stack_to
            can_raise = (may_raise.get(i, True) and max_to > current and others
                         and not (self.cap and raises >= self.cap))
            min_to = min(current + min_inc, max_to)
            state = {
                "type": "act", "hand_number": hand_no, "street": street, "seat": i, "button": button,
                "hole_cards": [card(c) for c in hole[i]], "board": [card(c) for c in board],
                "small_blind": self.sb, "big_blind": self.bb, "blind_level": 0,
                "pot": sum(contrib), "stacks": list(stacks), "bets": list(bets),
                "folded": list(folded), "to_call": to_call,
                "min_raise_to": min_to if can_raise else None,
                "max_raise_to": max_to if can_raise else None,
                "legal_actions": (["fold", "call"] if to_call > 0 else ["check"])
                + (["raise"] if can_raise else []),
                "betting": self.betting, "raise_cap": self.cap or None,
                "raises_this_street": raises, "history": list(history),
            }
            wire = self.send(state)
            decision = self.players[i].act(wire) or {}
            if self.on_state:
                self.on_state(i, wire, decision)
            action = str(decision.get("action", "")).lower()
            amount = decision.get("amount")
            if action in RAISE_WORDS and can_raise:
                if action in ("all_in", "allin"):
                    amount = max_to
                try:
                    target = int(amount)
                except (TypeError, ValueError, OverflowError):
                    target = min_to
                target = max(min_to, min(target, max_to))
                put(i, target - bets[i])
                size = target - current
                full = size >= min_inc
                if full and not fixed:
                    min_inc = size
                current = target
                raises += 1
                pending = {j for j in range(n) if j != i and not folded[j] and stacks[j] > 0}
                for j in pending:
                    if full:
                        may_raise[j] = True
                    else:
                        may_raise.setdefault(j, True)
                act, amt = "raise", target
            elif action in ("call",) + RAISE_WORDS and to_call > 0:
                put(i, to_call)
                act, amt = "call", to_call
            elif to_call == 0:
                act, amt = "check", 0
            else:
                folded[i] = True
                act, amt = "fold", 0
            pending.discard(i)
            may_raise[i] = False
            history.append({"seat": i, "street": street, "action": act, "amount": amt})
            seat = (seat + 1) % n


def normalise(result):
    if isinstance(result, dict):
        return {"action": result.get("action"), "amount": result.get("amount")}
    if isinstance(result, (tuple, list)):
        return {"action": result[0] if result else None,
                "amount": result[1] if len(result) > 1 else None}
    if isinstance(result, str):
        return {"action": result, "amount": None}
    return {"action": None, "amount": None}


class Seat:
    """In-process seat: errors become no answer, as the process harness does."""

    def __init__(self, make):
        self.make = make
        self.agent = None
        self.errors = 0

    def start_table(self, seat, info):
        self.agent = self.make()
        if hasattr(self.agent, "on_table_start"):
            self.agent.on_table_start(info)

    def act(self, state):
        try:
            return normalise(self.agent.act(state))
        except Exception:
            self.errors += 1
            return None

    def hand_end(self, summary):
        if hasattr(self.agent, "on_hand_end"):
            try:
                self.agent.on_hand_end(summary)
            except Exception:
                pass
