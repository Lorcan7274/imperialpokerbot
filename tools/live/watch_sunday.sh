#!/bin/bash
# One line per new Sunday round: our result, the server's timing figures, and where we stand at the bucket table.
#   POKER_TOKEN=... tools/live/watch_sunday.sh /path/to/hands
H=${1:-hands}
cd "$(dirname "$0")/../.." || exit 1
mkdir -p "$H"
ls "$H" > "$H/.seen"
fails=0
while true; do
  if python3 tools/fetch.py --out "$H" >/dev/null 2>"$H/.err"; then
    fails=0
  else
    fails=$((fails+1))
    if [ $fails -eq 3 ]; then echo "fetch failing: $(tail -1 "$H/.err" | cut -c1-200)"; fi
  fi
  for f in $(ls "$H" | grep -v -x -F -f "$H/.seen" | grep "json$" | grep -v "^_" | grep -v "^saturday_" | sort); do
    line=$(python3 tools/live/report.py "$H/$f" 2>&1 | head -1)
    flags=$(python3 -c "
import json, sys
r = json.load(open(sys.argv[1])).get('round', {})
bad = [k for k in ('errors', 'bank_out') if r.get(k)]
bad += ['timeouts'] if (r.get('timeouts') or 0) >= 5 else []
bad += ['think'] if (r.get('think_s') or 0) > 6 else []
bad += ['violations %s' % r['violations']] if r.get('violations') else []
# a bot the server played for all round loses the blinds and nothing else
bad += ['auto-played?'] if -19.5 <= (r.get('bb100') or 0) <= -16 and (r.get('think_s') or 0) < 1 else []
bad += ['error: ' + ' '.join(str(r['error_sample']).split())[-300:]] if r.get('error_sample') else []
print('ALERT ' + ', '.join(bad) if bad else 'ok')" "$H/$f")
    echo "$line, errors/bank: $flags | $(python3 tools/live/bucket.py 2>&1 | head -1)"
    echo "$f" >> "$H/.seen"
  done
  sleep 40
done
