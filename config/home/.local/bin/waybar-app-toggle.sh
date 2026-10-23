#!/bin/sh
id="$1"; shift
RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
: "${SWAYSOCK:=$(ls -t "$RT"/sway-ipc.*.sock 2>/dev/null | head -1)}"
export SWAYSOCK
pf="$RT/waybar-app-$id.pid"
run=0
if swaymsg -t get_tree 2>/dev/null | grep -q "\"app_id\": \"$id\""; then
  run=1
fi
if [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null; then
  run=1
fi
if [ "$run" = 1 ]; then
  swaymsg "[app_id=$id]" kill 2>/dev/null
  [ -f "$pf" ] && kill "$(cat "$pf" 2>/dev/null)" 2>/dev/null
  rm -f "$pf"
else
  setsid "$@" >/dev/null 2>&1 &
  echo $! > "$pf"
fi
