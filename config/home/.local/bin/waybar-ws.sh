#!/bin/sh
n="$1"
RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export SWAYSOCK=$(ls -t "$RT"/sway-ipc.*.sock 2>/dev/null | head -1)
cls=$(swaymsg -t get_workspaces 2>/dev/null | python3 -c '
import json,sys
n=sys.argv[1]
try:
    ws=json.load(sys.stdin)
except Exception:
    print("inactive"); raise SystemExit
for w in ws:
    if w.get("name")==n and w.get("focused"):
        print("active"); raise SystemExit
print("inactive")
' "$n")
printf '{"text":"%s","class":"%s"}\n' "$n" "$cls"
