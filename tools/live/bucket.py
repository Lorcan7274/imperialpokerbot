"""Print our bucket table's standings from the tournament's public feed.

    python3 tools/live/bucket.py [team name]
"""
import json
import sys
import urllib.request

FEED = "https://poker.imperialaihack.com/pokerbots/api/public"


def main():
    team = sys.argv[1] if len(sys.argv) > 1 else "Gherkers"
    req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        d = json.loads(r.read())
    if d.get("finalists"):
        print("finalists: " + " · ".join(f if isinstance(f, str) else str(f.get("name")) for f in d["finalists"]))
    stages = (d.get("sunday") or {}).get("stages") or []
    if not stages:
        print("no bucket tables in the feed yet; phase", d.get("phase"))
        return
    # the latest stage that has the team: a final added as a later stage must not hide the bucket table
    for stage in reversed(stages):
        for j, feed_rows in enumerate(stage.get("tables") or []):
            if team not in [r.get("name") for r in feed_rows]:
                continue
            # place by chips, whatever order the feed has the rows in (ties keep the feed's order)
            rows = sorted(feed_rows, key=lambda r: -r["chips"])  # a row without chips fails loudly, in one line
            k = [r.get("name") for r in rows].index(team)
            adv = stage.get("advance") or 0
            chips = [r["chips"] for r in rows]
            note = "" if rows == feed_rows else " (feed rows are not in chip order: place is by chips)"
            note += "" if stage is stages[-1] else " (stage %s; %s is not in the latest stage)" % (stage.get("stage"), team)
            head = "table %s after round %s of %s: %s is %d of %d" % (
                chr(65 + j), stage.get("rounds_played"), stage.get("rounds"), team, k + 1, len(rows))
            if not 0 < adv < len(rows):
                print("%s, no cut at this table (advance %s)%s" % (head, adv, note))
            else:
                lead = chips[k] - (chips[adv] if k < adv else chips[adv - 1])
                print("%s, %+.1f bb %s the cut%s%s" % (head, lead / 20, "above" if k < adv else "from",
                                                       " (TIED on chips)" if lead == 0 else "", note))
            print("   " + " | ".join("%d %s %+d bb (%+.1f)" % (i + 1, str(r.get("name"))[:16], round(chips[i] / 20),
                                                              r.get("bb100") or 0.0) for i, r in enumerate(rows)))
            return
    print(team, "is not at a bucket table in the feed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # one line, whatever went wrong: the watcher shows only the first
        print("standings unavailable: %s: %s" % (type(e).__name__, " ".join(str(e).split())[:150]))
        sys.exit(1)
