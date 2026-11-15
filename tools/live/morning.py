#!/usr/bin/env python3
"""One report over every round file in a hands directory.

    python3 morning.py <hands dir> [--prefix sunday_s1_] [--team Gherkers] [--last N]
                       [--sections table,rounds,luck,opponents,lines,halves] [--of 36]

The prefix picks the event: sunday_s1_ leaves practice and final files out.

Sections: table (standings and the gap to the final), rounds (one line a round, server
alerts, our versions), luck (all-in luck removed), opponents (how each team plays),
lines (where our chips come from and go), halves (first half against second half).
"""
import argparse
import glob
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations

# importing the repo must not leave bytecode files in it
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ.get("POKERBOT_REPO") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pokerbot.cards import evaluate, parse_card
from pokerbot.model import classify
from tools.handstats import to_history
from tools.pnl import label

BB = 20
SECTIONS = ("table", "rounds", "luck", "opponents", "lines", "halves")
QUIET = 60
SAMPLES = 3000
THINK_LIMIT = 6
SERVER_NUMBERS = ("bb100", "hands", "timeouts", "errors", "bank_out", "think_s")
ENDS = ("before the flop", "on the flop", "on the turn", "on the river, no showdown", "at showdown")
OPENS = {"early": "opened, early seat", "late": "opened, late seat", "sb": "opened, small blind",
         "bb": "raised from the big blind"}
FOLDS = {"unopened": "folded, nobody had raised", "vs_raise": "folded to a raise",
         "vs_3bet": "folded to a raise and a re-raise"}


def bb(chips):
    return chips / BB


def per100(chips, hands):
    return chips / BB / hands * 100 if hands else 0.0


def pct(part, whole, width=3):
    return "%*.0f" % (width, 100.0 * part / whole) if whole else "%*s" % (width, "-")


def pct_n(part, whole):
    return "%9s" % ("%.0f(%d)" % (100.0 * part / whole, whole) if whole else "-")


