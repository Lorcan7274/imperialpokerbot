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
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    if d.get("finalists"):
        print("finalists: " + " · ".join(d["finalists"]))
    stages = (d.get("sunday") or {}).get("stages") or []
    if not stages:
        print("no bucket tables in the feed yet; phase", d.get("phase"))
        return
    stage = stages[-1]
    for j, rows in enumerate(stage["tables"]):
        names = [r["name"] for r in rows]
        if team not in names:
            continue
        k = names.index(team)
        cut = rows[stage["advance"]]["chips"] if len(rows) > stage["advance"] else 0
        lead = rows[k]["chips"] - (cut if k < stage["advance"] else rows[stage["advance"] - 1]["chips"])
        print("table %s after round %d of %d: %s is %d of %d, %+d bb %s the cut" % (
            chr(65 + j), stage["rounds_played"], stage["rounds"], team, k + 1, len(rows), round(lead / 20),
            "above" if k < stage["advance"] else "from"))
        print("   " + " | ".join("%d %s %+d bb (%+.1f)" % (i + 1, r["name"][:16], round(r["chips"] / 20), r["bb100"])
                                 for i, r in enumerate(rows)))
        return
    print(team, "is not at a bucket table in the feed")


if __name__ == "__main__":
    main()
