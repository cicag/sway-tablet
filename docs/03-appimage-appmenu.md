# 03 - AppImage apps in the app menu

`appmenu` builds its grid from `Gio.AppInfo.get_all()`
## Quick start

1. Keep the AppImage in `~/Applications` and make it executable:

   ```sh
   mkdir -p ~/Applications
   mv ~/Downloads/MyApp-x86_64.AppImage ~/Applications/
   chmod +x ~/Applications/MyApp-x86_64.AppImage
   ```

2. Create `~/.local/share/applications/myapp.desktop`:

   ```ini
   [Desktop Entry]
   Type=Application
   Name=My App
   Comment=What the app does
   Exec=full directory of MyApp-x86_64.AppImage
   Icon=application-x-executable
   Terminal=false
   Categories=Utility;
   ```

3. Close and reopen the app menu from the waybar. `appmenu` rescans on every
   start, so no daemon restart is needed.


## Updating an AppImage

The menu only knows the path written in `Exec`. After downloading a new
version you can either:

- keep the filename stable, e.g. always save the new build as
  `~/Applications/Moonlight-x86_64.AppImage`, or
- edit the `Exec=` line in the `.desktop` file to the new filename.

To remove an app from the menu, delete its `.desktop` file. The AppImage in
`~/Applications` can stay there.
