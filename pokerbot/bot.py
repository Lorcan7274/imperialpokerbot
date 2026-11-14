import random
from time import perf_counter

from .cards import evaluate
from .clone_table import CLONE1, CLONE2
from .model import Model, classify, jam_kind, line, tell_key
from .preflop import class_name, percentile
from .ranges import Sample, keep_top, made, narrow, river_equity, sim_equity, simulate, strong_hand
from .ranges import runout_equity
from .state import Action
from .topx_table import TOPX, TOPX_GRID

NOISE = {1: 0.30, 2: 0.22, 3: 0.14}
BOARD_LEN = {1: 3, 2: 4, 3: 5}
MAX_EVENTS = 8


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


STRONG_ALL = [(a, b) for a in range(52) for b in range(a)
              if a >> 2 == b >> 2 or a >> 2 >= 11 or b >> 2 >= 11]


def strong_river_equity(hole, board):
    board = list(board)
    dead = set(hole) | set(board)
    hv = evaluate(list(hole) + board)
    won = tot = 0.0
    for x, y in STRONG_ALL:
        if x in dead or y in dead:
            continue
        v = evaluate([x, y] + board)
        tot += 1.0
        if hv > v:
            won += 1.0
        elif hv == v:
            won += 0.5
    return won / tot if tot else 0.5


TELL_PRIOR = ({"x": 0.09, "r": 0.72, 0: 0.22, 1: 0.4, 2: 0.22, 3: 0.58, 4: 0.7, 5: 0.7},
              {"x": 0.14, "r": 0.88, 0: 0.38, 1: 0.55, 2: 0.28, 3: 0.7, 4: 0.82, 5: 0.9})


def topx(name, x):
    row = TOPX[name]
    if x <= TOPX_GRID[0]:
        return row[0]
    for k in range(1, len(TOPX_GRID)):
        if x <= TOPX_GRID[k]:
            lo, hi = TOPX_GRID[k - 1], TOPX_GRID[k]
            return row[k - 1] + (row[k] - row[k - 1]) * (x - lo) / (hi - lo)
    return row[-1]


def learn_tells(tell, events, shown, board, hero):
    for e in events:
        hole = shown.get(e.player)
        key = tell_key(e)
        if key is None or hole is None or e.player == hero or len(hole) != 2:
            continue
        cards = board[:BOARD_LEN[e.street]]
        if len(cards) < BOARD_LEN[e.street]:
            continue
        t = tell.setdefault((e.player,) + key, [0, 0])
        t[0] += 1
        t[1] += strong_hand(hole, cards)


def floor_for(f, noise):
    return noise * f / (noise * f + 1 - noise)


