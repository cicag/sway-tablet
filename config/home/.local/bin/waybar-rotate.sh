#!/bin/sh
# Cycle the output transform (normal -> 90 -> 180 -> 270).
# The output is auto-detected (first non-headless output); override with
# OUTPUT_NAME=eDP-1.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[ -z "$SWAYSOCK" ] && SWAYSOCK=$(ls -t /run/user/$(id -u)/sway-ipc.*.sock 2>/dev/null | head -1)
export SWAYSOCK

out=$(swaymsg -t get_outputs 2>/dev/null | python3 -c "
import sys, json, os
name = os.environ.get('OUTPUT_NAME', '')
try:
    outs = [x for x in json.load(sys.stdin) if not x.get('headless') and x.get('name')]
    if name:
        outs = [x for x in outs if x['name'] == name]
    if not outs:
        print('')
    else:
        print(outs[0]['name'], outs[0].get('transform', 'normal'))
except Exception:
    print('')
")
name=$(printf '%s' "$out" | cut -d' ' -f1)
cur=$(printf '%s' "$out" | cut -d' ' -f2)
[ -z "$name" ] && exit 0

case "$cur" in
  normal|none|0) next=90;;
  90) next=180;;
  180) next=270;;
  270) next=normal;;
  *) next=90;;
esac
swaymsg output "$name" transform "$next" >/dev/null 2>&1
