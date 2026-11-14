"""Upload release/bot.py to the tournament site whenever a new one appears.

Run this on your own laptop; your login never leaves it.

    export POKER_COOKIE='<the cookie header your browser sends to imperialaihack.com>'
    python3 auto_upload.py --repo /path/to/your/clone/of/imperialpokerbot
    python3 auto_upload.py            # no clone: reads the file from GitHub (public repos only)

It uploads only when the file's contents change, never more than once a minute.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

API = "https://api.github.com/repos/Lorcan7274/imperialpokerbot/contents/release/bot.py?ref=main"
SITE = "https://imperialaihack.com"
AGENT = "pokerbot-uploader/1.0"


def read_source(repo):
    if repo:
        subprocess.run(["git", "-C", repo, "pull", "-q", "--ff-only"], check=False, timeout=60)
        with open(os.path.join(repo, "release", "bot.py"), "rb") as f:
            return f.read()
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github.raw", "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def upload(body, cookie):
    req = urllib.request.Request(SITE + "/api/poker/bot", data=body, method="POST", headers={
        "content-type": "text/x-python", "x-filename": "bot.py", "Cookie": cookie,
        "Origin": SITE, "Referer": SITE + "/pokerbots", "Accept": "application/json",
        "User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read()[:400]
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"error": text.decode("utf-8", "replace")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="", help="local clone to git-pull from (works for private repos)")
    ap.add_argument("--every", type=int, default=60, help="seconds between checks")
    ap.add_argument("--now", action="store_true", help="upload the current file immediately on start")
    ap.add_argument("--dry-run", action="store_true", help="show what would be uploaded without sending it")
    a = ap.parse_args()
    cookie = os.environ.get("POKER_COOKIE", "")
    if not cookie and not a.dry_run:
        raise SystemExit("Set POKER_COOKIE to your browser's cookie for imperialaihack.com first.")
    seen = None
    while True:
        try:
            body = read_source(a.repo)
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "could not read the bot file:", e)
            time.sleep(a.every)
            continue
        digest = hashlib.sha256(body).hexdigest()[:16]
        if seen is None and not a.now:
            seen = digest
            print(time.strftime("%H:%M:%S"), "watching; current bot is", digest, "(%d bytes)" % len(body))
        elif digest != seen:
            if a.dry_run:
                print(time.strftime("%H:%M:%S"), "would upload", digest, "(%d bytes)" % len(body))
                seen = digest
            else:
                status, reply = upload(body, cookie)
                print(time.strftime("%H:%M:%S"), "uploaded", digest, "->", status, json.dumps(reply)[:300])
                if reply.get("busy"):
                    time.sleep(5)
                    continue
                seen = digest
        time.sleep(max(60, a.every))


if __name__ == "__main__":
    main()