def ordinal(k):
    return "%d%s" % (k, "th" if 10 < k % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th"))


def natural(path):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", os.path.basename(path))]


def short_ref(ref):
    return str(ref).split("/")[-1]


def plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def round_number(name):
    m = re.search(r"(\d+)\.json$", name)
    return int(m.group(1)) if m else None


def seat_stats(h, events, me):
    """per seat, what it did in this hand, as counts that add up over hands"""
    n = len(h["results"])
    out = [Counter(hands=1, net=h["results"][i]) for i in range(n)]
    shown = h.get("showdown") or {}
    winners = {ev[1] for ev in h["events"] if ev[0] == "win"}
    paid_in, folded_pre, acted, raiser = set(), set(), set(), None
    for e in events:
        s = out[e.player]
        acted.add(e.player)
        if e.act in ("call", "raise"):
            paid_in.add(e.player)
        if e.street == 0:
            if e.act in ("call", "raise"):
                s["vpip"] = 1
            if e.act == "raise":
                s["pfr"] = 1
                s["shove"] |= e.shove
                raiser = e.player
            elif e.act == "fold":
                folded_pre.add(e.player)
            if e.sit == "vs_raise":
                s["tb_opp"] = 1
                s["tb"] |= e.act == "raise"
            elif e.sit == "re_raised" and not s["f3_opp"]:
                s["f3_opp"] = 1
                s["f3"] = e.act == "fold"
        elif e.street == 1:
            if e.sit[:8] == "p_no_bet" and e.player == raiser:
                s["cb_opp"] = 1
                s["cb"] = e.act == "raise"
            elif e.sit[:8] == "p_vs_bet":
                s["fb_opp"] = 1
                s["fb"] = e.act == "fold"
    flop = len(h.get("board") or []) >= 3
    for i, s in enumerate(out):
        s["flops"] = flop and i not in folded_pre
        if str(i) in shown:
            s["sd"] = 1
            s["sdwon"] = i in winners
        if i != me and i in paid_in and me in paid_in:
            s["vs_n"] = 1
            s["vs_net"] = h["results"][me]
    return out, acted, paid_in


def money(h):
    """chips each seat put in, and how many board cards were out at the last decision"""
    paid, street = Counter(), {}
    dealt = at_last = 0
    for ev in h["events"]:
        if ev[0] == "post":
            street[ev[1]] = ev[2]
        elif ev[0] == "board":
            paid.update(street)
            street = {}
            dealt = len(ev[2])
        elif ev[0] == "act":
            at_last = dealt
            if ev[2] == "raise":
                street[ev[1]] = ev[3]
            elif ev[2] == "call":
                street[ev[1]] = street.get(ev[1], 0) + ev[3]
        elif ev[0] == "refund":
            street[ev[1]] = street.get(ev[1], 0) - ev[2]
    paid.update(street)
    return paid, at_last


def side_pots(paid, live):
    pots, prev = [], 0
    for level in sorted({paid[p] for p in live}):
        chips = sum(min(v, level) - min(v, prev) for v in paid.values())
        pots.append((chips, [p for p in live if paid[p] >= level]))
        prev = level
    return pots


def share(pots, value, me):
    won = 0.0
    for chips, elig in pots:
        if me in elig:
            best = max(value[p] for p in elig)
            if value[me] == best:
                won += chips / sum(1 for p in elig if value[p] == best)
    return won


def allin_fair(h, me, seed):
    """our result averaged over the cards still to come, or None when the hand was not all-in before the river"""
    shown = h.get("showdown") or {}
    hole = h.get("hole") or {}
    if str(me) not in shown or len(shown) < 2 or any(k not in hole for k in shown):
        return None
    paid, at_last = money(h)
    if at_last >= 5:
        return None
    live = [int(k) for k in shown]
    cards = {p: [parse_card(c) for c in hole[str(p)]] for p in live}
    board = [parse_card(c) for c in h["board"][:at_last]]
    used = set(board).union(*cards.values())
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    if need <= 2:
        runs = combinations(deck, need)
    else:
        rng = random.Random(seed)
        runs = (rng.sample(deck, need) for _ in range(SAMPLES))
    pots = side_pots(paid, live)
    total = count = 0
    for run in runs:
        rest = board + list(run)
        total += share(pots, {p: evaluate(cards[p] + rest) for p in live}, me)
        count += 1
    return total / count - paid[me]


def line_of(pre, again):
    """tools/pnl.py's pre-flop label in plain words, seats merged except for a plain open; again: we raised twice"""
    if pre == "walk":
        return "no decision (all folded to our big blind)"
    head, _, tail = pre.partition(" > ")
    words = head.split()
    if words[0] == "fold":
        return FOLDS.get(words[1], "folded to a raise and a re-raise")
    if words[0] == "open":
        if tail == "fold" and again:
            return "opened, raised again, then folded"
        if tail:
            return "opened, then " + {"fold": "folded to a re-raise", "call 3bet": "called a re-raise",
                                     "4bet": "raised the re-raise"}.get(tail, tail)
        return OPENS.get(words[1], pre)
    if words[0] == "limp":
        return "limped" + (", then folded to a raise" if tail else "")
    if words[0] == "check":
        return "checked the big blind"
    if words[0] == "3bet":
        return "re-raised" + {"fold": ", then folded to another raise", "more": ", then put more in"}.get(tail, "")
    if head.startswith("call open"):
        return "called a raise" + (" from the big blind" if head.endswith("bb") else "") + (
            ", then folded to a re-raise" if tail else "")
    return {"call": "called", "raise": "raised"}.get(words[0], words[0]) + " a raise and a re-raise, cold"


def ended(h, me, events):
    for e in events:
        if e.player == me and e.act == "fold":
            return ENDS[e.street]
    if str(me) in (h.get("showdown") or {}):
        return ENDS[4]
    return ENDS[{0: 0, 3: 1, 4: 2}.get(len(h.get("board") or []), 3)]


def server_info(data, me):
    """the server's figures for the bot in this round; none when the file was fetched for another seat"""
    info = data.get("round")
    if not isinstance(info, dict) or data.get("seat") != me:
        return {}
    out = {k: info[k] for k in SERVER_NUMBERS if type(info.get(k)) in (int, float)}
    out["version"] = info.get("version") if type(info.get("version")) in (int, str) else None
    out["violations"] = bool(info.get("violations"))
    return out


def seat_names(names, team, seat):
    """names safe to print; a name on two seats gets its seat number, except ours at the file's own seat"""
    names = ["".join(ch if ch.isprintable() else "?" for ch in name) for name in names]
    ours = seat if type(seat) is int and 0 <= seat < len(names) and names[seat] == team else None
    return [name if names.count(name) == 1 or i == ours else "%s #%d" % (name, i) for i, name in enumerate(names)]


def read_round(path, team, need):
    with open(path) as f:
        data = json.load(f)
    players, hands = data["players"], data["hands"]
    if not hands or not isinstance(hands, list):
        raise ValueError("no hands")
    if not all(isinstance(p, str) for p in players):
        raise ValueError("odd list of players")
    twins = len(set(players)) != len(players)
    players = seat_names(players, team, data.get("seat"))
    if team not in players:
        return players
    me, n = players.index(team), len(players)
    info = server_info(data, me)
    ref = str(data.get("ref") or os.path.basename(path))
    rd = dict(ref=ref, file=os.path.basename(path), players=players, hands=len(hands), info=info, twins=twins,
              teams=[Counter() for _ in players], decisions=0, raw=0, fair=0.0, allins=0, allin_raw=0,
              unbalanced=0, lines=defaultdict(lambda: [0, 0]), ends=defaultdict(lambda: [0, 0]))
    run, longest, decided, busy = [0] * n, [0] * n, [0] * n, [0] * n
    for h in hands:
        res = h["results"]
        if len(res) != n:
            raise ValueError("hand %s has %d results for %d seats" % (h.get("n"), len(res), n))
        rd["unbalanced"] += sum(res) != 0
        events = classify(to_history(h), h.get("bb", BB), n=n)
        stats, acted, paid_in = seat_stats(h, events, me)
        for i in range(n):
            rd["teams"][i].update(stats[i])
            if i in acted:
                decided[i] += 1
                busy[i] += i in paid_in
                run[i] = 0 if i in paid_in else run[i] + 1
                longest[i] = max(longest[i], run[i])
        rd["decisions"] += sum(1 for e in events if e.player == me)
        rd["raw"] += res[me]
        fair = allin_fair(h, me, "%s/%s" % (ref, h.get("n"))) if "luck" in need else None
        rd["fair"] += res[me] if fair is None else fair
        if fair is not None:
            rd["allins"] += 1
            rd["allin_raw"] += res[me]
        if "lines" in need:
            again = sum(1 for e in events if e.player == me and e.street == 0 and e.act == "raise") > 1
            for group, key in ((rd["lines"], line_of(label(h, me, n, ())[1], again)),
                               (rd["ends"], ended(h, me, events))):
                group[key][0] += 1
                group[key][1] += res[me]
    rd["quiet"] = list(zip(longest, run, decided, busy))
    return rd


def read_all(folder, prefix, team, need):
    """the usable rounds in order, a note per file left out, and the round numbers the file names carry"""
    rounds, notes, away = [], [], []
    paths = sorted(glob.glob(os.path.join(glob.escape(folder), glob.escape(prefix) + "*.json")), key=natural)
    for path in paths:
        try:
            rd = read_round(path, team, need)
        except Exception as err:
            rd = False
            notes.append("skipped %s: %s: %s" % (os.path.basename(path), type(err).__name__, str(err)[:80]))
        if isinstance(rd, dict):
            rounds.append(rd)
        elif rd is not False:
            away.append(rd)
    if away:
        notes.append("%d of %d files left out: %s was not at the table. The latest of them has: %s" % (
            len(away), len(paths), team, ", ".join(name[:24] for name in away[-1][:10])))
    twins = sum(rd["twins"] for rd in rounds)
    if twins:
        notes.append("%s one name on two seats: those are shown as 'name #seat'" % (
            "%d file%s" % (twins, " has" if twins == 1 else "s have")))
    numbers = [round_number(path) for path in paths]
    return rounds, notes, [] if away or None in numbers else numbers


def merged(rounds):
    """per team name over these rounds: its counts, the rounds it sat in, its longest quiet run"""
    teams = {}
    for rd in rounds:
        for i, name in enumerate(rd["players"]):
            t = teams.setdefault(name, dict(c=Counter(), rounds=0, quiet=(0, "", 0, 0), tail=0, per_round={}))
            t["c"].update(rd["teams"][i])
            t["rounds"] += 1
            t["per_round"][rd["file"]] = rd["teams"][i]["net"]
            longest, tail, decided, busy = rd["quiet"][i]
            t["quiet"] = max(t["quiet"], (longest, short_ref(rd["ref"]), decided, busy))
            t["tail"] = tail
    return teams


def ranked(teams):
    return sorted(teams, key=lambda name: (-teams[name]["c"]["net"], name))


def gap_lines(rounds, team, left, of):
    teams = merged(rounds)
    order = ranked(teams)
    if len(order) < 3:
        return ["Fewer than three teams: no gap to show."]
    place = order.index(team) + 1
    ahead = place <= 2
    rival = order[2] if ahead else order[1]
    gap = bb(teams[team]["c"]["net"] - teams[rival]["c"]["net"])
    out = ["We are %s of %d. %s place (%s) is %.0f bb %s." % (
        ordinal(place), len(order), "Third" if ahead else "Second", rival, abs(gap),
        "behind us" if ahead else "ahead of us")]
    if left:
        each = abs(gap) / left
        hundreds = sum(rd["hands"] for rd in rounds) / len(rounds) / 100
        out.append("%d of %d rounds remain: we %s %.0f bb a round (%.1f bb/100) %s them%s." % (
            left, of, "can lose" if ahead else "must gain", each, each / hundreds, "to" if ahead else "on",
            " and still finish ahead" if ahead else " to catch up"))
    else:
        out.append("No rounds remain of %d." % of)
    mine, theirs = teams[team]["per_round"], teams[rival]["per_round"]
    diffs = [bb(mine[r] - theirs[r]) for r in mine if r in theirs]
    if len(diffs) >= 3:
        mean = sum(diffs) / len(diffs)
        sd = (sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)) ** 0.5
        out.append("So far we %s %.0f bb a round on them on average, give or take %.0f in any one round (%s)." % (
            "gain" if mean >= 0 else "lose", abs(mean), sd, plural(len(diffs), "round")))
        if left and sd:
            from statistics import NormalDist
            spread = sd * left ** 0.5
            signed = bb(teams[team]["c"]["net"] - teams[rival]["c"]["net"])
            out.append("Over the %d left, chance alone moves the gap by about %.0f bb (one standard deviation): "
                       "one time in six it moves more than that against us." % (left, spread))
            out.append("Chance we end ahead of %s: about %.0f%% if the two bots are even from here, %.0f%% if the "
                       "average so far continues. Other teams are not counted." % (
                           rival, 100 * NormalDist().cdf(signed / spread), 100 * NormalDist().cdf((signed + mean * left) / spread)))
    if any(set(rd["players"]) != set(rounds[0]["players"]) for rd in rounds):
        out.append("The table changed between rounds, so teams played different rounds: not a fair ranking.")
    return out


