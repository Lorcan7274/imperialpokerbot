#!/bin/bash
# One line per new Sunday round: our result, the server's timing figures, and where we stand at the bucket table.
#   POKER_TOKEN=... tools/live/watch_sunday.sh /path/to/hands
H=${1:-hands}
cd "$(dirname "$0")/../.." || exit 1
mkdir -p "$H"
ls "$H" > "$H/.seen"
rm -f "$H/.state" "$H/.late"
fails=0
behind=0
while true; do
  if python3 tools/fetch.py --out "$H" >/dev/null 2>"$H/.err"; then
    if [ $fails -ge 3 ]; then echo "fetch working again after $fails failed polls"; fi
    fails=0
  else
    fails=$((fails+1))
    if [ $fails -eq 3 ] || [ $((fails % 15)) -eq 0 ]; then echo "fetch failing ($fails polls in a row): $(tail -1 "$H/.err" | cut -c1-200)"; fi
  fi
  if [ $fails -ge 3 ]; then python3 -c "
import json, os, sys
H = sys.argv[1]
try:
    rounds = json.load(open(os.path.join(H, '_results.json'))).get('rounds') or []
    told = set(open(os.path.join(H, '.late')).read().split('\n')) if os.path.exists(os.path.join(H, '.late')) else set()
except Exception:
    sys.exit(0)
for r in rounds:
    ref = str(r.get('ref'))
    if ref.startswith('saturday/') or ref in told or os.path.exists(os.path.join(H, ref.replace('/', '_') + '.json')):
        continue
    print('ALERT %s is in the results feed but its hands did not download: chips %s, bb/100 %s, errors %s, timeouts %s, bank_out %s, think %s, violations %s' % (
        ref, r.get('chips'), r.get('bb100'), r.get('errors'), r.get('timeouts'), r.get('bank_out'), r.get('think_s'), str(r.get('violations'))[:100]))
    open(os.path.join(H, '.late'), 'a').write(ref + '\n')
" "$H" 2>/dev/null; fi
  state=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
c = d.get('lastCheck') or {}
bad = [] if c.get('ok', 1) else ['the upload failed the load check']
bad += ['team flags %s' % json.dumps(d['flags'])[:300]] if d.get('flags') else []
print('upload: version %s, sha %s, %s%s' % (c.get('version'), c.get('sha'), ' '.join(str(c.get('message')).split())[-200:],
                                            ' | ALERT ' + ', '.join(bad) if bad else ''))" "$H/_results.json" 2>/dev/null)
  if [ -n "$state" ] && [ "$state" != "$(cat "$H/.state" 2>/dev/null)" ]; then
    echo "$state"
    echo "$state" > "$H/.state"
  fi
  want=$(sha256sum release/bot.py 2>/dev/null | cut -c1-16)
  live=$(python3 -c "
import json, sys
print((json.load(open(sys.argv[1])).get('lastCheck') or {}).get('sha') or '')" "$H/_results.json" 2>/dev/null)
  if [ $fails -eq 0 ] && [ -n "$want" ] && [ -n "$live" ] && [ "$want" != "$live" ]; then
    behind=$((behind+1))
    # about four minutes of polls, then every five minutes while it lasts
    if [ $behind -eq 6 ] || { [ $behind -gt 6 ] && [ $(((behind - 6) % 8)) -eq 0 ]; }; then
      echo "ALERT not uploaded: release/bot.py is $want but the site still has $live after $behind polls"
    fi
  elif [ $fails -eq 0 ]; then
    if [ $behind -ge 6 ]; then echo "the site now has release/bot.py ($live)"; fi
    behind=0
  fi
  ls "$H" | grep -v -x -F -f "$H/.seen" | grep "json$" | grep -v "^_" | grep -v "^saturday_" | sort > "$H/.new"
  while IFS= read -r f; do
    line=$(python3 tools/live/report.py "$H/$f" 2>/dev/null | head -1)
    [ -n "$line" ] || line="$f: report.py could not read this round"
    flags=$(python3 -c "
import json, sys
r = json.load(open(sys.argv[1])).get('round') or {}
def n(k):
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0
bad = [k for k in ('errors', 'bank_out') if r.get(k)]
bad += ['timeouts'] if n('timeouts') >= 5 else []
bad += ['think'] if n('think_s') > 6 else []
bad += ['violations %s' % r['violations']] if r.get('violations') else []
# a bot the server played for all round loses the blinds and nothing else
bad += ['auto-played?'] if -19.5 <= n('bb100') <= -16 and r.get('think_s') is not None and n('think_s') < 1 else []
bad += ['error: ' + ' '.join(str(r['error_sample']).split())[-300:]] if r.get('error_sample') else []
print('ALERT ' + ', '.join(bad) if bad else 'ok')" "$H/$f" 2>/dev/null)
    [ -n "$flags" ] || flags="ALERT the round record could not be checked"
    table=$(python3 tools/live/bucket.py 2>/dev/null | head -1)
    echo "$line, errors/bank: $flags | ${table:-standings not available}"
    echo "$f" >> "$H/.seen"
  done < "$H/.new"
  sleep 40
done
