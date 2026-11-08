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

## On-screen keyboard is hidden behind fullscreen windows

**Cause:** `wvkbd` 0.15 (packaged in Debian 13/trixie) puts its
layer-shell surface on the **top** layer. Sway renders the top layer *below*
fullscreen windows, so a fullscreen control panel covers it.

**Check:**

```sh
command -v wvkbd-mobintl       # /usr/local/bin/... = local build wins
dpkg -l wvkbd                  # may still say 0.15 for the distro package
```

(`wvkbd-mobintl -h` does not print a version string, so use the path instead.)

**Fix:** use `wvkbd` **0.16 or newer**

```sh
sudo apt install build-essential pkg-config libwayland-dev \
    libxkbcommon-dev libpango1.0-dev libcairo2-dev
git clone --depth 1 --branch v0.16 https://github.com/jjsullivan5196/wvkbd
cd wvkbd
make LAYOUT=mobintl wvkbd-mobintl
strip wvkbd-mobintl
sudo install -m755 wvkbd-mobintl /usr/local/bin/wvkbd-mobintl
```

(`make LAYOUT=mobintl wvkbd-mobintl` builds only the binary and skips the
man page, which would otherwise require `scdoc`.)

## Waybar covers the bottom of the control panel

Waybar is a layer-shell client, so a fullscreen GTK window does **not** cover
it: the bar keeps painting over the bottom `height` pixels configured in
`~/.config/waybar/config` (default `"height": 48`).

`controlpanel.py` reserves that space explicitly:

```python
WAYBAR_HEIGHT = int(os.environ.get("WAYBAR_HEIGHT", "48"))
root.set_margin_bottom(WAYBAR_HEIGHT + BOTTOM_GAP)
```