def table(rounds, every, numbers, team, of):
    hands = sum(rd["hands"] for rd in rounds)
    part = "" if len(rounds) == len(every) else " (the last %d of %d)" % (len(rounds), len(every))
    print("%s read%s, %s to %s, %d hands" % (
        plural(len(rounds), "round"), part, short_ref(rounds[0]["ref"]), short_ref(rounds[-1]["ref"]), hands))
    have = {round_number(rd["file"]) for rd in every}
    missing = sorted(set(range(1, max(numbers) + 1)) - have) if numbers else []
    if missing:
        more = " and %d more" % (len(missing) - 12) if len(missing) > 12 else ""
        print("No usable file for round%s %s%s: the standings leave %s out." % (
            "s" if len(missing) > 1 else "", ", ".join(map(str, missing[:12])), more,
            "them" if len(missing) > 1 else "it"))
    left = max(0, of - max(numbers + [len(every)]))
    teams = merged(rounds)
    print("%5s  %-24s %6s %7s %9s %7s" % ("place", "team", "rounds", "hands", "total bb", "bb/100"))
    for k, name in enumerate(ranked(teams), 1):
        c = teams[name]["c"]
        print("%5d  %-24s %6d %7d %+9.0f %+7.1f%s" % (
            k, name[:24], teams[name]["rounds"], c["hands"], bb(c["net"]), per100(c["net"], c["hands"]),
            "  <- us" if name == team else ""))
    drift = sum(t["c"]["net"] for t in teams.values())
    if drift:
        print("Standings do not sum to zero: off by %+d chips." % drift)
    if part:
        print("Whole event so far, all %d rounds:" % len(every))
    for line in gap_lines(every, team, left, of):
        print(line)


