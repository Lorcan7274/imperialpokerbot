#!/bin/bash
S=/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad
cd /home/user/imperialpokerbot
ls $S/hands > $S/live/seen2.txt
fails=0
while true; do
  if python3 tools/fetch.py --out $S/hands >/dev/null 2>$S/live/fetch.err; then
    fails=0
  else
    fails=$((fails+1))
    if [ $fails -eq 3 ]; then echo "fetch failing: $(tail -1 $S/live/fetch.err | cut -c1-200)"; fi
  fi
  for f in $(ls $S/hands | grep -v -x -F -f $S/live/seen2.txt | grep "^saturday_r.*json$" | sort); do
    line=$(python3 $S/live/report.py $S/hands/$f 2>&1 | head -1)
    table=$(python3 $S/live/report.py $S/hands/$f 2>&1 | sed -n 2p)
    num=$(echo "$f" | sed 's/[^0-9]//g' | sed 's/^0*//')
    bb=$(echo "$line" | sed -n 's/.*: \([+-][0-9.]*\) bb\/100.*/\1/p')
    to=$(echo "$line" | sed -n 's/.*timeouts \([0-9]*\).*/\1/p')
    bad=$(python3 -c "print(1 if float('${bb:-0}') < 0 or int('${to:-0}') >= 8 else 0)")
    if [ "$bad" = "1" ]; then echo "ALERT $line |$table"; fi
    if [ $((num % 4)) -eq 0 ]; then echo "$line | $(python3 $S/live/summary.py 2>&1 | head -1 | sed 's/ by site version.*last check/ last check/')"; fi
    echo "$f" >> $S/live/seen2.txt
  done
  sleep 40
done
