# Gone players: what was built, what it is worth, what to upload

For the 08:30 UTC decision. Written 01:10 UTC, Sunday 15 Nov.

## The decision in short

- **Adopt the patch.** It is a narrowed version of what the reviewers saw. It cannot change a decision unless every opponent left in the hand has been silent for 60 hands.
- **It will most likely do nothing on Sunday.** No opponent went silent on Saturday. It pays only in a final with a flat 10 s bank, and only once every other bot has run dry while we have not.
- **Ask the organisers first thing whether the final's bank is 10 s in total or grows with the hands.** The FINAL setting depends on the answer (last section).

## What the feature does, in five lines

1. For each opponent the bot counts hands in a row in which that player had a decision and only checked or folded. At 60 the player is "gone". One call or raise makes it live again at once, also inside the current hand.
2. If every opponent still in the hand is gone, the bot makes the smallest legal raise with any two cards before the flop, or the smallest bet after the flop when nobody has bet.
3. In every other spot the bot plays exactly as before. A gone player sitting beside a live one changes nothing.
4. A bot the server plays for folds to any bet, so the smallest raise wins the blinds: 1.5 big blinds on 7 of 8 hands, 131 bb/100 at an 8-seat table.
5. The cost is one counter per seat. No extra thinking, and no extra decisions for the server to charge.

## What changed since the reviewers looked

The reviewed patch did one more thing: while live players were still in the hand, it left gone players out of its reckoning (opening widths, steals, re-raises, ranges). The reviewers found four problems, all in that part. I reproduced each one, then removed that part.

| problem | reproduced on the reviewed patch | with the final patch |
|---|---|---|
| Decisions against the starter bot changed (junk opens with 9-4 and 3-2 offsuit while the live team Joca was flagged) | 5 of 69,837 real decisions differ, all in round 18 | 0 of 69,837 differ |
| After the flop it could shove with a flagged player still in the pot | 12 of 58 probe decisions differ, three all-ins of 1,980 into a pot of 80 | 31 of 31 probe decisions match a copy that flags nobody |
| It spent our own time bank faster while opponents died | bank died 43 (se 31), 71 (se 27) and 163 (se 36) hands earlier in three grid cells; 134 and 69 more decisions on two 5,000-hand tables | +5 (se 29), -6 (se 26) and -29 (se 22) hands; -14 and +3 decisions |
| It lost chips when only some opponents were gone (grid: -119 bb per table, se 50) | not reproduced cleanly: -31 (se 43) and +37 (se 119) bb per table in my re-runs of two of the three cells | cannot occur: play is the same as the base unless everyone left in the hand is flagged |

The last row matters for how to read the grid. The harness is noisy: the final patch, which is the base in those hands, measured -47 (se 43) and +51 (se 95) against the base there.

## What was given up by narrowing

The removed part did earn chips when many players were dead and one or two were not.

| scenario | reviewed patch | final patch |
|---|---|---|
| All seven die at hand 500, weak field, 20 rounds | +31.6 (se 0.7) bb/100 | +31.2 (se 0.7) bb/100 |
| Three of seven die at hands 200, 500, 700, weak field, 60 rounds | +6.1 (se 2.1) bb/100 | 0.0, identical hand for hand in 60 of 60 |
| Seven die one by one between hands 3,000 and 4,800, weak field, 8 tables of 5,000 hands | +10.0 (se 1.1) bb/100, about +500 bb per table | +2.9 (se 0.4) bb/100, about +143 bb per table |
| Flat 10 s bank race, strong field, every opponent runs dry by hand 4,400, 10 tables | +705 (se 66) bb per table | +190 (se 114) bb per table |
| Same race, two or three opponents outlive us, 10 tables | +144 (se 151) | -18 (se 193) |

So the final patch keeps the whole gain when everyone dies quickly, about a quarter to a third of it when they die slowly, and nothing while a live player remains.

A wider version could win most of this back: the reviewed patch, limited to before the flop, with the starter-bot rule left alone. The reviewers proposed both fixes. Nobody has built or reviewed that combination, and it still spends our bank faster. I did not build it. If the organisers confirm a flat bank, it is worth an hour of someone's morning; otherwise leave it.

## What was measured on the final patch

**Real hands (Saturday, 54 rounds, 69,837 of our decisions)**

- Decision by decision against the live build: 0 differ. 27 decisions had a flagged opponent in the hand; none had every opponent flagged.
- Replay at 4 times this machine's CPU time: exceptions 0 and illegal answers 0 in every round, starter flags all match, 0.96 s of the 10 s bank per round.
- The same two checks on the Sunday candidate plus this patch: 0 differ, exceptions 0, illegal answers 0, all match.

**Simulations against the live build, same cards, all-in luck removed**

- Nobody dies, solid 7-handed field, 40 rounds: identical hand for hand in 40 of 40. 44 of 48,682 decisions carried a flag, 1 had every opponent flagged.
- Nobody dies, 8-handed field, 40 rounds: identical in 40 of 40. 27 flagged decisions, 0 with every opponent flagged.
- Everyone gone from hand 1: +127.3 bb/100 against the base's +126.0; 131 in every 100-hand block from hand 101. The ceiling is 131.25.
- Everyone dies at hand 500: 131 bb/100 in every 50-hand block from hand 601. The base stays at 48 to 69.

**Strict checks (bugs are not swallowed)**

- 16 unit tests pass; 18 with the Sunday candidate's patch on top.
- Load check: 98,697 bytes, strict errors none.
- About 115,000 fuzzed decisions with opponents dying, waking and dying mid-hand, 2 to 10 seats: 0 exceptions, 0 illegal answers. The reviewers' roughly 200,000 on the reviewed patch also found none; the branch that is left is unchanged from what they tested.

