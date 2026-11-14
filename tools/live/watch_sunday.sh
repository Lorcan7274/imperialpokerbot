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
  for f in $(ls "$H" | grep -v -x -F -f "$H/.seen" | grep "^sunday_.*json$" | sort); do
    line=$(python3 tools/live/report.py "$H/$f" 2>&1 | head -1)
    flags=$(python3 -c "
import json, sys
r = json.load(open(sys.argv[1])).get('round', {})
bad = [k for k in ('errors', 'bank_out', 'timeouts') if r.get(k)]
bad += ['think'] if (r.get('think_s') or 0) > 6 else []
bad += ['violations'] if r.get('violations') else []
print('ALERT ' + ','.join(bad) if bad else 'ok')" "$H/$f")
    echo "$line, errors/bank: $flags | $(python3 tools/live/bucket.py 2>&1 | head -1)"
    echo "$f" >> "$H/.seen"
  done
  sleep 40
done
