# 02 - Troubleshooting

Common failures on the LP-W841 and how to diagnose/fix them.

## Power key shuts the device down immediately

**Symptom:** pressing the power key once powers the device off, even though
`powerkeyd` is configured for "short press = screen off, long press = power
menu".

**Cause:** `systemd-logind` handles the power key on its own. Its built-in
default is `HandlePowerKey=poweroff`, so logind shuts the machine down in
parallel with `powerkeyd` (which only *reads* the event device and cannot stop
logind).

**Check:**

```sh
systemd-analyze cat-config systemd/logind.conf | grep -i handlepower
```

If it reports `HandlePowerKey=poweroff` (or the line is commented out, meaning
the default applies), this is the problem.

**Fix:** tell logind to ignore the power key so `powerkeyd` is the only
handler.

```sh
sudo mkdir -p /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/powerkey.conf >/dev/null <<EOF
[Login]
HandlePowerKey=ignore
HandlePowerKeyLongPress=ignore
EOF
sudo systemctl restart systemd-logind
```

## Waybar not appears after login

**Symptom:** sway starts, but the bottom bar is missing. `/tmp/waybar.log`
shows the bar being configured and then, about 25 s later:

```
[error] Error calling StartServiceByName for org.freedesktop.portal.Desktop: Timeout was reached
```

**Cause:** sway only exports `WAYLAND_DISPLAY` to its own child processes.
DBus-activated services and `systemd --user` units (such as
`xdg-desktop-portal-gtk`) do not inherit it, so the GTK portal starts without a
display and fails:

```
systemctl --user status xdg-desktop-portal-gtk   # failed: cannot open display:
```

**Fix:** `~/.config/sway/autostart.sh` exports the session variables and pushes
them into the DBus activation environment and the user manager, then (re)starts
the portal units before launching waybar:

```sh
export XDG_SESSION_TYPE=wayland
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
dbus-update-activation-environment --systemd \
  WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS
systemctl --user import-environment \
  WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR
systemctl --user reset-failed xdg-desktop-portal xdg-desktop-portal-gtk
systemctl --user start xdg-desktop-portal-gtk xdg-desktop-portal
```

## Waybar covers the bottom of the control panel

Waybar is a layer-shell client, so a fullscreen GTK window does **not** cover
it: the bar keeps painting over the bottom `height` pixels configured in
`~/.config/waybar/config` (default `"height": 48`).

`controlpanel.py` reserves that space explicitly:

```python
WAYBAR_HEIGHT = int(os.environ.get("WAYBAR_HEIGHT", "48"))
root.set_margin_bottom(WAYBAR_HEIGHT + BOTTOM_GAP)
```

The scrolling body is clipped above the fixed action bar, and the action bar
stays above the reserved gap, so nothing scrolls under waybar. If you change
the waybar height, start the panel with `WAYBAR_HEIGHT=<new height>` (or update
the default).