**Bank race (5,000 hands, 10 s flat bank for every seat, strong stand-in field, live pacing)**

- Every opponent runs dry (10 tables): we were alive for 274 hands after the last one died and made +119 bb/100 there, against the base's +60. Whole table +190 (se 114) bb; the two late phases alone +297.
- Two or three opponents outlive us (10 tables), and two die early (8 tables): no difference from the base beyond noise.
- 84 tables in all: exceptions 0, illegal answers 0, no decision over 25 ms.

## What it costs when nobody goes silent

Nothing that could be measured. 80 of 80 simulated rounds were identical to the base hand for hand, and no real decision changed. The new check takes under 3 microseconds per decision.

## What it earns when players do

- While even one live opponent is still in the hand: nothing. The base already steals from dead blinds when only they are left behind it.
- Once every other bot is gone and ours is not: about +60 to +70 bb/100 more than the base, up to the ceiling of 131. That is about 3 to 3.5 bb per 5 hands, or +300 to +350 bb if it lasts 500 hands.
- It takes about 70 hands after a death to flag a player.
- In a real final other survivors will also steal. The stand-in opponents never do, so these figures are upper bounds.

## False positives on Saturday's real opponents

- 348 opponent-rounds, 54,000 hands. At the threshold of 60, one opponent-round was flagged: the team Joca in round 18, three times, for 10, 46 and 3 hands. Joca put chips in on 4.4% of hands.
- First half of the day (rounds 1 to 27): 1 flagged opponent-round. Second half: 0.
- The next longest quiet runs were 56, 53, 52, 52 and 50 hands. None reaches 60.
- With the final patch a false flag only matters if every opponent left in the hand is flagged. That happened 0 times in 69,837 real decisions. If it does happen, the cost is a raise to 40 chips with a random hand; if the player calls or raises it is live again and normal play takes over.
- At a threshold of 40 there were 25 flags on 16 opponent-rounds across 8 teams. Keep 60.

## Agent.FINAL: what to upload

FINAL exists in the Sunday candidate (night/candidate.patch), not in the live v6.7. It only matters on tables longer than 1,000 hands, so it does not touch the bucket rounds. "scaled" thinks deeply all the way. "flat" pins the shallowest real thinking (16 trials) to make a 10 s bank last.

The pacing numbers below come from the reviewers' grid, which used the reviewed patch. I did not re-run deep or flat pacing with the final patch.

| organisers say | upload | why |
|---|---|---|
| The bank is flat (10 s for all 5,000 hands) | FINAL = "flat" | With deep thinking our bank ran dry at hand 3,790 to 4,030; with flat pacing at 4,300 to 4,760 (transport 1.3 ms). Where every opponent ran dry, flat beat deep by +632 (se 156) bb per table, and deep was never alive after the last opponent died. Elsewhere flat was 97 to 266 bb behind as measured, 10 to 192 after the grid's correction for early-hand noise (se about 130). The patch only pays in the phase that flat pacing reaches and deep pacing does not. |
| The bank is scaled (50 s) | FINAL = "scaled" | No bank ran dry on any 50 s table. Deep thinking was worth +7.2 (se 3.0) bb/100 over flat pacing, about +360 bb per table. The patch then does nothing and costs nothing. |
| Nothing | FINAL = "scaled", by a thin margin | If the bank is scaled, "flat" gives away about 360 bb (se 150). If it is flat, "scaled" loses only when nearly every opponent runs dry before about hand 4,000: 630 to 710 bb in the grid with the reviewed patch, by my estimate about 500 with the final patch. Otherwise it is level or about 100 bb ahead. With even odds on flat or scaled, "scaled" is the better bet unless you think that mass run-dry is about 75% likely under a flat bank. If you think a flat bank is 70% likely, the bar drops to about 40%. This is arithmetic on noisy numbers, not a measurement. |

One thing argues for "flat" under silence: in the organisers' kit the bank is a fixed number per table. One thing argues against: other survivors will also take the dead blinds, so outliving the table is worth less than the simulations say.

## Open risks

- The gain needs three things at once: a flat bank, every other bot dry, and our bank still alive. On two emulated 5,000-hand tables with flat pacing our bank ended with 0.3 and 0.6 s left. That is a knife edge either way.
- An opponent built to stay silent for 60 hands and then shove over a raise of exactly 40 would cost about 5 to 7 bb/100 (the skeptic's test on the reviewed patch; the same branch). It cannot happen by accident and loses heavily itself.
- The stand-in opponents are not the real finalists. Death hands depend almost entirely on the transport cost per decision, which is not known.
- The final patch has not had an independent review. It is the reviewed patch with the larger branch deleted: 20 lines in the bundle.

## Files

All under night/

- dead_final.patch: the patch against HEAD (bot, model, the test file, and "name@H" dying opponents for the arena).
- dead_final_bot.py: live v6.7 plus the patch. 98,697 bytes.
- dead_final_sunday_scaled.py and dead_final_sunday_flat.py: the Sunday candidate (night/bot_sunday.py) plus the patch, with FINAL set each way. They differ from night/bot_sunday.py only in the patch's 20 lines. Load check clean, 18 unit tests pass.
- dead/final/: every output behind this page. lane1.sh, lane2.sh and race.sh list the commands. race_tally.py prints the bank-race tables.
- race/grid/report.txt: the reviewers' grid.

Nothing was committed, pushed or uploaded. release/bot.py was not touched.