class Bot:
    LIGHT3 = True
    POSW = False
    ANY3 = 0.8
    LIGHT_OBS = 0
    LIGHT_RISK = 1.0
    PLAN = True
    MILK = True
    KEEP = True
    OPEN_BB = 3.5
    TELLS = True

    def __init__(self, seed=None, trials=90, strict=False, samples=160):
        self.rng = random.Random(seed)
        self.trials = trials
        self.samples = samples
        self.scale = 1.0
        self.deadline = None
        self.strict = strict
        self.model = Model()
        self._sample = None
        self._hand = None
        self._hist = []
        self._hero = None
        self._bb = 20
        self.seats = 0

    def decide(self, s):
        if s.hand_id != self._hand:
            self._commit()
            self._hand = s.hand_id
            self._sample = None
        self._hist = list(s.history)
        self._hero = s.hero
        self._bb = s.big_blind
        self.seats = len(s.players)
        try:
            a = self._postflop(s) if s.board else self._preflop(s)
        except Exception:
            if self.strict:
                raise
            try:
                a = self._quick(s)
            except Exception:
                a = Action("fold")
        return self._legal(s, a)

    def end_hand(self, history=None, showdown=None, board=None):
        if history:
            self._hist = list(history)
        self._commit(showdown, board)

    def _commit(self, shown=None, board=None):
        if self._hist:
            events = classify(self._hist, self._bb, n=self.seats)
            self.model.observe(events, self._hero, shown)
            if shown and board and self.TELLS:
                self._learn(events, shown, board)
        self._hist = []

    def _learn(self, events, shown, board):
        learn_tells(self.model.tell, events, shown, board, self._hero)

    def _late(self):
        return self.deadline is not None and perf_counter() > self.deadline

    def _quick(self, s):
        c = s.to_call
        if c <= 0:
            return Action("check")
        odds = c / (s.pot + c)
        many = len(s.active) > 2
        if not s.board:
            p = percentile(*s.hole)
            ok = p < 0.03 or (p < 0.08 and odds < 0.42) or (p < 0.2 and odds < 0.25 and not many)
            return Action("call") if ok else Action("fold")
        board = list(s.board)
        ranks = [x >> 2 for x in board]
        v = evaluate(list(s.hole) + board)
        cat = v >> 20
        if len(board) == 5:
            base = evaluate(board) >> 20
        else:
            cnt = sorted((ranks.count(r) for r in set(ranks)), reverse=True)
            base = (3 if cnt[0] >= 3 else 2 if cnt[0] == 2 and len(cnt) > 1 and cnt[1] == 2
                    else 1 if cnt[0] == 2 else 0)
        gain = cat - base
        if gain >= 2 or (gain == 1 and cat >= 3):
            return Action("call")
        if gain == 1:
            mine = v >> 16 & 15
            if cat == 2 and ranks.count(mine) >= 2:
                mine = v >> 12 & 15
            limit = (0.25 if many else 0.34) if mine >= max(ranks) else (0.15 if many else 0.2)
        else:
            limit = 0.07 if many else 0.1
        return Action("call") if odds <= limit else Action("fold")

    def _trials(self, opponents, heavy=False):
        # a decision for a large part of the stack is rare and worth a steadier estimate
        return max(16, int(self.trials * self.scale * min(1.0, 3.0 / (1 + opponents)) * (2 if heavy else 1)))

    def _legal(self, s, a):
        can_raise = s.max_raise_to > s.my_bet + s.to_call
        if a.kind == "raise" and can_raise:
            amt = int(round(a.amount))
            return Action("raise", int(clamp(amt, s.min_raise_to, s.max_raise_to)))
        if s.to_call <= 0:
            return Action("check")
        return Action("call") if a.kind in ("call", "raise") else Action("fold")

    def _raise(self, s, to):
        if to >= 0.4 * (s.my_stack + s.my_bet):
            to = s.max_raise_to
        return Action("raise", to)

    def _in_position(self, s):
        live = [p for p in s.players if p in s.active]
        return bool(live) and live[-1] == s.hero

    def _roles(self, s, events):
        roles = {}
        for v in s.active:
            if v != s.hero and self.model.is_clone(v):
                role = None
                for e in events:
                    if e.player == v:
                        if e.act == "raise" or (e.act == "call" and e.big):
                            role = "strong"
                        elif role is None and e.act in ("check", "call"):
                            role = "weak"
                roles[v] = role
        return roles

    def _update(self, w, e, s, n, sample):
        f = lambda act: self.model.freq(e.player, e.sit, act, n)
        if e.street == 0:
            order = sample.pre_order
            if e.jam:
                jf = self.model.freq(e.player, e.sit, "jam", n)
                narrow(w, order, 0, jf, 1, 0.15 * jf, 0.13)
            elif e.act == "raise":
                fr = f("raise")
                # shown hands put only one re-raise in twelve outside the range its frequency implies
                narrow(w, order, 0, fr, 1, 0.04 if e.sit[:8] == "unopened" else min(0.04, 0.1 * fr))
            elif e.act == "call":
                fr = f("raise")
                narrow(w, order, fr * 0.6, fr + f("call"), 0.35, 0.04)
            return
        _, order = sample.board(s.board[:BOARD_LEN[e.street]])
        noise = NOISE[e.street]
        if e.sit[:8] == "p_no_bet":
            fr = f("raise")
            if e.act == "raise":
                narrow(w, order, 0, fr, 1, floor_for(fr, noise))
            elif e.act == "check":
                narrow(w, order, fr, 1, 0.35, 1)
        elif e.act == "raise":
            fr = f("raise")
            narrow(w, order, 0, fr, 1, floor_for(fr, noise * 0.6))
        elif e.act == "call":
            narrow(w, order, f("raise"), 1 - f("fold"), 0.5, 0.05)
        key = tell_key(e)
        if key and self.TELLS:
            t = self.model.tell.get((e.player,) + key, (0, 0))
            flags = sample.flags(s.board[:BOARD_LEN[e.street]])
            tot = hit = 0.0
            for x, k in zip(w, flags):
                tot += x
                if k:
                    hit += x
            if 0.0 < hit < tot:
                share = hit / tot
                q = clamp((t[1] + 2 * TELL_PRIOR[key[0]][key[1]]) / (t[0] + 2), 0.02, 0.98)
                up, down = q / share, (1 - q) / (1 - share)
                for i, k in enumerate(flags):
                    w[i] *= up if k else down

    def _ranges(self, s, events, roles):
        if self._sample is None:
            self._sample = Sample(s.hole, self.rng, max(70, int(self.samples * self.scale)))
        sample = self._sample
        n = len(s.players)
        vals = sample.board(s.board)[0] if s.board else None
        seen = {}
        for e in events:
            seen.setdefault(e.player, []).append(e)
        out = {}
        for v in s.active:
            if v == s.hero:
                continue
            role = roles.get(v)
            if role == "strong":
                w = [x if k else 0.0 for x, k in zip(sample.base, sample.strong)]
            elif role == "weak":
                w = [0.0 if k else x for x, k in zip(sample.base, sample.strong)]
            else:
                # hands that share a card with the board come out first, so no share of the range is spent on them
                w = [0.0 if vals[i] < 0 else x for i, x in enumerate(sample.base)] if vals else list(sample.base)
                mine = seen.get(v, ())
                if len(mine) > MAX_EVENTS:
                    mine = mine[:3] + mine[3 - MAX_EVENTS:]
                if not self._late():
                    for e in mine:
                        self._update(w, e, s, n, sample)
            if vals:
                w = [0.0 if vals[i] < 0 else x for i, x in enumerate(w)]
            out[v] = w
        return out

    def _river_plan(self, s, w):
        # value of calling a raising starter bot down to the river, where it pays off a shove with its whole range
        bb = s.big_blind
        board = list(s.board)
        dead = set(s.hole) | set(board)
        deck = [x for x in range(52) if x not in dead]
        pot = s.pot + s.to_call
        stack = s.my_stack - s.to_call
        cost = s.to_call
        if len(board) == 4:
            suits = [0] * 4
            for x in board:
                suits[x & 3] += 1
            groups = {}
            for x in deck:
                key = (x >> 2, x & 3 if suits[x & 3] >= 2 else -1)
                if key in groups:
                    groups[key][1] += 1
                else:
                    groups[key] = [[x], 1]
            runs = [g[0] for g in groups.values()]
            counts = [g[1] for g in groups.values()]
        else:
            k = max(16, int(30 * self.scale))
            runs = [self.rng.sample(deck, 2) for _ in range(k)]
            counts = [1] * k
            turn = min(stack, bb + pot // 2)
            pot += 2 * turn
            stack -= turn
            cost += turn
        bet = min(stack, bb + pot // 2)
        eqs = runout_equity(s.hole, board, runs, self._sample, w, self.deadline)
        if len(eqs) < 6:
            return None
        total = 0.0
        for e, k in zip(eqs, counts):
            total += k * max(0.0, e * (pot + 2 * bet) - bet, e * (pot + 2 * stack) - stack)
        return total / sum(counts[:len(eqs)]) - cost

    def _preflop_clone(self, s, events, raises, villains, clones, n):
        bb = s.big_blind
        name = class_name(*s.hole)
        e1 = CLONE1[name]
        stack = s.my_stack + s.my_bet
        hot = {e.player for e in events
               if e.player in clones and (e.act == "raise" or (e.act == "call" and e.big))}
        hot = [v for v in hot if v in s.active]
        if hot:
            if any(e.player not in clones and e.player != s.hero for e in raises):
                return None
            if len(hot) >= 2:
                return Action("raise", s.max_raise_to) if CLONE2[name] >= 0.38 else Action("fold")
            c = s.to_call
            if (e1 >= 0.62 or c <= 0.07 * stack or (e1 >= 0.45 and c <= 0.15 * stack)
                    or (e1 >= 0.52 and c <= 0.3 * stack)):
                return Action("call")
            return Action("fold")
        if raises:
            return None
        acted = {e.player for e in events}
        behind = [v for v in villains if v not in acted]
        limpers = [e.player for e in events if e.act == "call"]
        if not any(v in clones for v in behind + limpers):
            return None
        ok = 1.0
        for v in behind:
            ok *= 0.664 if v in clones else self.model.gives_up(v, n)
        for v in limpers:
            if v not in clones:
                ok *= self.model.gives_up(v, n)
        # a starter bot without a raising hand calls up to 40 more, then pays 40 on the flop and the turn
        bets = {r.player: r.to for r in s.history}
        room = [bets.get(v, 0) + 2 * bb for v in limpers + behind if v in clones]
        to = s.my_bet + s.to_call + 2 * bb
        low = max(min(room), s.min_raise_to)
        pay = lambda x: s.pot + sum(x - y + 6 * bb for y in room if y >= x)
        # real players attack a small open, so it is used only while those behind are likely to fold
        if (self.KEEP and low < to and all(v in clones for v in limpers)
                and ok * pay(low) > (1 - ok) * low):
            return Action("raise", low)
        if e1 >= 0.36 or ok * pay(to) > (1 - ok) * to:
            return Action("raise", to)
        return Action("check") if s.to_call <= 0 else Action("fold")

    def _preflop(self, s):
        bb = s.big_blind
        n = len(s.players)
        allev = classify(s.history, bb, n=n)
        events = [e for e in allev if e.street == 0]
        raises = [e for e in events if e.act == "raise"]
        p = percentile(*s.hole)
        villains = [v for v in s.active if v != s.hero]
        level = s.my_bet + s.to_call
        freq = self.model.freq
        rnd = self.rng.random

        clones = {v for v in villains if self.model.is_clone(v)}
        if clones:
            a = self._preflop_clone(s, events, raises, villains, clones, n)
            if a is not None:
                return a

        if raises and (s.to_call >= 0.3 * s.my_stack or raises[-1].jam or level >= 25 * bb):
            name = class_name(*s.hole)
            into = [v for v in villains
                    if any(e.player == v and e.act in ("raise", "call") for e in events)]
            if len(into) == 1 and into[0] not in clones:
                v = into[0]
                x = 1.0
                jam = None
                for e in events:
                    if e.player == v and e.act == "raise":
                        x *= freq(v, e.sit, "jam" if e.jam else "raise", n)
                        if e.jam:
                            jam = jam_kind(e.sit)
                    elif e.player == v and e.act == "call":
                        x *= min(1.0, freq(v, e.sit, "raise", n) + freq(v, e.sit, "call", n))
                if jam:
                    # shown all-in hands in this field run about twice as wide as the frequency suggests;
                    # the same kind of shove counts in full, the player's other shoves at half weight
                    seen = shown = 0.0
                    for kind in "o34":
                        t = self.model.jamx.get((v, kind))
                        if t:
                            share = 1.0 if kind == jam else 0.5
                            seen += share * t[0]
                            shown += share * t[1]
                    x = (2 * x + 2 * (shown + 0.06)) / (4 + seen)
                eq = topx(name, x)
                if name in ("AA", "KK"):
                    eq = max(eq, 0.5)
            else:
                # several players all-in show premium hands, and a short simulation can flatter a weak one
                if len(into) > 1 and s.to_call >= 0.4 * s.my_stack and p > (
                        0.25 if any(v in clones for v in into) else 0.12):
                    return Action("fold")
                roles = self._roles(s, events)
                ranges = self._ranges(s, events, roles)
                against = [ranges[v] for v in into] or list(ranges.values())
                sim = simulate(s.hole, [], self._sample, against, self._trials(len(against), True),
                               self.rng, self.deadline)
                if not sim or (len(sim) < 12 and self._late() and not any(roles.values())):
                    return self._quick(s)
                eq = sim_equity(sim)
            if eq > 0.62:
                return Action("raise", s.max_raise_to)
            # a call that leaves chips behind has to be played out of the hand's weak spots after the flop
            if s.to_call < 0.8 * s.my_stack:
                eq *= 0.8
            if eq * (s.pot + s.to_call) - s.to_call > 0.04 * s.pot:
                return Action("call")
            return Action("fold")

        if not raises:
            limpers = sum(1 for e in events if e.act == "call")
            if n == 2:
                v = villains[0]
                if s.to_call > 0:
                    fold_f = freq(v, "vs_raise", "fold", 2)
                    width, size = 0.82, 2.5
                    if fold_f > 0.6:
                        width = 1.0
                    elif fold_f < 0.25:
                        width, size = 0.65, 3.0
                    if freq(v, "vs_raise", "raise", 2) > 0.3:
                        width = min(width, 0.55)
                    return self._raise(s, size * bb) if p < width else Action("fold")
                return self._raise(s, 3.5 * bb) if p < 0.40 else Action("check")
            acted = {e.player for e in events}
            behind = [v for v in villains if v not in acted]
            pct = {0: 0.22, 1: 0.45, 2: 0.42, 3: 0.26, 4: 0.19, 5: 0.15, 6: 0.12}.get(len(behind), 0.10)
            loose = sum(1 - freq(v, "vs_raise", "fold", n) for v in villains) / max(1, len(villains))
            steal = 1.0
            for v in behind:
                steal *= self.model.gives_up(v, n)
            if behind and steal > 0.6:
                pct = max(pct, min(1.0, 2.2 * steal - 0.7))
            else:
                pct *= clamp(1.3 - 1.0 * loose, 0.55, 1.1)
            if limpers:
                pct *= 0.8
            size = self.OPEN_BB + limpers + 7 * max(0.0, loose - 0.3)
            if p < pct:
                return self._raise(s, min(size, 9) * bb)
            if s.to_call <= 0:
                return Action("check")
            if p < 0.35 and s.to_call <= bb and (limpers or s.my_bet > 0):
                return Action("call")
            return Action("fold")

        r = raises[-1].player
        ip = self._in_position(s)
        if len(raises) == 1:
            base = 0.45 if n == 2 else 0.18
            width = clamp((freq(r, raises[0].sit, "raise", n) if self.POSW else self.model.opens(r, n)) / base,
                          0.5, 2.2)
            sizeadj = clamp((2.5 * bb / level) ** 0.5, 0.45, 1.2)
            to = level * (3.2 if ip else 3.8)
            if n == 2:
                bluff = 0.45 < p < 0.52 and freq(r, "vs_3bet", "fold", 2) > 0.5 and rnd() < 0.5
                if p < 0.08 * width or bluff:
                    return self._raise(s, to)
                if p < min(0.92, 0.62 * width * sizeadj):
                    return Action("call")
                return Action("fold")
            # an unusually large open is a narrower range, so fewer hands re-raise it for value
            if p < 0.045 * width * min(1.0, 3.5 * bb / level):
                return self._raise(s, to)
            limit = (0.24 if s.my_bet >= bb else 0.11) * width * sizeadj
            # in the real rounds calls behind other callers lost, and so did loose calls of early-seat opens
            if any(e.act == "call" and e.player not in clones for e in events):
                limit *= 0.6
            if raises[0].sit == "unopened":
                limit = min(limit, 0.28)
            if p < limit:
                return Action("call")
            limped = {e.player for e in events if e.act == "call" and e.player in clones}
            if self.LIGHT3 and self.model.opp[(r, "re_raised")] >= self.LIGHT_OBS and all(
                    e.act == "fold" or e.player == r or e.player in limped for e in events):
                sure = ff = freq(r, "re_raised", "fold", n)
                for v in villains:
                    # a starter bot that limped folds to any re-raise
                    if v != r and v not in limped:
                        ff *= 0.664 if v in clones else freq(v, "cold3", "fold", n)
                # in real rounds these paid only from the big blind or against an opener seen folding 85% or more,
                # and never against a large open, which is a stronger range
                if (p < (0.6 if ff < self.ANY3 else 1.0) and level <= 4.5 * bb
                        and (sure >= 0.85 or s.my_bet >= bb)
                        and ff * s.pot > (1 - ff) * self.LIGHT_RISK * (to - s.my_bet) + 0.1 * s.pot):
                    return Action("raise", to)
            return Action("fold")

        if len(raises) == 2:
            f3 = freq(r, "vs_raise", "raise", n)
            invested = any(e.player == s.hero and e.act == "raise" for e in events)
            if raises[0].player == s.hero:
                f3 = max(f3, freq(r, "vs_hero", "raise", n))
            width = clamp(f3 / (0.12 if n == 2 else 0.07), 0.5, 3.0)
            # against someone who re-raises most opens, most of an opening range is ahead
            if p < max(0.03 * width, 0.2 * f3):
                return self._raise(s, 2.3 * level)
            if p < max(((0.30 if n == 2 else 0.14) if invested else 0.05) * width,
                       0.6 * f3 if invested else 0.0):
                return Action("call")
            if invested and self._priced(s, f3):
                return Action("call")
            return Action("fold")

        f4 = freq(r, raises[-1].sit, "raise", n)
        width = clamp(f4 / 0.15, 0.5, 3.0)
        if p < 0.022 * width:
            return Action("raise", s.max_raise_to)
        if p < 0.045 * width:
            return Action("call")
        if s.my_bet > bb and self._priced(s, f4 * (self.model.opens(r, n) if raises[-1].sit == "re_raised" else 1.0)):
            return Action("call")
        return Action("fold")

    def _priced(self, s, x):
        # a small re-raise can offer a price that even a modest hand should take
        odds = s.to_call / (s.pot + s.to_call)
        if odds >= 0.25:
            return False
        if s.hole[0] >> 2 == s.hole[1] >> 2 and s.to_call <= 0.07 * s.my_stack:
            return True
        return 0.7 * topx(class_name(*s.hole), x) > odds + 0.03

    def _guard(self, s, best, fallback):
        if best.kind != "raise":
            return best
        total = 2000 - s.my_stack + best.amount - s.my_bet
        if total < 800:
            return best
        br = [c >> 2 for c in s.board]
        a, b = s.hole[0] >> 2, s.hole[1] >> 2
        top = made(a, b, br, max(br))
        cat = evaluate(list(s.hole) + list(s.board)) >> 20
        two = cat >= 4 or (a == b and a in br) or (a != b and (
            (a in br and b in br) or (a in br and br.count(a) > 1) or (b in br and br.count(b) > 1)))
        if two or (top and total < 1500):
            return best
        return fallback

    def _postflop(self, s):
        n = len(s.players)
        bb = s.big_blind
        ctx = {}
        events = classify(s.history, bb, ctx=ctx, n=n, now=s.street)
        roles = self._roles(s, events)
        st = s.street
        P = float(s.pot)
        c = s.to_call
        # a starter bot that only called pays 40 on the flop and the turn and still folds to 45 on the river
        if (self.MILK and st < 3 and c <= 0 and s.min_raise_to <= s.my_bet + 2 * bb <= s.max_raise_to
                and all(roles.get(v) == "weak" for v in s.active if v != s.hero)):
            return Action("raise", s.my_bet + 2 * bb)
        ranges = self._ranges(s, events, roles)
        sample = self._sample
        rl = list(ranges.values())
        freq = self.model.freq
        vals, order = sample.board(s.board)
        raisers = [v for v in ranges if roles.get(v) == "strong"]
        # starter bots that only called fold to the raiser's bet, so this is a duel with the raiser
        if (self.PLAN and st < 3 and len(raisers) == 1 and s.my_stack > P
                and all(roles.get(v) for v in ranges)):
            if c <= 0:
                return Action("check")
            ev = self._river_plan(s, ranges[raisers[0]])
            if ev is None:
                return self._quick(s)
            return Action("call") if ev > 0 else Action("fold")
        if st == 3:
            hv = evaluate(list(s.hole) + list(s.board))
            eq_with = lambda mults=None: river_equity(hv, vals, rl, mults)
        else:
            sim = simulate(s.hole, s.board, sample, rl, self._trials(len(rl), c >= 0.2 * s.my_stack),
                           self.rng, self.deadline)
            if not sim or (len(sim) < 12 and self._late() and not any(roles.values())):
                return self._quick(s)
            eq_with = lambda mults=None: sim_equity(sim, mults)
        eq = eq_with()
        pure = all(roles.get(v) for v in ranges)
        if st == 3 and len(rl) == 1 and "strong" in roles.values():
            eq = strong_river_equity(s.hole, s.board)
        ip = self._in_position(s)
        can_raise = s.max_raise_to > s.my_bet + c and any(
            s.stacks.get(v, 1) > 0 for v in ranges)
        most = s.max_raise_to - s.my_bet
        barrel = "strong" in roles.values()
        soft = "weak" in roles.values()
        # a starter bot that has raised never folds and bets every street, so the stack goes in on the river
        wait = barrel and st < 3 and s.my_stack > P
        big = barrel or all(roles.get(v) or self.model.sticky(v) for v in ranges)
        tag = {v: line(v, 2 if c > 0 else 1, ctx["agg"], ctx["stuck"], ctx["checked"], ctx["firm"], ctx["bold"])
               for v in ranges}

        # in the real rounds a bet in a re-raised pot folded out half as many hands as in a single-raised one
        pre = sum(1 for e in events if e.street == 0 and e.act == "raise")
        firmer = 1.0 if pre < 2 else (0.55, 0.7, 0.85)[st - 1] if pre == 2 else 0.4

        def response(sit, chips, x, ref):
            phi = 1.0
            mults = []
            exact = True
            # the field folds to a third-pot bet less than half as often as to a two-thirds one
            steep = (x / ref) ** (1.6 if x < ref and sit == "p_vs_bet" else 0.7)
            for v, w in ranges.items():
                role = roles.get(v)
                if role == "strong":
                    ff = 0.0
                elif role == "weak":
                    ff = 1.0 if chips > 2 * bb else 0.0
                else:
                    ff = clamp(freq(v, sit + tag[v], "fold", n) * steep * firmer, 0.02, 0.95)
                    exact = False
                phi *= ff
                mults.append(keep_top(w, order, 1 - ff, 0.02) if 0.0 < ff < 1.0 else None)
            if exact or phi > 0.999:
                return phi, eq
            return phi, eq_with([m or [1.0] * sample.size for m in mults])

        def risk(sit):
            return max(1.0 if roles.get(v) == "strong" else 0.0 if roles.get(v) == "weak"
                       else freq(v, sit + tag[v], "raise", n) for v in ranges)

        if c <= 0:
            real = (1.0 if ip else 0.93) if st == 3 else (0.95 if ip else 0.85)
            best, best_ev = Action("check"), eq * P * real
            if not can_raise or wait:
                return best
            fr = risk("p_vs_bet")
            floor = 2 * bb + 5
            sizes = ([2 * bb, floor] if soft else []) + [max(f * P, floor) for f in (0.33, 0.7, 1.1)]
            thin = len(sizes) - 1
            sizes += [1e9] if barrel else [2.2 * P, 1e9] if big else []
            for k, size in enumerate(sizes):
                if self._late():
                    break
                b = size
                if b >= 0.6 * s.my_stack:
                    b = s.my_stack
                b = clamp(b, s.min_raise_to - s.my_bet, most)
                phi, eqc = response("p_vs_bet", b, b / (P + b), 0.4)
                ev = phi * P + (1 - phi) * (eqc * (P + 2 * b) - b)
                if eqc < 0.8 and b < s.my_stack:
                    ev -= (1 - phi) * fr * b * 0.5
                if ev > best_ev + 0.02 * P:
                    best, best_ev = Action("raise", s.my_bet + b), ev
                if b >= most or (k >= thin and not barrel and (eqc < 0.6 or best.kind == "check")):
                    break
            return best if big else self._guard(s, best, Action("check"))

        if st == 3:
            real = 1.0
        elif barrel:
            real = 0.68 if st == 1 else 0.90
        else:
            real = 0.96 if ip else 0.90
        if c >= s.my_stack or not any(s.stacks.get(v, 1) > 0 for v in ranges):
            real = 1.0
        ev_call = eq * real * (P + c) - c
        best, best_ev = (Action("call"), ev_call) if ev_call > 0 else (Action("fold"), 0.0)
        if can_raise and not wait:
            rr = risk("p_vs_raise")
            for frac in (0.6, 1.0, 1e9) if big else (0.6, 1.0):
                if self._late():
                    break
                a = c + frac * (P + c)
                if a >= 0.6 * s.my_stack:
                    a = s.my_stack
                a = clamp(a, s.min_raise_to - s.my_bet, most)
                phi, eqc = response("p_vs_raise", a - c, (a - c) / (P + a), 0.3)
                ev = phi * P + (1 - phi) * (eqc * (P + 2 * a - c) - a)
                if eqc < 0.8 and a < s.my_stack:
                    ev -= (1 - phi) * rr * a * 0.5
                if ev > best_ev + (0.02 if pure else 0.15) * P:
                    best, best_ev = Action("raise", s.my_bet + a), ev
                if a >= most or (frac >= 1.0 and not barrel and (eqc < 0.6 or best.kind != "raise")):
                    break
        if big:
            return best
        return self._guard(s, best, Action("call") if ev_call > 0 else Action("fold"))
