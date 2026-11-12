#!/bin/sh
# Started by sway itself (exec in ~/.config/sway/config).
export MOZ_ENABLE_WAYLAND=1
#export LIBVA_DRIVER_NAME=i965
# Use Vulkan renderer for sway (GLES2 is the default on this hardware).
#export WLR_RENDERER=vulkan

BIN="$HOME/.local/bin"
CFG="$HOME/.config/sway"

# Sway exports its Wayland socket only to its own children. DBus-activated and
# systemd --user services (xdg-desktop-portal, portal-gtk, ...) do not inherit
# it, so portal-gtk fails with "cannot open display" and portal activation
# times out after 25s. GTK clients such as waybar then abort with
# "Error calling StartServiceByName for org.freedesktop.portal.Desktop".
# Keep both the DBus activation environment and the user manager in sync.
export XDG_SESSION_TYPE=wayland
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-sway}"
if command -v dbus-update-activation-environment >/dev/null 2>&1; then
  dbus-update-activation-environment --systemd \
    WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR \
    DBUS_SESSION_BUS_ADDRESS >/dev/null 2>&1 || true
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user import-environment \
    WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR \
    >/dev/null 2>&1 || true
  systemctl --user reset-failed xdg-desktop-portal \
    xdg-desktop-portal-gtk >/dev/null 2>&1 || true
  systemctl --user start xdg-desktop-portal-gtk \
    xdg-desktop-portal >/dev/null 2>&1 || true
fi

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

# Auto screen off after idle, then power off. Disabled when screen-blocked
# file exists (toggled from controlpanel for hands-free media playback).
if [ ! -f "$HOME/.config/swaytablet/screen-blocked" ]; then
  swayidle -w \
    timeout 300 'swaymsg "output * dpms off"' \
    resume 'swaymsg "output * dpms on"' \
    timeout 900 'systemctl poweroff' &
fi

# Touchscreen gestures (lisgd). Disabled when gestures-disabled file exists.
# Set GESTURE_DEVICE per device (e.g. /dev/input/event2) if auto-detect fails.
[ -x "$BIN/sway-tablet-gestures" ] && "$BIN/sway-tablet-gestures" start &

export TERMINAL=alacritty