def alerts(info):
    bad = [k for k in ("errors", "bank_out", "timeouts") if info.get(k, 0) > 0]
    bad += ["think_s"] if info.get("think_s", 0) > THINK_LIMIT else []
    bad += ["violations"] if info.get("violations") else []
    return "  ALERT " + ",".join(bad) if bad else ""


def show(info, key, width):
    value = info.get(key)
    return "%*s" % (width, "-" if value is None else "%.2f" % value if key == "think_s" else value)


def round_lines(rounds):
    print("%-10s %4s %7s %9s %8s %6s %8s %7s" % (
        "round", "ver", "bb/100", "decisions", "timeouts", "errors", "bank_out", "think_s"))
    versions = defaultdict(list)
    for rd in rounds:
        info = rd["info"]
        rate = per100(rd["raw"], rd["hands"])
        stored = info.get("bb100")
        differs = "  file says %+.1f" % stored if stored is not None and abs(stored - rate) > 0.01 else ""
        odd = "  %s not summing to zero" % plural(rd["unbalanced"], "hand") if rd["unbalanced"] else ""
        short = "  only %d hands" % rd["hands"] if rd["hands"] < info.get("hands", 0) else ""
        print("%-10s %4s %+7.1f %9d %s %s %s %s%s%s%s%s" % (
            short_ref(rd["ref"])[:10], show(info, "version", 4), rate, rd["decisions"], show(info, "timeouts", 8),
            show(info, "errors", 6), show(info, "bank_out", 8), show(info, "think_s", 7),
            alerts(info), differs, odd, short))
        versions[info.get("version")].append((rate, info.get("think_s")))
    for version in sorted(versions, key=lambda v: (not isinstance(v, int), v if isinstance(v, int) else str(v))):
        rates = [r for r, _ in versions[version]]
        thinks = [t for _, t in versions[version] if t is not None]
        k = len(rates)
        mean = sum(rates) / k
        se = "give or take %.1f" % ((sum((r - mean) ** 2 for r in rates) / (k - 1) / k) ** 0.5) if k > 1 else ""
        think = "%.2fs" % (sum(thinks) / len(thinks)) if thinks else "-"
        print("version %s: %s, mean %+.1f bb/100%s, mean think %s" % (
            "unknown" if version is None else version, plural(k, "round"), mean, se and ", " + se, think))


