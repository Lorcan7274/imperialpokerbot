import random
from time import perf_counter

from .cards import evaluate
from .clone_table import CLONE1, CLONE2
from .model import Model, classify, line
from .preflop import class_name, percentile
from .ranges import Sample, keep_top, narrow, river_equity, sim_equity, simulate
from .state import Action

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


def floor_for(f, noise):
    return noise * f / (noise * f + 1 - noise)


class Bot:
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

    def decide(self, s):
        if s.hand_id != self._hand:
            self._commit()
            self._hand = s.hand_id
            self._sample = None
        self._hist = list(s.history)
        self._hero = s.hero
        self._bb = s.big_blind
        try:
            a = self._postflop(s) if s.board else self._preflop(s)
        except Exception:
            if self.strict:
                raise
            a = Action("fold")
        return self._legal(s, a)

    def end_hand(self, history=None, showdown=None):
        if history:
            self._hist = list(history)
        self._commit(showdown)

    def _commit(self, shown=None):
        if self._hist:
            self.model.observe(classify(self._hist, self._bb), self._hero, shown)
        self._hist = []

    def _late(self):
        return self.deadline is not None and perf_counter() > self.deadline

    def _trials(self, opponents):
        return max(16, int(self.trials * self.scale * min(1.0, 3.0 / (1 + opponents))))

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
                narrow(w, order, 0, self.model.freq(e.player, "jam", "jam", n), 1, 0.02)
            elif e.act == "raise":
                narrow(w, order, 0, f("raise"), 1, 0.04)
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
                w = list(sample.base)
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
            if (e1 >= 0.62 or (e1 >= 0.36 and c <= 0.07 * stack) or (e1 >= 0.45 and c <= 0.15 * stack)
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
            ok *= 0.664 if v in clones else self.model.freq(v, "vs_raise", "fold", n)
        for v in limpers:
            if v not in clones:
                ok *= self.model.freq(v, "vs_raise", "fold", n)
        level = s.my_bet + s.to_call
        to = level + 2 * bb
        gain = s.pot + 2 * bb * sum(1 for v in limpers if v in clones)
        if e1 >= 0.36 or ok * gain > (1 - ok) * to:
            return Action("raise", to)
        return Action("check") if s.to_call <= 0 else Action("fold")

    def _preflop(self, s):
        bb = s.big_blind
        n = len(s.players)
        allev = classify(s.history, bb)
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
            ranges = self._ranges(s, events, self._roles(s, events))
            committed = [w for v, w in ranges.items()
                         if any(e.player == v and e.act in ("raise", "call") for e in events)]
            against = committed or list(ranges.values())
            sim = simulate(s.hole, [], self._sample, against, self._trials(len(against)),
                           self.rng, self.deadline)
            if not sim:
                return Action("fold")
            eq = sim_equity(sim)
            if eq * (s.pot + s.to_call) - s.to_call > 0.04 * s.pot:
                if eq > 0.62:
                    return Action("raise", s.max_raise_to)
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
                steal *= freq(v, "vs_raise", "fold", n)
            if behind and steal > 0.6:
                pct = max(pct, min(1.0, 2.2 * steal - 0.7))
            else:
                pct *= clamp(1.3 - 1.0 * loose, 0.55, 1.1)
            if limpers:
                pct *= 0.8
            size = 2.5 + limpers + 7 * max(0.0, loose - 0.3)
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
            width = clamp(freq(r, "unopened", "raise", n) / base, 0.5, 2.2)
            sizeadj = clamp((2.5 * bb / level) ** 0.5, 0.45, 1.2)
            to = level * (3.2 if ip else 3.8)
            if n == 2:
                bluff = 0.45 < p < 0.52 and freq(r, "vs_3bet", "fold", 2) > 0.5 and rnd() < 0.5
                if p < 0.08 * width or bluff:
                    return self._raise(s, to)
                if p < min(0.92, 0.62 * width * sizeadj):
                    return Action("call")
                return Action("fold")
            if p < 0.045 * width:
                return self._raise(s, to)
            if p < (0.24 if s.my_bet >= bb else 0.11) * width * sizeadj:
                return Action("call")
            return Action("fold")

        if len(raises) == 2:
            width = clamp(freq(r, "vs_raise", "raise", n) / (0.12 if n == 2 else 0.07), 0.5, 3.0)
            invested = any(e.player == s.hero and e.act == "raise" for e in events)
            if p < 0.03 * width:
                return self._raise(s, 2.3 * level)
            if p < ((0.30 if n == 2 else 0.14) if invested else 0.05) * width:
                return Action("call")
            return Action("fold")

        width = clamp(freq(r, "vs_3bet", "raise", n) / 0.15, 0.5, 3.0)
        if p < 0.022 * width:
            return Action("raise", s.max_raise_to)
        if p < 0.045 * width:
            return Action("call")
        return Action("fold")

    def _postflop(self, s):
        n = len(s.players)
        bb = s.big_blind
        ctx = {}
        events = classify(s.history, bb, ctx=ctx)
        roles = self._roles(s, events)
        ranges = self._ranges(s, events, roles)
        sample = self._sample
        rl = list(ranges.values())
        st = s.street
        P = float(s.pot)
        c = s.to_call
        freq = self.model.freq
        vals, order = sample.board(s.board)
        if st == 3:
            hv = evaluate(list(s.hole) + list(s.board))
            eq_with = lambda mults=None: river_equity(hv, vals, rl, mults)
        else:
            sim = simulate(s.hole, s.board, sample, rl, self._trials(len(rl)), self.rng,
                           self.deadline)
            if not sim:
                return Action("fold")
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
        tag = {v: line(v, 1, ctx["agg"], ctx["stuck"], ctx["checked"]) for v in ranges}

        def response(sit, chips, x, ref):
            phi = 1.0
            mults = []
            exact = True
            for v, w in ranges.items():
                role = roles.get(v)
                if role == "strong":
                    ff = 0.0
                elif role == "weak":
                    ff = 1.0 if chips > 2 * bb else 0.0
                else:
                    ff = clamp(freq(v, sit + tag[v], "fold", n) * (x / ref) ** 0.7, 0.02, 0.95)
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
            sizes += [1e9] if barrel else [2.2 * P, 1e9]
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
            return best

        if st == 3:
            real = 1.0
        elif barrel:
            real = 0.68 if st == 1 else 0.90
        else:
            real = 0.96 if ip else 0.90
        ev_call = eq * real * (P + c) - c
        best, best_ev = (Action("call"), ev_call) if ev_call > 0 else (Action("fold"), 0.0)
        if can_raise and not wait:
            rr = risk("p_vs_raise")
            for frac in (0.6, 1.0, 1e9):
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
        return best
