# Imperial poker bot

A no-limit hold'em bot written for the AI Poker Bots track at Imperial AI Hack, 14–15 November 2026.

Bots played 1,000-hand rounds at tables of up to eight, with 100 big blinds each and stacks reset every hand, and were ranked on big blinds won per 100 hands. A bot is a single Python file that may use only the standard library, with 10 to 25 ms per decision and 10 s of thinking per round.

## How it plays

- **Before the flop.** Every starting hand has a precomputed strength rank. How wide it opens, re-raises and calls depends on its position and on how often each opponent has been raising and folding.
- **Opponent model.** For each opponent it counts how often they raise, call and fold in each kind of situation, starting from typical values until it has seen enough hands.
- **Reading hands.** Each action an opponent takes narrows the hands they can hold to the share that fits how often they take that action, so a player who bets everything keeps a wide range and a tight player a narrow one. Hands shown at showdown teach it how strong each player's small bets, big bets, raises and all-ins have been.
- **After the flop.** It estimates its chance of winning against a weighted sample of those ranges by simulating the cards still to come. It then picks the check, call, fold, bet or raise size with the best expected value, using each opponent's measured fold rate for the chance that a bet wins the pot.
- **Starter bots.** The organisers' starter bot and its variants are recognised by their raise sizes and the hands they show, and played by their known rules.
- **Time.** It measures the server's speed at the start of each round and scales how deeply it simulates, so a round stays inside the thinking time.

`bot.py` is the file that was uploaded. It is bundled from the source in `pokerbot/` by `python3 tools/bundle.py`.