def luck(rounds):
    hands = sum(rd["hands"] for rd in rounds)
    raw = sum(rd["raw"] for rd in rounds)
    fair = sum(rd["fair"] for rd in rounds)
    pots = sum(rd["allins"] for rd in rounds)
    got = sum(rd["allin_raw"] for rd in rounds)
    print("as played            %+9.0f bb  %+7.1f bb/100  (%d hands)" % (bb(raw), per100(raw, hands), hands))
    print("all-in luck removed  %+9.0f bb  %+7.1f bb/100" % (bb(fair), per100(fair, hands)))
    size = round(abs(bb(raw - fair)), -1)
    side = "either way" if not size else "in our favour" if raw > fair else "against us"
    print("luck: about %.0f bb %s, from %s where everyone left was all-in before the river" % (
        size, side, plural(pots, "pot")))
    print("in them we won %+.0f bb; averaged over the cards still to come they were worth %+.0f bb" % (
        bb(got), bb(got - raw + fair)))
    print("All-ins before the flop are sampled, so the luck figures are good to about 20 bb.")


def quiet_text(t):
    longest, where, decided, busy = t["quiet"]
    if longest < QUIET:
        return "%d" % longest
    # how often it enters outside the run, so a bot that died does not look tight
    rate = busy / max(decided - longest, 1)
    # the chance that a team entering this rarely strings such a run together in one round
    by_itself = decided * rate * (1 - rate) ** longest >= 0.01
    return "%d in %s QUIET%s%s" % (longest, where, " NOW" if t["tail"] >= QUIET else "",
                                  ", but it plays few hands" if by_itself else "")


