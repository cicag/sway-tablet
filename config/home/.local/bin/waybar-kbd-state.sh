#!/bin/sh
if pgrep -x wvkbd-mobintl >/dev/null 2>&1; then
  printf '{"text":"Kbd","class":"on"}\n'
else
  printf '{"text":"Kbd","class":"off"}\n'
fi
