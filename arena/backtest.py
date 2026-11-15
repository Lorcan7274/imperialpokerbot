"""Paired comparison of bundles like abtest.py, with our seat's hands tagged by situation, for backtests."""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arena.abtest import make_agent, registry
from arena.engine import Table
from arena.kitlike import KitSeat

BB = 20


def tag_hand(hist, me):
    """What happened to `me` in one hand: situations met (tags), each decision facing a bet (dec), who put chips in,
    whose flop and turn bets were called."""
    tags, dec, vol, called = set(), [], set(), set()
    street = None
    raises = 0
    agg = None
    my_open = False
    i_bet = False
    for r in hist:
        if r.kind in ("sb", "bb"):
            continue
        if r.street != street:
            street = r.street
            raises = 0
            agg = None
            i_bet = False
        p = r.player
        if p != me and r.kind in ("call", "raise"):
            vol.add(p)
        if p == me:
            if street == 0:
                if raises == 0 and r.kind == "raise":
                    my_open = True
                    tags.add("open")
                elif raises and my_open and agg != me:
                    dec.append("P3" + r.kind[0])
                elif raises and not my_open:
                    dec.append("Pv" + r.kind[0])
                    if r.kind == "raise" and raises == 1:
                        tags.add("we3bet")
            elif agg is not None and agg != me:
                dec.append("%s%d%s" % ("R" if i_bet else "F", street, r.kind[0]))
                if r.kind == "call":
                    tags.add("call%d" % street)
                    if street < 3:
                        called.add(agg)
                    if i_bet:
                        tags.add("callraise%d" % street)
            elif agg is None:
                dec.append("B%d%s" % (street, "b" if r.kind == "raise" else "x"))
            if r.kind == "raise" and street:
                i_bet = True
                tags.add("bet%d" % street)
        if r.kind == "raise":
            raises += 1
            if p != me:
                if street == 0 and my_open:
                    tags.add("reraised")
                if street and i_bet:
                    tags.add("betraised%d" % street)
            agg = p
    if "call1" in tags or "call2" in tags:
        tags.add("call12")
    return tags, dec, vol, called


class Recorder:
    def __init__(self, inner):
        self.inner = inner
        self.hands = []

    def decide(self, s):
        return self.inner.decide(s)

    def end_hand(self, history, showdown, board=()):
        self.hands.append((history, showdown))
        self.inner.end_hand(history, showdown, board)


def summarise(hands, nets, me, kind_of):
    """Per round: chips per tag, decision counts, chips against each kind of opponent (split among those who played)."""
    tag = {}
    dec = {}
    vs = {}
    vsc = {}
    for (hist, showdown), x in zip(hands, nets):
        tags, ds, vol, called = tag_hand(hist, me)
        for p in called:
            c = vsc.setdefault(kind_of(p), [0, 0.0])
            c[0] += 1
            c[1] += x / len(called)
        if showdown and me in showdown:
            tags.add("showdown")
            if "call12" in tags:
                tags.add("call12_shown")
                if x > 0:
                    tags.add("call12_won")
        elif any(r.player == me and r.kind != "fold" and r.street for r in hist):
            tags.add("noshow_postflop")
        for t in tags:
            c = tag.setdefault(t, [0, 0.0])
            c[0] += 1
            c[1] += x
        for d in ds:
            dec[d] = dec.get(d, 0) + 1
        for p in vol:
            k = kind_of(p)
            c = vs.setdefault(k, [0, 0.0])
            c[0] += 1
            c[1] += x / len(vol)
    return {"tag": tag, "dec": dec, "vs": vs, "vsc": vsc}


def play_round(job):
    path, field, seed, hands = job
    reg = registry()
    names = ["hero"] + ["%s#%d" % (k, i) for i, k in enumerate(field)]
    order = list(names)
    random.Random(seed).shuffle(order)
    bots = {}
    for nm in order:
        if nm == "hero":
            bots[nm] = rec = Recorder(KitSeat(make_agent(path, seed, False), order, nm, hands))
            continue
        kind, i = nm.rsplit("#", 1)
        if kind.startswith("bot:"):
            bots[nm] = KitSeat(make_agent(kind[4:], seed * 100 + int(i), False), order, nm, hands)
        else:
            bots[nm] = reg[kind](seed=seed * 100 + int(i))
    table = Table(bots, seed=seed)
    _, log = table.play(hands)
    fair = table.fair_log["hero"]
    out = summarise(rec.hands, fair, "hero", lambda p: os.path.basename(p.rsplit("#", 1)[0]))
    out["net"] = sum(log["hero"]) / hands
    out["fair"] = sum(fair) / hands
    others = {}
    for nm in names[1:]:
        k = os.path.basename(nm.rsplit("#", 1)[0])
        others.setdefault(k, []).append(sum(table.fair_log[nm]) / hands)
    out["others"] = {k: sum(v) / len(v) for k, v in others.items()}
    return out


def mean_se(xs):
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n)


def expand(spec, bots):
    field = []
    for tok in spec.split(","):
        tok, _, rep = tok.partition("*")
        if tok.startswith("@"):
            tok = "bot:" + bots[int(tok[1:])]
        field += [tok] * int(rep or 1)
    return field


def main():
    ap = argparse.ArgumentParser(description="Tagged paired comparison; the first bundle is the baseline.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--bots", required=True, help="comma list of bundles; @0, @1 ... in the field seat copies")
    ap.add_argument("--field", required=True)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    bots = [os.path.abspath(b) for b in a.bots.split(",")]
    field = expand(a.field, bots)
    res = {b: [play_round((b, field, a.seed + r, a.hands)) for r in range(a.rounds)] for b in bots}
    line = {"name": a.name, "field": a.field, "rounds": a.rounds, "hands": a.hands, "seed": a.seed,
            "bots": bots, "res": [res[b] for b in bots]}
    if a.out:
        with open(a.out, "a") as f:
            f.write(json.dumps(line) + "\n")
    base = [r["fair"] for r in res[bots[0]]]
    for b in bots:
        m, se = mean_se([r["fair"] for r in res[b]])
        txt = "%s %-14s %-12s %+7.1f se %4.1f" % (a.name, os.path.basename(b), "level", 100 * m / BB, 100 * se / BB)
        if b != bots[0]:
            m, se = mean_se([r["fair"] - x for r, x in zip(res[b], base)])
            txt += "   minus %s %+7.1f se %4.1f" % (os.path.basename(bots[0]), 100 * m / BB, 100 * se / BB)
        print(txt, flush=True)


if __name__ == "__main__":
    main()