def opponents(rounds, team):
    teams = merged(rounds)
    print("%-16s %6s %7s %3s %3s %3s %9s %9s %9s %3s %9s %5s %12s  %s" % (
        "team", "hands", "bb/100", "in", "pfr", "3b", "f3b(n)", "cbet(n)", "fold(n)", "sd", "won(n)", "shv/k",
        "we won bb(n)", "longest quiet run"))
    names = sorted(teams, key=lambda name: (name != team, -teams[name]["c"]["hands"], -teams[name]["c"]["net"]))
    for name in names:
        t, c = teams[name], teams[name]["c"]
        versus = "%+.0f(%d)" % (bb(c["vs_net"]), c["vs_n"]) if name != team else "us"
        print("%-16s %6d %+7.1f %s %s %s %s %s %s %s %s %5.1f %12s  %s" % (
            name[:16], c["hands"], per100(c["net"], c["hands"]), pct(c["vpip"], c["hands"]),
            pct(c["pfr"], c["hands"]), pct(c["tb"], c["tb_opp"]), pct_n(c["f3"], c["f3_opp"]),
            pct_n(c["cb"], c["cb_opp"]), pct_n(c["fb"], c["fb_opp"]), pct(c["sd"], c["flops"]),
            pct_n(c["sdwon"], c["sd"]), 1000.0 * c["shove"] / c["hands"], versus, quiet_text(t)))
    print("All rates are percentages. Of all hands: in, put chips in before the flop by choice; pfr, raised before the flop.")
    print("3b: re-raised when facing one raise. f3b: folded to a re-raise after raising first.")
    print("cbet: bet the flop when nobody had, as the last raiser before it. fold: folded to a flop bet.")
    print("sd: reached showdown, of flops seen. won: won at showdown. shv/k: all-in raises before the flop per 1,000 hands.")
    print("we won: OUR result in bb, in the hands where both it and we put chips in by choice (others may be in too).")
    print("longest quiet run: hands in a row with a decision and only checks or folds. QUIET: %d or more," % QUIET)
    print("the server may be playing for it; 'plays few hands' if a team that tight gets there by itself.")
    print("NOW: still quiet when its latest round ended.")


def groups(title, merged_groups, hands, order=None):
    print("%-44s %6s %8s %9s" % (title, "hands", "bb/100", "bb a hand"))
    keys = order or sorted(merged_groups, key=lambda k: merged_groups[k][1])
    for key in keys:
        count, chips = merged_groups.get(key, (0, 0))
        if count:
            print("%-44s %6d %+8.1f %+9.2f" % (key, count, per100(chips, hands), bb(chips) / count))


def lines(rounds):
    hands = sum(rd["hands"] for rd in rounds)
    for field, title, order in (("lines", "before the flop we...", None), ("ends", "for us the hand ended...", ENDS)):
        total = defaultdict(lambda: [0, 0])
        for rd in rounds:
            for key, (count, chips) in rd[field].items():
                total[key][0] += count
                total[key][1] += chips
        groups(title, total, hands, order)
    print("bb/100 is the line's share of our overall %+.1f bb/100; each list adds up to it. Worst first." % per100(
        sum(rd["raw"] for rd in rounds), hands))
    print("Folding always costs the blinds; watch a line that should win and does not.")


