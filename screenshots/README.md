# Screenshots

Captured on the device (800x1280) with `grim` while the sway session was
running.

| File | Contents |
|---|---|
| `01-desktop.png` | sway desktop: wallpaper, bottom waybar and the on-screen keyboard (`wvkbd-mobintl`) |
| `02-controlpanel.png` | the GTK control panel (`controlpanel`): volume, output devices, brightness, WiFi, Bluetooth and the wallpaper carousel |
| `03-powermenu.png` | the power menu: shut down, restart, restart waybar, cancel |
| `04-appmenu.png` | the GTK app grid (`appmenu`) |

Reproduce:

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1}
export SWAYSOCK=$(ls -t /run/user/$(id -u)/sway-ipc.*.sock | head -1)
grim -o "$(swaymsg -t get_outputs | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["name"])')" desktop.png
# open the apps grid / settings panel / power menu, then capture again
```
