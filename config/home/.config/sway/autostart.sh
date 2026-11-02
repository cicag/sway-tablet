#!/bin/sh
# Started by sway itself (exec in ~/.config/sway/config).
export MOZ_ENABLE_WAYLAND=1
export LIBVA_DRIVER_NAME=i965

BIN="$HOME/.local/bin"
CFG="$HOME/.config/sway"

# wallpaper (path stored in ~/.config/sway/wallpaper)
if [ -f "$CFG/wallpaper" ] && [ -s "$CFG/wallpaper" ]; then
  swaybg -i "$(cat "$CFG/wallpaper")" -m fill &
else
  swaybg -c '#1d1f21' &
fi

# on-screen keyboard is hidden at login; the waybar "Kbd" button starts/stops
# it (waybar-kbd.sh), where WVKBD_HEIGHT / WVKBD_LAYOUT tune its size.

waybar &
sleep 0.5

# wallpaper-derived accent theme
[ -x "$BIN/accent-update" ] && "$BIN/accent-update"

swaymsg 'gaps inner all set 4' >/dev/null 2>&1
swaymsg 'gaps outer all set 3' >/dev/null 2>&1

# power button (short press = screen, long press = power dialog)
[ -x "$BIN/powerkeyd" ] && "$BIN/powerkeyd" >/tmp/powerkeyd.log 2>&1 &

export TERMINAL=alacritty