def changed(a, b):
    if not a["hands"] or not b["hands"]:
        return ""
    for key in ("vpip", "pfr"):
        p, q = a[key] / a["hands"], b[key] / b["hands"]
        pooled = (a[key] + b[key]) / (a["hands"] + b["hands"])
        se = (pooled * (1 - pooled) * (1 / a["hands"] + 1 / b["hands"])) ** 0.5
        if abs(p - q) >= 0.04 and se and abs(p - q) / se >= 3:
            return "  CHANGED?"
    return ""


def halves(rounds, team):
    if len(rounds) < 2:
        print("Needs two rounds or more.")
        return
    cut = len(rounds) // 2
    first, second = merged(rounds[:cut]), merged(rounds[cut:])
    print("first half: %s to %s (%s). second half: %s to %s (%s)." % (
        short_ref(rounds[0]["ref"]), short_ref(rounds[cut - 1]["ref"]), plural(cut, "round"),
        short_ref(rounds[cut]["ref"]), short_ref(rounds[-1]["ref"]), plural(len(rounds) - cut, "round")))
    print("%-16s | %6s %7s %3s %3s | %6s %7s %3s %3s" % (
        "team", "hands", "bb/100", "in", "pfr", "hands", "bb/100", "in", "pfr"))
    empty = dict(c=Counter())
    both = merged(rounds)
    names = sorted(both, key=lambda name: (name != team, -both[name]["c"]["hands"], -both[name]["c"]["net"]))
    for name in names:
        a, b = first.get(name, empty)["c"], second.get(name, empty)["c"]
        cells = ["%6d %+7.1f %s %s" % (c["hands"], per100(c["net"], c["hands"]), pct(c["vpip"], c["hands"]),
                                      pct(c["pfr"], c["hands"])) if c["hands"] else "%6s %7s %3s %3s" % (
                                          "-", "-", "-", "-") for c in (a, b)]
        print("%-16s | %s | %s%s" % (name[:16], cells[0], cells[1], changed(a, b)))
    print("CHANGED?: 'in' or 'pfr' moved by 4 points or more, beyond chance: a new bot, or a reaction to the table.")


def main():
    ap = argparse.ArgumentParser(description="One report over every round file in a hands directory.")
    ap.add_argument("hands_dir")
    ap.add_argument("--prefix", default="sunday_s1_", help="file name prefix of the rounds to read")
    ap.add_argument("--team", default="Gherkers")
    ap.add_argument("--last", type=int, default=0, metavar="N", help="report on the latest N rounds only")
    ap.add_argument("--sections", default=",".join(SECTIONS), help="comma-separated, from: " + ", ".join(SECTIONS))
    ap.add_argument("--of", type=int, default=36, metavar="ROUNDS", help="rounds in the whole event")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")
    want = [s.strip() for s in a.sections.split(",") if s.strip()]
    unknown = [s for s in want if s not in SECTIONS]
    if unknown:
        ap.error("unknown section %s; choose from %s" % (", ".join(unknown), ", ".join(SECTIONS)))
    every, notes, numbers = read_all(a.hands_dir, a.prefix, a.team, set(want))
    for note in notes:
        print(note)
    if not every:
        print("No usable round files match %s*.json in %s." % (a.prefix, a.hands_dir))
        names = os.listdir(a.hands_dir) if os.path.isdir(a.hands_dir) else []
        there = sorted({re.sub(r"\d+\.json$", "", name) for name in names if round_number(name) is not None})
        if there and not notes:
            print("Round files there start with: %s. Pass one as --prefix." % ", ".join(there[:8]))
        return 1
    rounds = every[-a.last:] if a.last > 0 else every
    run = {"table": lambda: table(rounds, every, numbers, a.team, a.of), "rounds": lambda: round_lines(rounds),
           "luck": lambda: luck(rounds), "opponents": lambda: opponents(rounds, a.team),
           "lines": lambda: lines(rounds), "halves": lambda: halves(rounds, a.team)}
    for name in SECTIONS:
        if name in want:
            print("\n== %s ==" % name)
            run[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
