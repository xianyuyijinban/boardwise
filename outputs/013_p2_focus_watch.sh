#!/usr/bin/env bash
# 013 批② focus watch: poll doc.list every 12s, record one line per sample.
# Read-only. Stops after N samples or when the focused project is 毕设FOC驱动板.
cd /e/boardwise
out=outputs/013_p2_doclist_watch.txt
: > "$out"
for i in $(seq 1 40); do
  ts=$(date +%H:%M:%S)
  line=$(.venv/Scripts/python.exe outputs/013_p2_call.py doc.list '{}' | .venv/Scripts/python.exe -c "
import json,sys
d=json.load(sys.stdin)
ps=d.get('projects',[])
a=d.get('active')
foc=[p.get('friendlyName') for p in ps if p.get('focused')]
print(json.dumps({'projects':[p.get('friendlyName') for p in ps],'focused':foc,'active':(a or {}).get('uuid'),'tabs_active':len(d.get('documents',[]))},ensure_ascii=False))
")
  echo "$ts $line" >> "$out"
  echo "$ts $line"
  case "$line" in *毕设FOC驱动板*) echo "$ts HIT bishe focused" >> "$out"; break;; esac
  sleep 12
done
echo "DONE" >> "$out"
