#!/bin/sh
if pgrep -x wvkbd-mobintl >/dev/null 2>&1; then
  pkill -x wvkbd-mobintl
else
  wvkbd-mobintl -H "${WVKBD_HEIGHT:-384}" -L "${WVKBD_LAYOUT:-240}" &
fi
