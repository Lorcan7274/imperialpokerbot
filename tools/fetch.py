import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

AGENT = "pokerbot-fetch/1.0"


def get(site, path, token):
    req = urllib.request.Request(site.rstrip("/") + path, headers={
        "Authorization": "Bearer " + token, "User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def sync(site, token, out):
    res = get(site, "/api/poker/results", token)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "_results.json"), "w") as f:
        json.dump(res, f)
    new = []
    for rd in res.get("rounds", []):
        dest = os.path.join(out, rd["ref"].replace("/", "_") + ".json")
        if os.path.exists(dest):
            continue
        data = get(site, "/api/poker/hands?ref=" + urllib.parse.quote(rd["ref"]), token)
        data["round"] = rd
        with open(dest, "w") as f:
            json.dump(data, f)
        new.append(dest)
    return res, new


def main():
    ap = argparse.ArgumentParser(description="Download the team's rounds; the token comes from --token or POKER_TOKEN.")
    ap.add_argument("--token", default=os.environ.get("POKER_TOKEN", ""))
    ap.add_argument("--site", default="https://imperialaihack.com")
    ap.add_argument("--out", default="hands")
    ap.add_argument("--wait", type=int, default=0, help="poll up to this many seconds for a new round")
    a = ap.parse_args()
    deadline = time.time() + a.wait
    while True:
        try:
            res, new = sync(a.site, a.token, a.out)
        except urllib.error.HTTPError as e:
            raise SystemExit("%s %s" % (e.code, e.reason))
        if new or time.time() >= deadline:
            break
        time.sleep(20)
    for rd in res.get("rounds", []):
        print(rd.get("ref"), {k: v for k, v in rd.items() if k != "ref"})
    print("%s: %d round(s), %d new; last check: %s" % (
        res.get("team"), len(res.get("rounds", [])), len(new), (res.get("lastCheck") or {}).get("message")))


if __name__ == "__main__":
    main()
