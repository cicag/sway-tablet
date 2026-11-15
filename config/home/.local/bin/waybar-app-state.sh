#!/bin/sh
. "$(dirname "$0")/swaytablet-common.sh"

id="$1"; label="$2"
waybar_sock
pf="$(waybar_app_pidfile "$id")"
cl=off
if waybar_app_running "$id"; then
  cl=on
fi
printf '{"text":"%s","class":"%s"}\n' "$label" "$cl"
