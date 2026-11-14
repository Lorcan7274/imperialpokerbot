# Imperial poker bot

A no-limit hold'em bot for the Imperial AI Hack poker track: 2,000-chip stacks reset every hand, 10/20 blinds, tables of 7 or 8 bots, ranked on bb/100. Pure Python standard library, built for the 10 ms per decision limit.

## How it plays

- **Preflop**: every starting hand is ranked by a precomputed strength table; opening, 3-bet and 4-bet thresholds depend on position and on how often this opponent raises and folds.
- **Opponent model**: for each opponent it counts how often they raise, call and fold in each situation, blended with sensible defaults until there is data.
- **Range inference**: each action an opponent takes narrows the hands they can hold to the share that matches how often they take that action, so a bot that always bets keeps a wide range and a tight one a narrow range.
- **Postflop**: it estimates equity against a weighted sample of those ranges and picks the check, call, fold, bet or raise size with the best expected value, using the opponent's measured fold rate for the chance a bet wins the pot.
- **Bet sizes**: from the hands each opponent shows down it learns how strong their small bets, big bets, raises and shoves have been, and reads the next one the same way.
- **All-in spots**: big preflop raises are answered by equity against the range the opponent has actually been shoving.
- **Starter bots**: the organisers' starter bot and its variants are recognised by their raise sizes and played by their exact rules.

## Results

Saturday's counted rounds at the hack (real opponents, 1,000 hands a round): a mean of +43 bb/100 over all 54 rounds, first at the table in 17 and in the top two in 28, with seven losing rounds. The first 31 rounds averaged +61; from round 32 the tables were almost all eight-player with no weak or starter bots left, and the last 23 averaged +20. A round took 1.8 to 4.9 s of the 10 s thinking bank, with no errors and the bank never emptied; 80 decisions in all were lost to the 10 ms limit.

Local check on an eight-player table in the organisers' state format (`arena/kitlike.py`), 1,000-hand rounds against stand-ins for the house bots plus tighter opponents:

| Field | bb/100 | Worst decision | Thinking per round |
|---|---|---|---|
| starter-style, calling station, random, tight, equity bots | about +650 (two four-round runs: +680 and +628, each give or take 230) | under 4 ms | under 1 s |

The limits are 10 ms per decision and 10 s per round. The local opponents are ones written for this repo, so treat that win rate as a sanity check, not a forecast.

## Files

- `bot.py` is the single file to upload; it is generated from `pokerbot/` by `python3 tools/bundle.py`.
- `pokerbot/` is the source: hand evaluator, preflop table, opponent model, range sampling, decision logic and the `Agent` wrapper.
- `arena/` is a small test engine with example opponents.

## Run it

```
python3 tools/bundle.py
python3 arena/kitlike.py --rounds 4
python3 arena/run.py --hands 2000
python3 -m unittest discover -s tests -t .
```

In the organisers' starter kit: `python local_sim.py path/to/bot.py`.
