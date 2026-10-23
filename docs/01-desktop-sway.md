# 01 - The sway desktop

The desktop is a plain sway session. Once sway runs, it pulls in
`~/.config/sway/autostart.sh`, which builds the touch-friendly environment:

```
sway
  -> ~/.config/sway/config
       -> ~/.config/sway/autostart.sh
            -> swaybg, waybar (on-screen keyboard on demand via the Kbd
               button), accent-update, scrollbridge, powerkeyd
```

**This repo does not decide how the session is started.** Starting sway from a
shell, from a display manager, or automatically at boot are all valid - pick
the one that fits your machine. The "boot straight into sway" recipe used on
the LP-E841 is described in [Starting a session](#starting-a-session) below.

## Starting a session

### From a shell

```sh
sway
```

### Boot straight into sway (no display manager)

Two pieces: a **getty autologin** so a user is logged in on tty1 without a
password, and a **way to launch sway** from that session.

**1. getty autologin** - a systemd drop-in:

```sh
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload
```

The `lp-w841_linux` repo ships this as a template
([`config/etc/systemd/system/getty@tty1.service.d/autologin.conf`](https://github.com/cicag/lp-w841_linux/blob/main/config/etc/systemd/system/getty@tty1.service.d/autologin.conf))
and its `install.sh` fills in the user name for you.

**2. launch sway from the session** - pick one:

*Shell profile* - add to `~/.bash_profile`:

```sh
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  export XDG_SESSION_TYPE=wayland
  export XDG_CURRENT_DESKTOP=sway
  export MOZ_ENABLE_WAYLAND=1
  [ -z "$XDG_RUNTIME_DIR" ] && export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  export WLR_RENDERER=vulkan
  /usr/local/bin/sway && exit 0
  export WLR_RENDERER=gles2
  exec sway
fi
```

*systemd user unit* - `~/.config/systemd/user/sway.service`:

```ini
[Unit]
Description=sway
After=graphical-session-pre.target
PartOf=graphical-session.target

[Service]
Type=exec
ExecStart=/usr/bin/sway
Environment=WLR_RENDERER=vulkan

[Install]
WantedBy=graphical-session.target
```

```sh
systemctl --user enable sway.service
```

*Display manager* - sway ships a session file, so `sway` shows up in the GDM/
SDDM/lightdm session list and can be started from there.

The renderer is a separate concern: the LP-E841 uses a custom sway built with
**Vulkan** support (see
[lp-w841_linux/docs/06-vulkan-renderer-backport.md](https://github.com/cicag/lp-w841_linux/blob/main/docs/06-vulkan-renderer-backport.md)),
with a **gles2** fallback. On a stock sway, drop the `WLR_RENDERER` lines.

## sway configuration

[`config/home/.config/sway/config`](../config/home/.config/sway/config)

```
font pango:sans 12
exec sh -c '$HOME/.config/sway/autostart.sh'

bindsym Mod4+Return exec alacritty
bindsym Mod4+Shift+q kill
bindsym Mod4+Shift+e exec swaynag -t warning -m 'Exit?' -b 'Ya' 'swaymsg exit'

bindsym XF86AudioRaiseVolume exec wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+
bindsym XF86AudioLowerVolume exec wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-
bindsym XF86AudioMute        exec wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle

input type:touchpad {
    tap enabled
    natural_scroll disabled
}

gaps inner 4
gaps outer 3
smart_borders off
default_border pixel 1
default_floating_border pixel 1
include $HOME/.config/sway/local*.conf
include $HOME/.config/sway/accent.conf
```

The keyboard bindings are minimal (the device is touch-first);
`accent.conf` is generated (see below).

**Device-specific parts are not included.** Anything that depends on the
hardware goes in `~/.config/sway/local*.conf`, which is included (as a glob, so
it is safe to leave absent). The usual one is the touchscreen mapping:

```sh
cat >> ~/.config/sway/local.conf <<'EOF'
input "0:0:silead_ts" {
    map_to_output DSI-1
}
EOF
```

Find the right names with:

```sh
libinput list-devices | grep -i touch
swaymsg -t get_outputs
```

Then `swaymsg reload`.

## Autostart

[`config/home/.config/sway/autostart.sh`](../config/home/.config/sway/autostart.sh)

```sh
#!/bin/sh
export MOZ_ENABLE_WAYLAND=1
export LIBVA_DRIVER_NAME=i965
BIN="$HOME/.local/bin"
CFG="$HOME/.config/sway"

if [ -f "$CFG/wallpaper" ] && [ -s "$CFG/wallpaper" ]; then
  swaybg -i "$(cat "$CFG/wallpaper")" -m fill &   # or a solid color
else
  swaybg -c '#1d1f21' &
fi
# on-screen keyboard: hidden at login, toggled by the waybar "Kbd" button
waybar &
sleep 0.5
[ -x "$BIN/accent-update" ] && "$BIN/accent-update"                   # wallpaper-derived theme
swaymsg 'gaps inner all set 4' >/dev/null 2>&1
swaymsg 'gaps outer all set 3' >/dev/null 2>&1
sudo -n -p '' setsid "$BIN/scrollbridge" 150 0 1 >/dev/null 2>&1 &    # 2-finger scroll
[ -x "$BIN/powerkeyd" ] && "$BIN/powerkeyd" >/tmp/powerkeyd.log 2>&1 &  # power key
export TERMINAL=alacritty
```

- **swaybg** sets the wallpaper (path stored in `~/.config/sway/wallpaper`).
  The file is created by the control panel when a wallpaper is picked.
- **wvkbd-mobintl** is the on-screen keyboard; it is hidden at login and the
  **Kbd** button starts/stops it. `WVKBD_HEIGHT` / `WVKBD_LAYOUT` tune its size.
- **waybar** the panel.
- **accent-update** derives an accent color from the wallpaper and rewrites the
  theme (below).
- **scrollbridge** adds two-finger scrolling to the touchscreen; it needs root
  (for the input device), hence the `sudo`. It is started with `sudo -n`, so
  it only runs if the user may use sudo without a password. The companion
  `lp-w841_linux/install.sh` installs that sudoers rule; otherwise add a
  `NOPASSWD` rule for `~/.local/bin/scrollbridge` yourself.
- **powerkeyd** implements power-button behaviour (below).

## Theme / accent color

A small theme system ties the wallpaper, window borders and the panel together:

- `~/.config/sway/wallpaper` - path to the current wallpaper.
- `~/.config/sway/accent` - two lines: accent color + foreground color.
- `~/.config/sway/accent.conf` - sway `client.*` border colors.
- `~/.config/waybar/style.css` - the waybar stylesheet, **generated**.

[`accent-update`](../config/home/.local/bin/accent-update) reads the wallpaper,
picks the dominant saturated color (HSV histogram over a downscaled image),
adjusts saturation/value, chooses a readable foreground, then writes `accent`,
`accent.conf` and a freshly templated `style.css`, and reloads sway + waybar.
The default accent is Catppuccin-ish `#89b4fa`.

## The panel (waybar)

[`config/home/.config/waybar/config`](../config/home/.config/waybar/config) -
a bottom, overlay bar, height 48:

- left: **launcher** (Apps), workspace **1**, workspace **2**
- center: **clock**
- right: **Kbd** (toggle on-screen keyboard), **Rot** (rotate), **Set** (control
  panel), **battery**

Each button is backed by a small script:

| Script | Role |
|---|---|
| [`waybar-app-state.sh`](../config/home/.local/bin/waybar-app-state.sh) | reports `on`/`off` if a GTK app with a given `app_id` is running |
| [`waybar-app-toggle.sh`](../config/home/.local/bin/waybar-app-toggle.sh) | launches the app, or kills it if running; tracks a pidfile |
| [`waybar-ws.sh`](../config/home/.local/bin/waybar-ws.sh) | prints the waybar JSON + active class for workspace 1/2 |
| [`waybar-kbd.sh`](../config/home/.local/bin/waybar-kbd.sh) | toggles `wvkbd-mobintl` |
| [`waybar-kbd-state.sh`](../config/home/.local/bin/waybar-kbd-state.sh) | reports whether the on-screen keyboard is running (the **Kbd** button highlights) |
| [`waybar-rotate.sh`](../config/home/.local/bin/waybar-rotate.sh) | cycles the output transform normal/90/180/270 (output auto-detected) |

## GTK apps (touch UI)

- [`appmenu`](../config/home/.local/bin/appmenu) - a fullscreen GTK3 application
  grid (reads installed `.desktop` entries via GIO, `FlowBox`, 4 columns,
  launches on tap). Triggered by the waybar **Apps** button (`app_id` = `appmenu`).
- [`controlpanel`](../config/home/.local/bin/controlpanel) - a fullscreen GTK3
  settings panel (`app_id` = `controlpanel`) with:
  - **Volume** slider + output-device list (`wpctl`), clamped to 100%,
  - **Per-app volume** list (`pw-dump`): each PipeWire stream gets its own
    volume slider and a mute toggle,
  - **Brightness** slider (writes `intel_backlight`),
  - **WiFi** card (`nmcli`: on/off, scan, connect, show IP/GW/DNS),
  - **Bluetooth** card (`bluetoothctl`: on/off, scan, connect),
  - **Wallpaper** picker (thumbnails from `~/wallpapers`, sets it and refreshes
    the accent).

  It scales its whole UI based on the current orientation, and applies a CSS
  theme built from the current accent color.

Both apps set a sway `app_id`, which is how the waybar buttons know whether they
are open.

## Power button

[`powerkeyd`](../config/home/.local/bin/powerkeyd) reads the power-key input
device directly (the user has to be in the `input` group) and implements:

- **short press** - toggle screen `dpms` on/off; after the screen has been off
  for `POWERKEY_OFF_DELAY` (default 600 s) it powers off (a "sleep then off"
  behaviour).
- **long press** (>= `POWERKEY_HOLD`, default 1.0-1.5 s) - show a `swaynag`
  power dialog with **Matikan** (poweroff), **Mulai ulang** (reboot), **Batal**.

The input device and the output are **auto-detected** (an input device whose
name contains *power* or *pek*; the first non-headless sway output). Override
them with `POWERKEY_DEVICE` / `POWERKEY_OUTPUT`; `POWERKEY_HOLD` and
`POWERKEY_OFF_DELAY` tune the timings.

## Manual/session snippets

When testing over SSH, the session variables are:

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=wayland-1
export SWAYSOCK=$(ls -t /run/user/$(id -u)/sway-ipc.*.sock | head -1)
```
