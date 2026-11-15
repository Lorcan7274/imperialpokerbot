from bisect import bisect_left, bisect_right

from arena.opponents import Base
from pokerbot.cards import evaluate
from pokerbot.preflop import COMBOS, COMBO_PCT, PREFLOP_ORDER, class_name
from pokerbot.state import Action

NC = len(COMBOS)
CLASS_PCT = {}
CLASS_COMBOS = {}
for _i, (_a, _b) in enumerate(COMBOS):
    _nm = class_name(_a, _b)
    CLASS_PCT[_nm] = COMBO_PCT[_i]
    CLASS_COMBOS.setdefault(_nm, []).append((_a, _b))
CLASSES = sorted(CLASS_PCT, key=CLASS_PCT.get)


def S(text):
    return frozenset(text.split())


OPEN = (0.44, 0.29, 0.22, 0.17, 0.14, 0.12, 0.10)
SB_OPEN = 0.42
EXTRA_EARLY = S("JTs T9s 98s 55 44 A4s")
EXTRA_MID = EXTRA_EARLY | S("87s 76s 33 22 A3s A2s")
EXTRA_LATE = EXTRA_MID | S("65s 54s 97s 86s 75s T7s 64s 53s 96s")
TIERS = (S("AA KK"), S("QQ AKs"), S("JJ AKo"), S("TT AQs"), S("99 AJs KQs AQo"), S("88 ATs KJs AJo"),
         S("77 KTs QJs A9s KQo"))
BLUFF3 = "A5s A4s A3s A2s K9s K8s Q9s J9s T9s 98s K7s K6s 87s 76s K5s 65s".split()
BLUFF4 = "A5s A4s A3s A2s K5s K4s".split()
CALL_IP = S("66 55 44 33 22 JTs T9s 98s 87s QJs")
CALL_3B = S("JTs T9s 98s QJs KQs KJs ATs")

BET0 = (0.60, 0.50, 0.42)
BET_VS = (0.50, 0.58, 0.66)
RAISE0 = (0.14, 0.11, 0.09)
RAISE_VS = (0.60, 0.70, 0.80)
DAMP = 0.65


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def value(kf):
    kf = clamp(kf, 1.0, len(TIERS) - 0.01)
    out = {}
    for t in TIERS[:int(kf)]:
        for nm in t:
            out[nm] = 1.0
    frac = kf - int(kf)
    if frac > 0.02:
        for nm in TIERS[int(kf)]:
            out[nm] = frac
    return out


def add_bluffs(rv, names, combos):
    for nm in names:
        if combos <= 0:
            break
        if nm in rv:
            continue
        p = min(1.0, combos / 4.0)
        rv[nm] = p
        combos -= 4.0 * p


def weight_of(rv):
    return sum(p * len(CLASS_COMBOS[nm]) for nm, p in rv.items())


def texture(board):
    suits = [0] * 4
    for c in board:
        suits[c & 3] += 1
    rs = sorted({c >> 2 for c in board})
    close = sum(1 for a, b in zip(rs, rs[1:]) if b - a <= 2)
    return max(suits) >= 2 or close >= 2


class Ctx:
    __slots__ = ("rthr", "rv", "cthr", "cx", "free", "to")

    def __init__(self, rthr=0.0, rv=None, cthr=0.0, cx=(), free=False, to=0):
        self.rthr, self.rv, self.cthr, self.cx, self.free, self.to = rthr, rv or {}, cthr, cx, free, to

    def probs(self, nm):
        p = CLASS_PCT[nm]
        r = 1.0 if p < self.rthr else self.rv.get(nm, 0.0)
        if self.free:
            return 1.0 - r, r
        return ((1.0 - r) if (p < self.cthr or nm in self.cx) else 0.0), r


