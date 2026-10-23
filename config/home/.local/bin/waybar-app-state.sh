#!/bin/sh
id="$1"; label="$2"
RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
: "${SWAYSOCK:=$(ls -t "$RT"/sway-ipc.*.sock 2>/dev/null | head -1)}"
export SWAYSOCK
pf="$RT/waybar-app-$id.pid"
cl=off
if swaymsg -t get_tree 2>/dev/null | grep -q "\"app_id\": \"$id\""; then
  cl=on
elif [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null; then
  cl=on
fi
printf '{"text":"%s","class":"%s"}\n' "$label" "$cl"
