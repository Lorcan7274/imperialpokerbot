# Sparring: where the live build is weak against balanced play

Live build: `bot_v6l.py`. Sparring bots: `theory`, `theory_agg`, `theory_tight` (arena/theory.py, from theory.patch).
All simulated figures have all-in luck removed. Real hands: 54 Saturday rounds (builds 9 to 28, so mostly older than the live build).

## Level (8 seats, 1,000-hand rounds)

| table (7 opponents) | rounds | live build, bb/100 | standard error |
|---|---|---|---|
| `theory*7` | 36 | -11.3 | 4.2 |
| `theory*3,theory_agg*2,theory_tight*2` | 36 | -10.6 | 4.1 |
| `@a*3,theory*2,theory_agg,theory_tight` | 24 | -13.8 (its three copies -8.0; all four -9.5) | 4.2 |

At the last table theory made +12.6, theory_agg +8.8, theory_tight +3.9. The live build loses about 10 bb/100 to a balanced table, far from the "beaten by 50" case, and this is stable across the three tables.

For scale, in the real rounds hands whose main opponent was one of the eight strong teams gave +2.8 of our +43.4 bb/100 (26% of hands). We lost chips to Lehman Brothers (-161 bb), Resonance Qt (-134 bb) and The Market Makers (-100 bb) and won from the other five.

## Where the 11 bb/100 goes (72,000 hands at the two theory tables)

Contribution to bb/100: opens +4.1 (blinds taken +8.3, called +0.9, re-raised -5.1), our 3-bets +2.4, cold calls -3.2, blind calls -1.9, blinds folded -13.0.
A theory seat at the same table makes +7.5 from opens and +6.7 from 3-bets. The gap is after the flop, not before it.

## Leaks, ranked

### 1. Raising flop bets (large in simulation, absent in real hands: low confidence)
- Simulation: 786 flop raises, -4.75 +-2.0 bb/100. We raise 51% of the flop bets we face (theory seats raise 9%). Theory folds 40% and continues 60%; when it continues we average -12.6 bb.
- Real: 906 raises, +6.6 bb each (+11.1 bb/100). Against the strong teams 200 raises, +3.7 bb each, and they folded 61%. No strong team defended like theory (Lehman folded 48%, Anker 40%, the rest 58 to 77%).
- Reason: theory bets 0.33 and 0.5 pot on the flop, the sizes the real field uses with weak hands, and the bot assumes 60% folds to a raise. It raises one pair and air for a pot-sized amount into a range that is not weak.
- Typical: KcTc calls an open, flop Kd9h4h, bet 71, we raise to 343, called by Ah6h, turn 3h, we bet 269, face a shove, fold: -33 bb. AcJs on Jd8h2h raises 71 to 234, called by QQ, bets turn, checks river: -24 bb.

### 2. Continuing against a 3-bet after we open (same sign in real hands: medium confidence)
- Real, strong teams: 341 re-raises of our opens, -4.3 bb each, worse than folding every time (-3.5). Calls -6.5 bb (119), 4-bets -2.3 bb (63). Worst: Attention Is All In -11.6 (33), Resonance Qt -10.7 (28), Lehman Brothers -8.7 (70). Against other teams +1.2 bb each.
- Simulation: calls -3.0 bb at the theory tables (423), -4.8 at the all-theory table, -5.7 with our own copies seated (176). About the same as folding, never clearly better.
- None of the differences from folding is statistically significant on its own (real: +-5 bb on 119 calls).

### 3. Turn bets of 0.7 pot (thin real evidence: low to medium confidence)
- Simulation: 415 second barrels of 0.7 pot, -3.07 +-1.4 bb/100; called 56% of the time for -11.5 bb.
- Real: +4.3 bb each overall (139); against strong teams -4.3 bb (27 hands, not significant).
- Our 0.7-pot bets are our weakest hands: made-hand percentile on the turn 0.53 against 0.77 (0.33 pot) and 0.78 (1.1 pot) in simulation; 0.59 against 0.65 and 0.70 in real hands. A team that reads sizes can use this; theory cannot, it just calls enough.

### 4. Checking the flop as the pre-flop raiser means giving up (low to medium)
- Simulation: 1,086 checks, -3.7 bb each (-5.6 bb/100); a theory seat's own checks lose -0.8. Real: +0.2 overall, -2.1 against strong teams (123).

### 5. Third-pot flop continuation bets (low)
- Simulation: 746 bets, -2.4 +-1.5 bb/100, called 67%. Real: +4.3 bb each, +6.1 against strong teams.

### 6. Cold calls of opens (low)
- Simulation: -3.2 +-2.1 bb/100 (-1.8 bb each; -0.4 at the all-theory table). Real: +4.4 bb each, +1.1 against strong teams (241).

## Checked and not leaks
- Folding to bets: against theory's real hands our folded hands had 0.17 / 0.21 / 0.20 equity on flop / turn / river where the price needed 0.23 / 0.28 / 0.30.
- Calling bets, measured against folding at that point: flop -0.4 bb per call (break-even), turn +4.7, river +10.5. In real hands +16.5 / +34 / +49. Flop calls are the thin ones, as on Saturday.
- River bets: called by theory we win 55% heads-up (62% against real strong teams); only one river bet in ten is a weak made hand.
- Folding a flop bet to a raise: 335 folds with 0.36 equity against a price of 0.29, marginal once later bets are counted.
- Blind defence: big-blind calls -0.7 bb against -1.0 for folding; 3-bets from the blinds +1.3 bb.

## Smallest fixes (not applied)
- Leak 1, `Bot._postflop` in pokerbot/bot.py, the raise loop under "facing a bet" (`response("p_vs_raise", ...)`): count across the whole table how many of our post-flop raises were folded to (two counters in `Model.observe`), and once six have been seen cap each opponent's fold frequency at the table's rate plus 0.10. At Saturday's 60% nothing changes; at a table that folds 40% the raise stops being chosen. Danger: the hands that no longer raise fall through to call, which is the change that lost money live. A/B it on the weak-field tables too and watch the flop-call line.
- Leak 2, `Bot._preflop`, branch `len(raises) == 2`: nothing proposed beyond the offsuit cut already released; the real sample is too small to justify more.
- Leaks 3 to 6: no change proposed; real hands do not support them.

## Fields for judging a candidate against the live build
```
--field "theory*7"
--field "theory*3,theory_agg*2,theory_tight*2"
--field "@a*3,theory*2,theory_agg,theory_tight"
--field "theory,theory_agg,theory_tight,balanced,real_ee,lag,adaptive"
```
One round's standard deviation is 21 to 25 bb/100, so use at least 24 rounds per table. Keep the existing weak-field tables as the guard: every leak above is a play that earned chips in the real rounds.

## Files
- Recorded hands (96 rounds, tools/pnl.py shape, plus `allhole` and `fair`): `night/spar/probe/sim/`
- `probe/record.py` (recorder), `probe/split.py` (line split, simulated and real side by side), `probe/teams.py` (answers to our aggression per team)
- Outputs: `probe/split_all.txt`, `probe/split_vs_theory.txt`, `probe/teams.txt`, `probe/level_*.txt`
