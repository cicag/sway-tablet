# Screenshots

Captured on the device (800x1280) with `grim` while the session ran the
**GLES2** renderer. Screen capture (`grim`) fails under the Vulkan renderer
(`vulkan_read_pixels: could not find adequate memory type`), so these were taken
by temporarily forcing the GLES2 fallback and then restoring Vulkan.

| File | Contents |
|---|---|
| `01-desktop.png` | sway desktop: photo wallpaper, bottom waybar (launcher, workspaces, clock, Kbd, Rot, Set, battery) and the on-screen keyboard `wvkbd-mobintl` |
| `02-apps.png` | the GTK app grid (`appmenu`) |
| `03-settings.png` | the GTK control panel (`controlpanel`): volume, output devices, brightness, WiFi, Bluetooth, wallpaper |

Reproduce:

```sh
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-1}
export SWAYSOCK=$(ls -t /run/user/$(id -u)/sway-ipc.*.sock | head -1)
grim -o "$(swaymsg -t get_outputs | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["name"])')" desktop.png
# open the apps grid / settings panel, then capture again
```
