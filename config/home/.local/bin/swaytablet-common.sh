#!/bin/sh
# swaytablet-common.sh - shared shell helpers for sway-tablet waybar applets.
#
# Source from sibling scripts:
#   . "$(dirname "$0")/swaytablet-common.sh"

waybar_runtime_dir() {
    printf '%s' "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
}

waybar_sock() {
    : "${SWAYSOCK:=$(ls -t "$(waybar_runtime_dir)"/sway-ipc.*.sock 2>/dev/null | head -1)}"
    export SWAYSOCK
}

waybar_app_pidfile() {
    # $1 = app id
    printf '%s/waybar-app-%s.pid' "$(waybar_runtime_dir)" "$1"
}

waybar_app_running() {
    # $1 = app id. Returns 0 if the app has a sway window or a live pidfile.
    if swaymsg -t get_tree 2>/dev/null | grep -q "\"app_id\": \"$1\""; then
        return 0
    fi
    pf="$(waybar_app_pidfile "$1")"
    if [ -f "$pf" ] && kill -0 "$(cat "$pf" 2>/dev/null)" 2>/dev/null; then
        return 0
    fi
    return 1
}
