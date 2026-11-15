#!/usr/bin/env python3
"""Shared app-grid helpers for sway-tablet Python tools.

Provides the app listing/dedup/sort logic, the gtk-launch command builder,
and the app-tile widget builder so appmenu.py and controlpanel.py draw the
same grid from a single implementation.
"""
import os
import shlex

from gi.repository import Gio, Gtk


def app_choices(log=None):
    """(display name, Gio.AppInfo) pairs, deduped and sorted by name.

    `log` is an optional callable for error reporting (e.g. plog).
    """
    apps, seen = [], set()
    try:
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
            apps.append((name, a))
    except Exception as e:
        if log is not None:
            log("app list err %r" % e)
    apps.sort(key=lambda t: t[0].lower())
    return apps


def launch_cmd_for(app):
    """Build the shell command lisgd/controlpanel runs for a Gio.AppInfo."""
    ident = app.get_id() or ""
    if not ident:
        fn = app.get_filename() or ""
        ident = os.path.basename(fn)
    if ident.endswith(".desktop"):
        ident = ident[:-8]
    return "gtk-launch %s" % shlex.quote(ident)


def make_app_tile(app, name, scale, on_click, icon_px=40, tile_w=140,
                  tile_h=112, spacing=5):
    """Build one app-grid tile button.

    `on_click(app)` is invoked with the Gio.AppInfo when the tile is clicked.
    """
    b = Gtk.Button()
    b.get_style_context().add_class("app-tile")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                  spacing=int(spacing * scale))
    box.set_halign(Gtk.Align.CENTER)
    box.set_valign(Gtk.Align.CENTER)
    try:
        icon = app.get_icon()
    except Exception:
        icon = None
    img = Gtk.Image()
    if icon is not None:
        img.set_from_gicon(icon, Gtk.IconSize.DIALOG)
    else:
        img.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
    img.set_pixel_size(int(icon_px * scale))
    img.set_halign(Gtk.Align.CENTER)
    img.set_valign(Gtk.Align.CENTER)
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
    b.set_size_request(int(tile_w * scale), int(tile_h * scale))
    b.connect("clicked", lambda *_a: on_click(app))
    return b
