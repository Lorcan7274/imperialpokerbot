import json, sys, glob
S = '/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
r = json.load(open(S + '/hands/_results.json'))
rounds = [x for x in r['rounds'] if '/practice/' not in x['ref']]
rounds.sort(key=lambda x: x['slot'])
by = {}
for x in rounds:
    by.setdefault(x['version'], []).append(x['bb100'])
tot = [x['bb100'] for x in rounds]
if tot:
    print("counted so far: %d rounds, mean %+.1f bb/100 | by site version: %s | last check v%s %s" % (
        len(tot), sum(tot) / len(tot),
        ", ".join("v%s: %d rounds %+.1f" % (k, len(v), sum(v) / len(v)) for k, v in sorted(by.items())),
        (r.get('lastCheck') or {}).get('version'), (r.get('lastCheck') or {}).get('sha', '')[:8]))
