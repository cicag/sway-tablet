# 01 - The sway desktop

The desktop is a plain sway session. Once sway runs, it pulls in
`~/.config/sway/autostart.sh`, which builds the touch-friendly environment:

```
sway
  -> ~/.config/sway/config
       -> ~/.config/sway/autostart.sh
            -> swaybg, waybar (on-screen keyboard on demand via the Kbd
               button), accent-update, powerkeyd
```

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
[ -x "$BIN/powerkeyd" ] && "$BIN/powerkeyd" >/tmp/powerkeyd.log 2>&1 &  # power key
export TERMINAL=alacritty
```
