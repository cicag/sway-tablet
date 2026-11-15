#!/bin/sh
. "$(dirname "$0")/swaytablet-common.sh"

id="$1"; shift
waybar_sock
pf="$(waybar_app_pidfile "$id")"
if waybar_app_running "$id"; then
  swaymsg "[app_id=$id]" kill 2>/dev/null
  [ -f "$pf" ] && kill "$(cat "$pf" 2>/dev/null)" 2>/dev/null
  rm -f "$pf"
else
  setsid "$@" >/dev/null 2>&1 &
  echo $! > "$pf"
fi