class Theory(Base):
    """Static equilibrium-style player: seat-based pre-flop ranges with mixed three-bets and four-bets; after the flop it tracks its own range and each opponent's, scores every hand of its range by equity against theirs, and bets, raises and defends by position in that range at sizes fixed by the spot, never by the hand."""

    loose = 1.0
    k3 = 0.0
    b3 = 1.0
    bluff = 1.0
    thin = 0.0
    defend_f = (0.95, 0.90, 0.85)
    sizes = (0.33, 0.55, 0.66, 0.75)
    M = 130
    K = 48
    RUNS = (14, 8)
    strict = False

    def __init__(self, seed=0):
        super().__init__(seed)
        self.hid = None
        self.reset(None)

    def reset(self, hid):
        self.hid = hid
        self.pre_log = []
        self.my_open = 0.0
        self.hands = None
        self.mw = None
        self.opp = {}
        self.nboard = 0


    def can_raise(self, s):
        return bool(s.max_raise_to) and bool(s.min_raise_to) and s.max_raise_to > (s.my_bet or 0) + (s.to_call or 0)

    def legal(self, s, a):
        c = s.to_call or 0
        if a.kind == "raise":
            if not self.can_raise(s):
                return Action("call") if c else Action("check")
            return Action("raise", int(min(max(a.amount, s.min_raise_to), s.max_raise_to)))
        if a.kind == "call":
            return Action("call") if c else Action("check")
        if a.kind == "check" or not c:
            return Action("fold") if c else Action("check")
        return Action("fold")

    def decide(self, s):
        if self.strict:
            return self.legal(s, self.act(s))
        try:
            return self.legal(s, self.act(s))
        except Exception:
            return Action("check") if not s.to_call else Action("fold")

    def act(self, s):
        tag = (s.hand_id, s.hole[0], s.hole[1])
        if tag != self.hid:
            self.reset(tag)
        return self.post(s) if s.board else self.pre(s)


    def seat_open(self, idx, n):
        if idx == 0 and n > 2:
            return SB_OPEN
        if idx == 1 and n > 2:
            return 0.10
        return OPEN[min(n - 1 - idx, 6)]

    def pre_ctx(self, s):
        me = s.hero
        bb = s.big_blind or 20
        players = s.players
        n = len(players)
        idx = players.index(me)
        c = s.to_call or 0
        my_bet = s.my_bet or 0
        level = my_bet + c
        stack0 = (s.my_stack or 0) + my_bet
        raises = []
        limpers = callers = mine = 0
        for r in s.history:
            if r.street:
                break
            if r.kind == "raise":
                raises.append(r)
                callers = 0
                if r.player == me:
                    mine += 1
            elif r.kind == "call":
                if raises:
                    callers += 1
                else:
                    limpers += 1
        nr = len(raises)
        big = level >= 0.3 * stack0
        jam = s.max_raise_to or 0
        if nr == 0:
            if not c:
                return Ctx(rthr=0.10 * self.loose, free=True, to=(3.5 + limpers) * bb)
            if idx == 0 and n > 2:
                if limpers:
                    return Ctx(rthr=0.12 * self.loose, cthr=0.55, to=(4 + limpers) * bb)
                self.my_open = SB_OPEN * self.loose
                return Ctx(rthr=self.my_open, rv=dict.fromkeys(EXTRA_LATE, 1.0), to=3 * bb)
            d = min(n - 1 - idx, 6)
            base = OPEN[d] * self.loose
            if limpers:
                self.my_open = 0.75 * base
                return Ctx(rthr=self.my_open, cthr=1.25 * base + (0.1 if d <= 1 else 0.0), to=(3.5 + limpers) * bb)
            self.my_open = base
            extra = EXTRA_LATE if d <= 1 else EXTRA_MID if d <= 3 else EXTRA_EARLY
            return Ctx(rthr=base, rv=dict.fromkeys(extra, 1.0), to=(2.3 if d <= 1 else 2.5) * bb)
        last = raises[-1]
        li = players.index(last.player) if last.player in players else 0
        ip = idx > li
        level = max(level, bb)
        odds = c / float((s.pot or 0) + c) if c else 0.0
        if nr == 1 and not mine:
            if big:
                cx = TIERS[0] | TIERS[1] | TIERS[2]
                return Ctx(cx=cx if callers else cx | TIERS[3] | S("99"))
            R = self.seat_open(li, n)
            size = level / bb
            sf = clamp(2.6 / size, 0.35, 1.1)
            rv = value(2.3 + 7.0 * (R - 0.10) + self.k3 - 0.25 * max(0.0, size - 3.5))
            ratio = (0.85 if ip else 0.65) * self.b3 * sf * (0.6 if callers else 1.0)
            add_bluffs(rv, BLUFF3, ratio * weight_of(rv))
            cx = ()
            if idx == 1 and n > 2:
                cthr = clamp((0.24 + 0.8 * R) * (0.27 / max(odds, 0.05)) ** 1.2, 0.04, 0.62)
            elif idx == 0 and n > 2:
                cthr = 0.3 * R * sf
            else:
                cthr = (0.65 if idx == n - 1 else 0.5) * R * sf + 0.01
                if size <= 3.2 and R >= 0.15:
                    cx = CALL_IP
            to = ((3.0 if ip else 4.0) + callers) * level
            return Ctx(rv=rv, cthr=cthr, cx=cx, to=jam if to >= 0.4 * stack0 else to)
        if nr == 2 and mine == 1 and raises[0].player == me:
            R = self.my_open or 0.2
            if big:
                return Ctx(cx=TIERS[0] | TIERS[1] | (TIERS[2] if R >= 0.25 else frozenset()))
            ratio3 = level / float(max(my_bet, bb))
            rv = value(1.5 + 3.0 * (R - 0.10) + 0.5 * self.k3)
            add_bluffs(rv, BLUFF4, 0.5 * self.b3 * weight_of(rv))
            cont = (0.48 if ip else 0.40) * clamp(3.3 / ratio3, 0.5, 1.2)
            to = (2.2 if ip else 2.5) * level
            return Ctx(rv=rv, cthr=clamp(R * cont, 0.03, 0.22), cx=CALL_3B if ip and ratio3 <= 3.6 else (),
                       to=jam if to >= 0.45 * stack0 else to)
        if nr == 2:
            if big:
                return Ctx(cx=TIERS[0] | TIERS[1])
            to = 2.3 * level
            rv = value(1.5 + 0.3 * self.k3)
            add_bluffs(rv, BLUFF4, 0.4 * self.b3 * weight_of(rv))
            return Ctx(rv=rv, to=jam if to >= 0.45 * stack0 else to)
        if nr == 3 and mine == 1 and raises[1].player == me:
            if big:
                return Ctx(cx=TIERS[0] | TIERS[1] | (TIERS[2] if ip else frozenset()))
            rv = value(1.7 + 0.3 * self.k3)
            rv.setdefault("A5s", min(1.0, 0.3 * self.b3))
            return Ctx(rv=rv, cx=TIERS[1] | TIERS[2] | (TIERS[3] if ip else frozenset()), to=jam)
        return Ctx(rv=dict.fromkeys(TIERS[0], 1.0), cthr=0.12 if odds <= 0.22 else 0.0, cx=TIERS[1], to=jam)

    def pre(self, s):
        ctx = self.pre_ctx(s)
        pc, pr = ctx.probs(class_name(*s.hole))
        u = self.rng.random()
        k = 2 if u < pr else 1 if u < pr + pc else 0
        self.pre_log.append((ctx, k))
        if k == 2:
            return Action("raise", int(ctx.to))
        return Action("call") if k else Action("fold")


    def build_range(self, s):
        w = dict.fromkeys(CLASSES, 1.0)
        for ctx, k in self.pre_log:
            for nm in CLASSES:
                x = w[nm]
                if x:
                    pc, pr = ctx.probs(nm)
                    w[nm] = x * (pr if k == 2 else pc if k == 1 else 1.0 - pc - pr)
        dead = set(s.board)
        dead.update(s.hole)
        pool = []
        acc = 0.0
        for nm in CLASSES:
            x = w[nm]
            if x > 0:
                for a, b in CLASS_COMBOS[nm]:
                    if a not in dead and b not in dead:
                        acc += x
                        pool.append((acc, a, b))
        hands = [(s.hole[0], s.hole[1])]
        n = self.M - 1
        if len(pool) <= n:
            ws = [0.0]
            prev = 0.0
            for cum, a, b in pool:
                hands.append((a, b))
                ws.append(cum - prev)
                prev = cum
            ws[0] = acc / len(pool) if pool else 1.0
        else:
            step = acc / n
            x = self.rng.random() * step
            cums = [p[0] for p in pool]
            for _ in range(n):
                p = pool[min(bisect_left(cums, x), len(pool) - 1)]
                hands.append((p[1], p[2]))
                x += step
            ws = [1.0] * len(hands)
        self.hands, self.mw = hands, ws

    def opp_segs(self, s, p):
        players = s.players
        n = len(players)
        nr = 0
        raised = []
        last = None
        opener = None
        for r in s.history:
            if r.street:
                break
            if r.kind == "raise":
                if not nr:
                    opener = r.player
                if r.player == p:
                    raised.append(nr)
                    last = ("raise", nr)
                nr += 1
            elif r.kind == "call" and r.player == p:
                last = ("call", nr)
        idx = players.index(p) if p in players else 2
        R = self.seat_open(idx, n)
        if raised:
            k = raised[-1]
            called = last[0] == "call"
            if k == 0:
                if called:
                    return [(0.0, 0.012, 0.35), (0.012, 0.45 * R + 0.03, 1.0)], 0.04
                return [(0.0, 1.15 * R, 1.0)], 0.05
            if k == 1:
                if called:
                    return [(0.003, 0.05, 1.0)], 0.03
                return [(0.0, 0.045, 1.0), (0.045, 0.30, 0.10)], 0.03
            return [(0.0, 0.028, 1.0)], 0.04
        if last is None:
            return [(0.0, 0.08, 0.3), (0.08, 1.0, 1.0)], 0.0
        k = last[1]
        if k == 0:
            return [(0.0, 0.06, 0.3), (0.06, 0.70, 1.0)], 0.05
        if k == 1:
            Ro = self.seat_open(players.index(opener), n) if opener in players else 0.2
            if idx == 1:
                return [(0.0, 0.03, 0.3), (0.03, 0.28 + 0.75 * Ro, 1.0)], 0.05
            return [(0.0, 0.025, 0.35), (0.025, 0.07 + 0.6 * Ro, 1.0)], 0.05
        if k == 2:
            return [(0.008, 0.11, 1.0)], 0.04
        return [(0.0, 0.04, 1.0)], 0.03

    def draw(self, segs, leak, dead, k):
        rnd = self.rng.random
        tot = sum((hi - lo) * w for lo, hi, w in segs)
        out = []
        tries = 0
        while len(out) < k and tries < 25 * k:
            tries += 1
            if rnd() < leak:
                i = int(rnd() * NC)
            else:
                x = rnd() * tot
                lo = hi = 0.0
                for lo, hi, w in segs:
                    x -= (hi - lo) * w
                    if x <= 0:
                        break
                i = int((lo + rnd() * (hi - lo)) * NC)
            a, b = COMBOS[PREFLOP_ORDER[min(i, NC - 1)]]
            if a not in dead and b not in dead:
                out.append((a, b))
        if not out:
            deck = [c for c in range(52) if c not in dead]
            out = [tuple(self.rng.sample(deck, 2)) for _ in range(k)]
        return out

    def samples(self, s, p, k):
        board = s.board
        got = self.opp.get(p)
        if got:
            got = [h for h in got if h[0] not in board and h[1] not in board]
        if not got or len(got) < 10:
            dead = set(board)
            dead.update(s.hole)
            segs, leak = self.opp_segs(s, p)
            got = self.draw(segs, leak, dead, k)
        self.opp[p] = got
        return got

    def scan(self, s):
        me = s.hero
        ev = {}
        pot = st = level = checks = last_amt = nraise = 0
        agg_prev = agg = None
        for r in s.history:
            if r.street != st:
                st = r.street
                level = checks = last_amt = nraise = 0
                agg_prev, agg = agg, None
            k = r.kind
            if st and r.player != me:
                if k == "raise":
                    ev.setdefault(r.player, []).append((st, "raise" if level else "bet", r.amount / float(max(pot, 1))))
                elif k == "call":
                    ev.setdefault(r.player, []).append((st, "call", last_amt / float(max(pot, 1))))
                elif k == "check":
                    ev.setdefault(r.player, []).append((st, "check", 1.0 if checks or r.player == agg_prev else 0.0))
            if k == "raise":
                level = r.to
                agg = r.player
                last_amt = r.amount
                nraise += 1
            elif k == "check":
                checks += 1
            pot += r.amount
        if st != s.street:
            agg_prev = agg
            last_amt = nraise = 0
        return ev, agg_prev, last_amt, nraise

    def narrow(self, x, evs, cur):
        k = len(x)
        w = [1.0] * k
        order = sorted(range(k), key=x.__getitem__, reverse=True)
        for st, kind, f in evs:
            if kind == "check" and not f:
                continue
            g = DAMP ** (cur - st)
            tot = sum(w)
            acc = 0.0
            if kind == "call":
                lo = 1.0 - clamp(f, 0.1, 0.85)
                hi = 0.6 * RAISE0[st - 1]
                mt = (0.5 if st < 3 else 0.3) ** g
                mb = 0.08 ** g
                for j in order:
                    u = (acc + 0.5 * w[j]) / tot
                    acc += w[j]
                    if u > lo:
                        w[j] *= mb
                    elif u < hi:
                        w[j] *= mt
            elif kind == "check":
                m = 0.4 ** g
                for j in order:
                    u = (acc + 0.5 * w[j]) / tot
                    acc += w[j]
                    if u < 0.2:
                        w[j] *= m
            else:
                if kind == "bet":
                    beta = clamp(BET0[st - 1] * (0.66 / max(f, 0.2)) ** 0.5, 0.1, 0.9)
                    top = beta * BET_VS[st - 1]
                else:
                    beta = RAISE0[st - 1]
                    top = beta * RAISE_VS[st - 1]
                m = ((beta - top) / (1.0 - top)) ** g
                for j in order:
                    u = (acc + 0.5 * w[j]) / tot
                    acc += w[j]
                    if u >= top:
                        w[j] *= m
        return w

    def analyse(self, s, opps, ev):
        board = list(s.board)
        need = 5 - len(board)
        hands, mw = self.hands, self.mw
        m = len(hands)
        runs = [()]
        if need:
            dead = set(board)
            dead.update(s.hole)
            deck = [c for c in range(52) if c not in dead]
            k = self.RUNS[need - 1]
            if len(opps) > 2:
                k = k * 2 // 3
            sample = self.rng.sample
            runs += [tuple(sample(deck, need)) for _ in range(k)]
        ko = self.K if len(opps) <= 2 else 30
        smp = [self.samples(s, p, ko) for p in opps]
        mv = []
        ov = [[] for _ in opps]
        for run in runs:
            full = board + list(run)
            if run:
                mv.append([evaluate([a, b] + full) if a not in run and b not in run else -1 for a, b in hands])
                for o, hs in zip(ov, smp):
                    o.append([evaluate([a, b] + full) if a not in run and b not in run else -1 for a, b in hs])
            else:
                mv.append([evaluate([a, b] + full) for a, b in hands])
                for o, hs in zip(ov, smp):
                    o.append([evaluate([a, b] + full) for a, b in hs])
        eq_runs = range(1, len(runs)) if need else (0,)
        own = {}
        for r in eq_runs:
            pairs = sorted((v, w) for v, w in zip(mv[r], mw) if v >= 0 and w > 0)
            cum = [0.0]
            acc = 0.0
            for _, w in pairs:
                acc += w
                cum.append(acc)
            own[r] = ([p[0] for p in pairs], cum)
        tabs = []
        for p, hs, vals in zip(opps, smp, ov):
            x = []
            for j in range(len(hs)):
                tot = 0.0
                cnt = 0
                for r in eq_runs:
                    v = vals[r][j]
                    vs, cum = own[r]
                    if v >= 0 and cum[-1] > 0:
                        tot += (cum[bisect_left(vs, v)] + cum[bisect_right(vs, v)]) / (2.0 * cum[-1])
                        cnt += 1
                x.append(tot / cnt if cnt else 0.5)
            ow = self.narrow(x, ev.get(p, ()), s.street)
            tab = []
            for r in range(len(runs)):
                pairs = sorted((v, w) for v, w in zip(vals[r], ow) if v >= 0)
                cum = [0.0]
                acc = 0.0
                for _, w in pairs:
                    acc += w
                    cum.append(acc)
                tab.append(([q[0] for q in pairs], cum))
            tabs.append(tab)

        def score(rs):
            e = [0.0] * m
            cnt = [0] * m
            for r in rs:
                rt = [t[r] for t in tabs if t[r][1][-1] > 0]
                vals = mv[r]
                for i in range(m):
                    v = vals[i]
                    if v < 0:
                        continue
                    y = 1.0
                    for vs, cum in rt:
                        y *= (cum[bisect_left(vs, v)] + cum[bisect_right(vs, v)]) / (2.0 * cum[-1])
                    e[i] += y
                    cnt[i] += 1
            return [e[i] / cnt[i] if cnt[i] else 0.0 for i in range(m)]

        e = score(eq_runs)
        return e, (score((0,)) if need else e)


    def size(self, s, st, nopp):
        if st == 1:
            pre = sum(r.amount for r in s.history if not r.street)
            if nopp >= 2:
                return 0.5
            return self.sizes[0] if pre >= 18 * (s.big_blind or 20) or not texture(s.board) else self.sizes[1]
        return self.sizes[st]

    def fill(self, prob, cand, w, target):
        for i in cand:
            if target <= 0:
                break
            x = w[i]
            if x > 0:
                p = min(1.0, target / x)
                prob[i] = p
                target -= x * p

    def post(self, s):
        me = s.hero
        if self.hands is None:
            self.build_range(s)
        if s.board != self.nboard:
            self.nboard = board = list(s.board)
            keep = [i for i, (a, b) in enumerate(self.hands) if i == 0 or (a not in board and b not in board)]
            self.hands = [self.hands[i] for i in keep]
            self.mw = [self.mw[i] for i in keep]
        opps = [p for p in s.active if p != me]
        c = s.to_call or 0
        if not opps:
            return Action("call") if c else Action("check")
        ev, agg_prev, last_amt, nraise = self.scan(s)
        e, cur = self.analyse(s, opps, ev)
        w = self.mw
        m = len(w)
        st = s.street
        nopp = len(opps)
        can = self.can_raise(s)
        pot = max(s.pot or 1, 1)
        stack = s.my_stack or 0
        u = self.rng.random()
        rng_m = range(m)
        draw = [x - 0.8 * y for x, y in zip(e, cur)]
        if not c:
            prob = [0.0] * m
            behind = agg_prev is not None and agg_prev != me and agg_prev in s.active and (
                s.players.index(agg_prev) > s.players.index(me))
            f = self.size(s, st, nopp)
            amt = int(f * pot)
            if amt >= 0.65 * stack:
                amt = stack
            f = amt / float(pot)
            if can and not behind:
                tv = 1.0 - 0.5 / (1.0 + f) - (0.03, 0.02, 0.0)[st - 1] + self.thin
                trap = st < 3 and nopp == 1
                v = 0.0
                for i in rng_m:
                    if e[i] >= tv:
                        prob[i] = 0.88 if trap and e[i] >= 0.86 else 1.0
                        v += w[i] * prob[i]
                ratio = (2.5, 1.5, 1.0)[st - 1] * f / (1.0 + f) * self.bluff * (1.0, 0.5, 0.25)[min(nopp, 3) - 1]
                if st < 3:
                    cand = sorted((i for i in rng_m if e[i] < tv and cur[i] < 0.42), key=draw.__getitem__, reverse=True)
                else:
                    lim = min(0.35, tv)
                    cand = sorted((i for i in rng_m if e[i] < lim), key=e.__getitem__)
                self.fill(prob, cand, w, v * ratio)
            bet = u < prob[0]
            self.mw = [max(x * (p if bet else 1.0 - p), 0.02 * x) for x, p in zip(w, prob)]
            return Action("raise", (s.my_bet or 0) + amt) if bet else Action("check")
        need = c / float(pot + c)
        alpha = clamp((last_amt or c) / float(pot), 0.02, 0.95)
        d = (1.0 - alpha) * self.defend_f[st - 1] * (1.0 if nopp == 1 else 0.8)
        order = sorted(rng_m, key=e.__getitem__, reverse=True)
        tot = sum(w) or 1.0
        q = [0.0] * m
        acc = 0.0
        for i in order:
            q[i] = (acc + 0.5 * w[i]) / tot
            acc += w[i]
        big = c >= 0.45 * stack and c >= 15 * (s.big_blind or 20)
        allin = c >= stack
        pr = [0.0] * m
        to = (s.my_bet or 0) + c + (0.8 if st == 3 else 0.7) * (pot + c)
        jam = to - (s.my_bet or 0) >= 0.6 * stack
        if can and not allin:
            tr = (0.76, 0.78, 0.82)[st - 1] + (0.08 if nraise >= 2 else 0.0) + (0.07 if jam else 0.0) + self.thin
            pv = (0.7, 0.75, 1.0)[st - 1]
            v = 0.0
            for i in rng_m:
                if e[i] >= tr:
                    pr[i] = pv
                    v += w[i] * pv
            if nopp == 1 and nraise <= 1 and v > 0:
                if st < 3:
                    cand = sorted((i for i in rng_m if e[i] < tr and cur[i] < 0.42), key=draw.__getitem__, reverse=True)
                else:
                    cand = [i for i in order if q[i] > d and e[i] < need]
                self.fill(pr, cand, w, v * (0.9, 0.55, 0.35)[st - 1] * self.bluff * (0.5 if jam else 1.0))
        pc = [0.0] * m
        edge = 0.07 if st == 3 else 0.04
        for i in rng_m:
            x = e[i]
            if big:
                ok = x >= need - 0.02 and (q[i] <= d or x >= need + 0.08)
            else:
                ok = (q[i] <= d and x >= 0.7 * need) or x >= need + edge
            if ok:
                pc[i] = 1.0 - pr[i]
        if u < pr[0]:
            self.mw = [max(x * p, 0.02 * x) for x, p in zip(w, pr)]
            return Action("raise", int(s.max_raise_to if jam else to))
        if u < pr[0] + pc[0]:
            self.mw = [max(x * p, 0.02 * x) for x, p in zip(w, pc)]
            return Action("call")
        return Action("fold")


class TheoryAgg(Theory):
    """Theory with more three-bets, more bluffs and barrels, thinner value and wider defence."""

    loose = 1.1
    k3 = 0.5
    b3 = 1.4
    bluff = 1.3
    thin = -0.03
    defend_f = (1.0, 0.95, 0.9)
    sizes = (0.33, 0.6, 0.7, 0.85)


class TheoryTight(Theory):
    """Theory with tighter opens, value-heavy betting and narrower defence."""

    loose = 0.85
    k3 = -0.3
    b3 = 0.5
    bluff = 0.6
    thin = 0.03
    defend_f = (0.88, 0.8, 0.72)


THEORY = {"theory": Theory, "theory_agg": TheoryAgg, "theory_tight": TheoryTight}
