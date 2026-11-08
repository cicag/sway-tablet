#!/usr/bin/env python3
import os
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, Gdk, GLib


def load_accent():
    p = os.path.join(os.path.expanduser("~"), ".config", "sway", "accent")
    try:
        t = open(p).read().split()
    except OSError:
        return "#8c272e", "#f5f5f5"
    return (t[0] if t else "#8c272e",
            t[1] if len(t) > 1 else "#f5f5f5")


ACCENT, ONACC = load_accent()
WAYBAR_HEIGHT = int(os.environ.get("WAYBAR_HEIGHT", "48"))

def hex_to_rgba(h, a):
    h = h.lstrip('#')
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {a})"
ACCENT_RGBA_25 = hex_to_rgba(ACCENT, 0.25)
ACCENT_RGBA_40 = hex_to_rgba(ACCENT, 0.40)
ACCENT_RGBA_20 = hex_to_rgba(ACCENT, 0.20)

CSS = ("""
window { background-color: #1e1e2e; color: #cdd6f4; }
window, label, button {
  font-family: "Berkeley Mono", "IBM Plex Mono", "Noto Sans Mono",
               "DejaVu Sans Mono", monospace;
  box-shadow: none; }
.bar { border-bottom: 1px solid rgba(205,214,244,0.08); padding-bottom: 8px; }
.title { font-size: 16px; font-weight: 700; color: #cdd6f4; }
.close { background-image: none; background-color: #313244; color: #cdd6f4;
         border: none; border-radius: 4px; padding: 4px 20px;
         font-size: 16px; }
.close:hover { background-color: #45475a; }
button { background-image: none; background-color: #313244; color: #cdd6f4;
         border: none; border-radius: 4px; padding: 8px; }
button:hover { background-color: #45475a; }
button:active { background-color: %(accent)s; color: %(onacc)s; }
button:active .appname { color: %(onacc)s; }
.appname { font-size: 14px; color: #a6adc8; }
flowbox, scrolledwindow, viewport { background-color: transparent; }
.app-tile {
  background-image: none;
  background-color: %(accent_rgba_20)s;
  color: #cdd6f4;
  border: 1px solid rgba(205,214,244,0.12);
  border-radius: 4px;
}
.app-tile:hover { background-color: %(accent_rgba_40)s; }
""" % {"accent": ACCENT, "onacc": ONACC, "accent_rgba_25": ACCENT_RGBA_25, "accent_rgba_40": ACCENT_RGBA_40, "accent_rgba_20": ACCENT_RGBA_20}).encode()


class AppMenu(Gtk.Window):
    def __init__(self, apps):
        super().__init__(title="Apps")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # Geometry managed by Sway rules (avoids compositor fullscreen).
        try:
            self.set_role("org.swaytablet.appmenu")
        except Exception:
            pass
        self._fit_workarea()
        try:
            disp = Gdk.Display.get_default()
            mon = disp.get_primary_monitor() or disp.get_monitor(0)
            if mon is not None:
                mon.connect("notify::geometry", lambda *_a: self._fit_workarea())
                try:
                    mon.connect("notify::workarea", lambda *_a: self._fit_workarea())
                except Exception:
                    pass
        except Exception:
            pass
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(16)
        # Keep content above the bottom bar (bar can cover input).
        root.set_margin_bottom(WAYBAR_HEIGHT + 16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        self.add(root)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("bar")
        title = Gtk.Label(label="[+] Apps")
        title.get_style_context().add_class("title")
        title.set_xalign(0)
        bar.pack_start(title, True, True, 0)
        close = Gtk.Button(label="[x] Close")
        close.get_style_context().add_class("close")
        close.connect("clicked", lambda *a: Gtk.main_quit())
        bar.pack_end(close, False, False, 0)
        root.pack_start(bar, False, False, 0)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.pack_start(sw, True, True, 0)

        fb = Gtk.FlowBox()
        fb.set_valign(Gtk.Align.START)
        fb.set_selection_mode(Gtk.SelectionMode.NONE)
        fb.set_max_children_per_line(4)
        fb.set_min_children_per_line(4)
        fb.set_row_spacing(8)
        fb.set_column_spacing(8)
        fb.set_homogeneous(True)
        sw.add(fb)

        for app in apps:
            fb.add(self.make_button(app))

    def make_button(self, app):
        b = Gtk.Button()
        b.get_style_context().add_class("app-tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        icon = app.get_icon()
        img = Gtk.Image()
        if icon:
            img.set_from_gicon(icon, Gtk.IconSize.DIALOG)
        else:
            img.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        img.set_pixel_size(48)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        name = app.get_display_name() or app.get_name()
        lbl = Gtk.Label(label=name)
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(14)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_xalign(0.5)
        lbl.set_halign(Gtk.Align.CENTER)
        lbl.get_style_context().add_class("appname")
        box.pack_start(img, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        b.add(box)
        b.set_size_request(180, 150)
        b.connect("clicked", self.launch, app)
        return b

    def launch(self, _b, app):
        try:
            ctx = Gdk.AppLaunchContext()
            app.launch([], ctx)
        except Exception as e:
            print("launch failed:", e)
        Gtk.main_quit()

    def _fit_workarea(self):
        try:
            disp = Gdk.Display.get_default()
            mon = disp.get_primary_monitor() or disp.get_monitor(0)
            if mon is not None and hasattr(mon, "get_workarea"):
                wa = mon.get_workarea()
                if wa.width > 50 and wa.height > 50:
                    self.set_default_size(wa.width, wa.height)
                    self.resize(wa.width, wa.height)
                    return
            if mon is not None:
                geo = mon.get_geometry()
                h = int(os.environ.get("WAYBAR_HEIGHT", "48"))
                if geo.width > 50 and geo.height > h + 50:
                    self.set_default_size(geo.width, geo.height - h)
                    self.resize(geo.width, geo.height - h)
        except Exception:
            pass

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()


def main():
    # GTK3 on Wayland derives app_id from the program name; set it before the
    # first window is created so waybar can find/kill this grid by app_id.
    GLib.set_prgname("org.swaytablet.appmenu")
    try:
        Gdk.set_program_class("org.swaytablet.appmenu")
    except Exception:
        pass
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    screen = Gdk.Screen.get_default()
    Gtk.StyleContext.add_provider_for_screen(
        screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    seen = set()
    apps = []
    for a in Gio.AppInfo.get_all():
        try:
            if not a.should_show():
                continue
        except Exception:
            continue
        name = a.get_display_name() or a.get_name()
        if not name or name in seen:
            continue
        seen.add(name)
        apps.append(a)
    apps.sort(key=lambda a: (a.get_display_name() or a.get_name()).lower())

    win = AppMenu(apps)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
