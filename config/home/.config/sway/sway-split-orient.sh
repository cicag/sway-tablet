#!/bin/sh
# sway-split-orient - auto-set default split orientation based on screen rotation.
#
# Portrait (vertical) orientation  -> split horizontally (side by side)
# Landscape (horizontal) orientation -> split vertically (stacked)
#
# Runs in the background and re-checks every 2 seconds, so rotating the screen
# automatically adjusts the split direction for new windows.

RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
SWAYSOCK="${SWAYSOCK:=$(ls -t "$RT"/sway-ipc.*.sock 2>/dev/null | head -1)}"
export SWAYSOCK

last=""

while true; do
    transform=$(swaymsg -t get_outputs 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for o in data:
    if not o.get("headless") and o.get("name"):
        print(o.get("transform", "normal"))
        break
' 2>/dev/null)

    if [ "$transform" != "$last" ]; then
        case "$transform" in
            90|270|flipped-90|flipped-270)
                # Portrait: split horizontally (side by side)
                swaymsg default_orientation horizontal >/dev/null 2>&1
                ;;
            *)
                # Landscape: split vertically (stacked)
                swaymsg default_orientation vertical >/dev/null 2>&1
                ;;
        esac
        last="$transform"
    fi

    sleep 2
done
