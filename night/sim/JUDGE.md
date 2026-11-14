# Judging a candidate bundle against bot_v6l.py

All numbers are bb/100 with one standard error, all-in luck removed, paired on identical cards.
`S` = /tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad

## Setup (once, in a worktree; nothing under pokerbot/ is touched)

    git apply $S/night/sim/clones_audited.patch
    git apply $S/night/sim/judge.patch        # adds arena/backtest.py and arena/judge.py

## The one command

    python3 arena/judge.py --base $S/bot_v6l.py --cand <new bundle> --procs 2

About 12 minutes on two free cores, 22 on one (`--procs 1`). `--only late,final` skips self-play (5 minutes).
`--scale 2` doubles every test's rounds and cuts each standard error by 0.7.

| test | tables | paired rounds | standard error | the candidate is WORSE if |
|---|---|---|---|---|
| late | nine clone tables seated like rounds 41, 45, 46, 48, 49, 52 (8 seats), 53, 54, 31 (7 seats) | 9 x 40 | 1.6 | below -3.5 |
| final | the seven named top teams as clones | 80 | 3.5 | below -7 |
| self | the candidate among 7 copies of v6l, and v6l among 7 copies of the candidate, averaged | 2 x 50 | printed 2, really about 4 (see below) | below -7 |
| mix | 3 copies of v6l plus the Attention, FisherMen, Kojack, Resonance clones | 60 | 3.3 | below -7 |
| behaviour | on the late tables: share of flop / turn / river bets called, share of re-raises of our open called | | | up by more than 2 / 3 / 4 / 3 points on v6l's 25 / 44 / 56 / 36 % |

The script prints each difference, its standard error, where it came from (showdown, pots won without one, hands
where we called a flop or turn bet, hands where our open was re-raised, hands where our flop bet was raised) and a
verdict line.

## Decision

1. Any "WORSE" line: do not ship.
2. A "calls more" flag: do not ship unless the real hands give a reason for the extra calls. Both calling leaks
   we had live would have been flagged (v6.4/v6.5: flop +3 to +5, turn +6 to +8, river +6 to +8 points; v6.6:
   re-raises called 47.5% against 35.7%), and no chip test here prices extra calls correctly.
3. No lines at all ("no test separates..."): the candidate is not shown to be better. Ship it only if it fixes
   something measured on the real hands; otherwise keep v6l, whose +15.1 over 14 real rounds is the only real
   number we have.
4. "better on late/final/mix" counts only when the gain is in pots won without showdown or before the flop. The
   clone field pays us +32 at showdown where the real field paid +14 (rounds 41-54), so gains from value bets and
   calls are inflated. "better on self" alone is not a reason to ship.
5. Never read an absolute level: v6l makes +30.5 at the late clone tables against +15.1 live, and +37 against the
   final-table clones where live it made about 0 to +2 from each of those teams.

## What the backtests showed (why the rules are this cautious)

| known live change | live evidence | late clone tables | old hand-written field | self-play |
|---|---|---|---|---|
| v6.3 -> v6.5 calls more flop and turn bets, did worse | v6.5: -11 over 3 rounds (se 23), 54 called hands lost 12 bb/100. v6.4, same calling code: +63 over 3 rounds | +0.6 (se 1.7); v6.4 +1.6 (1.7). Final table +6.7 (3.8) | +9.0 (3.8); v6.4 +10.7 (4.8): wrongly better | +0.6 (2.3) |
| v6.1 -> v6.2 stops losing to WBot | against WBot -27, -5, then +36, -18 (one round each) | +1.1 (1.8) at 7 WBot tables; against the WBot clone v6.1 already wins 11.5 | +0.4 (4.8) | -1.5 (2.8) |
| v6.6 -> v6.7 calls fewer re-raises | re-raised opens cost 13.9 (se 7.0, 4 rounds), then 3.0 (se 2.6, 14 rounds) | 0.0 (1.5); re-raised hands -0.5 (0.8) | -1.2 (3.9) | among v6l copies four blocks of 50 rounds: +5.5, +4.1, +3.7, -9.1 (each se 2.5); +0.8 (2.9) and -1.4 (2.5) among v6.3 and v6.1 copies; +0.8 among v6.6 copies |
| level of v6l, rounds 41-54 | +15.1 (se 7.0) | +30.5 | +114 | 0 by construction |

- The clone tables reproduced none of the three live changes; each came out as zero within two standard errors.
  They did stop the old field's false "better" on the calling change. They are a check against breaking
  something, not a way to find 3 bb/100.
- What the clone tables do get right is how often we do things (re-raises called: 47.5% -> 35.7% simulated,
  41% -> 31% live). Use them to see what a candidate does differently, then ask whether the real hands say that
  is good.
- The live evidence itself is thin: one live round has a standard error near 27, so three rounds cannot separate
  builds; v6.4 and v6.5 together averaged +26 over six rounds, no worse than v6.6/v6.7 (+18 over 18).
- Self-play reproduced none of the three either, and its standard errors are too small: four blocks of 50 rounds
  of the same comparison (v6.7 against v6.6 among v6l copies) gave +5.5, +4.1, +3.7 and -9.1, each printed with a
  standard error of 2.5. The cause was not found (rounds are reproducible and do not depend on what ran before).
  Until it is, a self-play difference under about 7 means nothing. Among v6.1, v6.3 and v6.7 no order holds
  across tables (each table of copies favoured a different build, all within that noise).

## The same tests by hand

    python3 arena/abtest.py --a $S/bot_v6l.py --b <new bundle> --field <field> --rounds 40 --seed 90000 --procs 1

abtest.py prints "±" as a 95% interval: divide by 1.96 to get the standard error used above. Fields:

    clone_astra,clone_red,clone_wbot,clone_kojack,clone_claudebot,clone_lehman,clone_sars
    clone_anker,clone_pokermon,clone_equity,clone_resonance,clone_lehman,clone_pokebot,clone_sars
    clone_munchlax,clone_lehman,clone_jumpstreet,clone_fishermen,clone_equity,clone_matcha,clone_pokebot
    clone_attention,clone_test,clone_kaiserbot,clone_pokebot,clone_matcha,clone_aivey,clone_claudebot
    clone_equity,clone_smartbger,clone_ailin,clone_munchlax,clone_attention,clone_aivey,clone_resonance
    clone_astra,clone_fishermen,clone_joca,clone_nd,clone_munchlax,clone_bigroddy,clone_red
    clone_kojack,clone_anton,clone_fishermen,clone_nd,clone_gamblerlove,clone_pokermon
    clone_anton,clone_nd,clone_clanker,clone_aivey,clone_attention,clone_supernut
    clone_sars,clone_pokermon,clone_field,clone_kaiserbot,clone_smartbger,clone_joca
    final (80 rounds): clone_attention,clone_marketmakers,clone_resonance,clone_anker,clone_fishermen,clone_equity,clone_kojack
    self (50 rounds each): @a*7 with --a v6l --b candidate, then @a*7 with --a candidate --b v6l (flip the sign)
    mix (60 rounds): @a*3,clone_attention,clone_fishermen,clone_kojack,clone_resonance

A single table of 40 rounds has a standard error of 4 to 6: read the nine together, never one alone.

## Where the backtest data is

`$S/night/sim/bt/`: `res_*.jsonl` (every simulated round, tagged), `live.json` (the 54 real rounds, same tags),
`pool.py` (differences per test), `level.py` (simulated against live by situation), `calls.py` (per team: hands
where we called its bet), `tableadj.py` (live results per build), `jobs.py` (what was run).
