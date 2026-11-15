"""Judges a candidate bundle against the live build: clone tables seated like Saturday's late rounds, the final-table
field, and self-play against copies of the live build. Thresholds come from the backtests in night/sim/JUDGE.md."""
import argparse
import math
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arena.backtest import BB, expand, play_round

LATE = {
    "r041": "clone_astra,clone_red,clone_wbot,clone_kojack,clone_claudebot,clone_lehman,clone_sars",
    "r045": "clone_anker,clone_pokermon,clone_equity,clone_resonance,clone_lehman,clone_pokebot,clone_sars",
    "r046": "clone_munchlax,clone_lehman,clone_jumpstreet,clone_fishermen,clone_equity,clone_matcha,clone_pokebot",
    "r048": "clone_attention,clone_test,clone_kaiserbot,clone_pokebot,clone_matcha,clone_aivey,clone_claudebot",
    "r049": "clone_equity,clone_smartbger,clone_ailin,clone_munchlax,clone_attention,clone_aivey,clone_resonance",
    "r052": "clone_astra,clone_fishermen,clone_joca,clone_nd,clone_munchlax,clone_bigroddy,clone_red",
    "r053": "clone_kojack,clone_anton,clone_fishermen,clone_nd,clone_gamblerlove,clone_pokermon",
    "r054": "clone_anton,clone_nd,clone_clanker,clone_aivey,clone_attention,clone_supernut",
    "r031": "clone_sars,clone_pokermon,clone_field,clone_kaiserbot,clone_smartbger,clone_joca",
}
FINAL = "clone_attention,clone_marketmakers,clone_resonance,clone_anker,clone_fishermen,clone_equity,clone_kojack"
MIX = "@0*3,clone_attention,clone_fishermen,clone_kojack,clone_resonance"
TAGS = ("showdown", "noshow_postflop", "call12", "reraised", "betraised1")
RATES = (("flop bets called", "F1c", ("F1c", "F1f", "F1r"), 2.0), ("turn bets called", "F2c", ("F2c", "F2f", "F2r"), 3.0),
         ("river bets called", "F3c", ("F3c", "F3f", "F3r"), 4.0), ("re-raises of our open called", "P3c", ("P3c", "P3f", "P3r"), 3.0))


def mean_se(xs):
    n = len(xs)
    m = sum(xs) / n
    return m, (math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n) if n > 1 else float("nan"))


def part(r, tag, hands):
    return 100.0 * r["tag"].get(tag, [0, 0.0])[1] / hands / BB if tag else 100.0 * r["fair"] / BB


def pooled(tables, hands, tag=None):
    """Candidate minus live build over a group of tables, each table weighing the same."""
    ms, vs = [], []
    for base, cand in tables:
        m, se = mean_se([part(c, tag, hands) - part(b, tag, hands) for b, c in zip(base, cand)])
        ms.append(m)
        vs.append(se * se)
    return sum(ms) / len(ms), math.sqrt(sum(vs)) / len(ms)


def rate(rounds, yes, keys):
    tot = sum(r["dec"].get(k, 0) for r in rounds for k in keys)
    return 100.0 * sum(r["dec"].get(yes, 0) for r in rounds) / tot if tot else float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cand", required=True)
    ap.add_argument("--base", required=True, help="the live build, bot_v6l.py")
    ap.add_argument("--only", default="late,final,self,mix")
    ap.add_argument("--scale", type=float, default=1.0, help="multiplies the number of rounds of every test")
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=90000)
    ap.add_argument("--procs", type=int, default=1)
    a = ap.parse_args()
    bots = [os.path.abspath(a.base), os.path.abspath(a.cand)]
    groups = []
    if "late" in a.only:
        groups.append(("late", [(k, f, 40) for k, f in LATE.items()]))
    if "final" in a.only:
        groups.append(("final", [("final", FINAL, 80)]))
    if "self" in a.only:
        # blocks of 50 self-play rounds have disagreed by 13 bb/100, so both home tables are played and the bar is high
        groups.append(("self", [("live_copies", "@0*7", 50), ("cand_copies", "@1*7", 50)]))
    if "mix" in a.only:
        groups.append(("mix", [("mix", MIX, 60)]))
    jobs, index = [], []
    seed = a.seed
    for g, tables in groups:
        for name, field, rounds in tables:
            n = max(4, int(round(rounds * a.scale)))
            f = expand(field, bots)
            for k, b in enumerate(bots):
                for r in range(n):
                    jobs.append((b, f, seed + r, a.hands))
                    index.append((g, name, k))
            seed += 1000
    if a.procs > 1:
        with multiprocessing.Pool(a.procs) as pool:
            res = pool.map(play_round, jobs, chunksize=1)
    else:
        res = [play_round(j) for j in jobs]
    got = {}
    for (g, name, k), r in zip(index, res):
        got.setdefault(g, {}).setdefault(name, ([], []))[k].append(r)
    verdict = []
    for g, _ in groups:
        tables = list(got[g].values())
        m, se = pooled(tables, a.hands)
        n = sum(len(t[0]) for t in tables)
        lvl = mean_se([part(r, None, a.hands) for t in tables for r in t[0]])[0]
        print("%-5s %d tables, %d paired rounds: live build %+.1f bb/100; candidate minus live build %+.1f (se %.1f)" % (
            g, len(tables), n, lvl, m, se))
        print("      by part: " + "  ".join("%s %+.1f (se %.1f)" % ((t,) + pooled(tables, a.hands, t)) for t in TAGS))
        if len(tables) > 1:
            print("      by table: " + "  ".join("%s %+.1f" % (k, pooled([t], a.hands)[0]) for k, t in got[g].items()))
        floor = {"late": 3.5, "final": 7.0, "self": 7.0, "mix": 7.0}[g]
        if m < -max(floor, 2 * se):
            verdict.append("WORSE on %s: %+.1f (se %.1f)" % (g, m, se))
        elif m > max(floor, 2 * se):
            verdict.append("better on %s: %+.1f (se %.1f)%s" % (
                g, m, se, "; self-play has not reproduced a live result" if g == "self"
                else "; counts only if it does not come from showdown or call12"))
        if g == "late":
            base = [r for t in tables for r in t[0]]
            cand = [r for t in tables for r in t[1]]
            for label, yes, keys, limit in RATES:
                x, y = rate(base, yes, keys), rate(cand, yes, keys)
                flag = "   <-- calls more" if y - x > limit else ""
                print("      %-28s live build %4.1f%%  candidate %4.1f%%%s" % (label, x, y, flag))
                if flag:
                    verdict.append("calls more (%s %.1f%% -> %.1f%%): needs a reason from the real hands" % (label, x, y))
    print("verdict: " + ("; ".join(verdict) if verdict else "no test separates the candidate from the live build"))


if __name__ == "__main__":
    main()
