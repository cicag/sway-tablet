#!/usr/bin/env python3
"""Control panel - fullscreen, DESIGN.md structure with the dark tablet theme.

Structure follows DESIGN.md: monospaced text, bracketed [+] / [-] / [x] ASCII
markers, hairline-bordered .box cards, 4px radii and .btn-item action buttons.
Colours are intentionally the tablet's dark theme (#1e1e2e / accent) instead of
DESIGN.md's cream palette.

The window is fullscreen, but waybar is a layer-shell client that stays on top
of the bottom 48px. The root box therefore reserves a fixed gap at the bottom
so no content is hidden behind the bar.
"""
import gi
import glob
import json
import math
import os
import re
import shlex
import subprocess
import sys
import threading
import time

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf  # noqa: E402

HOME = os.path.expanduser("~")
BACKLIGHT = "/sys/class/backlight/intel_backlight"
WALL_FILE = os.path.join(HOME, ".config", "sway", "wallpaper")
WALL_DIRS = [os.path.join(HOME, "wallpapers")]
WALL_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

ACCENT_FILE = os.path.join(HOME, ".config", "sway", "accent")
ACCENT_DEF = "#89b4fa"
ONACC_DEF = "#1e1e2e"
ACCENT = ACCENT_DEF
ONACC = ONACC_DEF

# waybar is anchored to the bottom and is NOT covered by a fullscreen toplevel
# (it is a layer-shell client). Keep this gap free so the panel is never
# obscured. Override the bar height with WAYBAR_HEIGHT if the config changes.
WAYBAR_HEIGHT = int(os.environ.get("WAYBAR_HEIGHT", "48"))
BOTTOM_GAP = 8

SUDO = "/usr/bin/sudo"
SYSTEMCTL = "/usr/bin/systemctl"
ZEROTIER = "zerotier-one"

os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _find_sway_sock():
    try:
        socks = sorted(
            glob.glob(os.path.join(os.environ["XDG_RUNTIME_DIR"],
                                   "sway-ipc.*.sock")),
            key=os.path.getmtime)
        return socks[-1] if socks else ""
    except Exception:
        return ""


if not os.environ.get("SWAYSOCK"):
    _sock = _find_sway_sock()
    if _sock:
        os.environ["SWAYSOCK"] = _sock


def list_wallpapers():
    seen, out = set(), []
    for d in WALL_DIRS:
        try:
            names = sorted(os.listdir(d))
        except Exception:
            continue
        for n in names:
            p = os.path.join(d, n)
            if n.lower().endswith(WALL_EXTS) and os.path.isfile(p) and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def current_wallpaper():
    try:
        return open(WALL_FILE).read().strip()
    except Exception:
        return ""


def load_accent():
    global ACCENT, ONACC
    try:
        toks = open(ACCENT_FILE).read().split()
        ACCENT = toks[0] if toks else ACCENT_DEF
        ONACC = toks[1] if len(toks) > 1 else ONACC_DEF
    except Exception:
        ACCENT, ONACC = ACCENT_DEF, ONACC_DEF
    return ACCENT, ONACC


def hex_rgb(c):
    c = (c or "#000000").lstrip("#")
    try:
        return (int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0,
                int(c[4:6], 16) / 255.0)
    except Exception:
        return (0.54, 0.71, 0.98)


def hex_darken(c, f):
    r, g, b = hex_rgb(c)
    return "#%02x%02x%02x" % (int(r * 255 * f), int(g * 255 * f),
                              int(b * 255 * f))


def hex_to_rgba(c, a):
    c = (c or "#000000").lstrip("#")
    try:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return "rgba(%d, %d, %d, %s)" % (r, g, b, a)
    except Exception:
        return "rgba(137, 180, 250, %s)" % a


def ui_scale():
    try:
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        g = mon.get_geometry()
        return 1.0 if g.width >= g.height else 1.2
    except Exception:
        return 1.25


def monitor_size():
    """Current logical size of the primary monitor (follows rotation)."""
    try:
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        g = mon.get_geometry()
        return g.width, g.height
    except Exception:
        return 0, 0


def make_css(scale):
    """Scale-aware overlay loaded on top of gtk-theme.css."""
    def p(x):
        return max(1, int(round(x * scale)))
    return ("""
.title { font-size: %(title)dpx; font-weight: bold; color: #cdd6f4; }
.close { font-size: %(cf)dpx; padding: %(cpy)dpx %(cpx)dpx; border-radius: 4px; }
.card, .box { border-radius: 4px; padding: %(crd2)dpx; }
.label-sub.bold { font-size: %(rl)dpx; }
.label-sub.accent { font-size: %(vl)dpx; }
.label-sub { font-size: %(sub)dpx; }
switch { font-size: %(swf)dpx; border-radius: %(swr)dpx; }
switch slider { min-width: %(sws)dpx; min-height: %(sws)dpx; border-radius: %(swsr)dpx; }
button.btn-thumb { padding: 2px; border-radius: 4px; }

/* controlpanel-specific structural bits (DESIGN.md: 4px radii, hairlines) */
button.btn-mini {
  font-size: %(bmf)dpx;
  padding: %(bmpy)dpx %(bmpx)dpx;
  border-radius: 4px;
  margin: 0;
  min-height: 0;
  min-width: 0;
}
button.action-tile {
  padding: %(atpad)dpx;
  border-radius: 4px;
  margin: 0;
  min-height: %(atmin)dpx;
}
.tile-mark { font-size: %(tm)dpx; font-weight: 700; color: #cdd6f4; }
.tile-name { font-size: %(tn)dpx; font-weight: 700; color: #cdd6f4; }
.tile-sub  { font-size: %(ts)dpx; color: #a6adc8; }
.net-row {
  border-bottom: 1px solid rgba(205, 214, 244, 0.08);
  padding-bottom: %(netpad)dpx;
  margin-bottom: %(netpad)dpx;
}
.net-meta { font-size: %(nm)dpx; color: #a6adc8; }
.wall-near { opacity: 0.72; }
.wall-far { opacity: 0.42; }
.action-box { padding: %(abpad)dpx; }
""" % {
        "title": p(20), "cf": p(16), "cpy": p(7), "cpx": p(19),
        "crd2": p(12), "rl": p(15), "vl": p(14), "sub": p(11),
        "swf": p(17), "swr": p(13), "sws": p(22), "swsr": p(11),
        "bmf": p(12), "bmpy": p(5), "bmpx": p(9),
        "atpad": p(10), "atmin": p(52),
        "tm": p(15), "tn": p(14), "ts": p(11),
        "netpad": p(6), "abpad": p(8), "nm": p(11),
    })


def apply_css(scale):
    load_accent()
    accent_rgba_25 = hex_to_rgba(ACCENT, 0.25)
    accent_rgba_40 = hex_to_rgba(ACCENT, 0.40)
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "gtk-theme.css")
    base = open(css_path).read() % {"accent": ACCENT, "onacc": ONACC,
                                    "accent_rgba_25": accent_rgba_25,
                                    "accent_rgba_40": accent_rgba_40}
    overlay = make_css(scale)
    prov = Gtk.CssProvider()
    prov.load_from_data((base + "\n" + overlay).encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return prov


def run(cmd, timeout=12):
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=timeout,
                             env=dict(os.environ, NO_COLOR="1"))
        return out.stdout.decode(errors="replace").strip()
    except Exception:
        return ""


PLOG = "/tmp/panel-diag.log"


def plog(msg):
    try:
        with open(PLOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def qrun(cmd, timeout=12):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, env=dict(os.environ, NO_COLOR="1"))
        return (p.returncode,
                p.stdout.decode(errors="replace").strip(),
                p.stderr.decode(errors="replace").strip())
    except Exception as e:
        return -1, "", str(e)


def add_classes(widget, *names):
    """Add several CSS classes (a dotted selector means several classes)."""
    ctx = widget.get_style_context()
    for name in names:
        ctx.add_class(name)


def tsplit(line):
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def read_backlight():
    try:
        cur = int(open(BACKLIGHT + "/brightness").read().strip())
        mx = int(open(BACKLIGHT + "/max_brightness").read().strip())
        return int(round(cur * 100.0 / mx)), mx
    except Exception:
        return 50, 100


def read_volume():
    s = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    try:
        return max(0, min(100, int(round(float(s.split()[1]) * 100))))
    except Exception:
        return 50


def list_streams():
    try:
        p = subprocess.run(["pw-dump"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=8,
                           env=dict(os.environ, NO_COLOR="1"))
        data = json.loads(p.stdout.decode(errors="replace") or "[]")
    except Exception:
        return []
    out = []
    for o in data:
        info = o.get("info", {}) or {}
        props = info.get("props", {}) or {}
        if "Stream/Output" not in props.get("media.class", ""):
            continue
        app = (props.get("application.name") or props.get("node.name")
               or props.get("media.name") or "app")
        name = props.get("media.name") or props.get("node.name") or ""
        vol, mute = 100, False
        for pr in (info.get("params", {}) or {}).get("Props", []) or []:
            if "volume" in pr:
                try:
                    vol = max(0, min(150, int(round(float(pr["volume"]) * 100))))
                except Exception:
                    pass
            if "mute" in pr:
                mute = bool(pr["mute"])
        out.append({"id": o.get("id"), "app": app, "name": name,
                    "vol": vol, "mute": mute})
    return out


def list_sinks():
    out = run(["wpctl", "status"])
    sinks, inside = [], False
    for line in out.splitlines():
        if "Sinks:" in line:
            inside = True
            continue
        if inside and ("Sources:" in line or "Sink endpoints" in line or
                       "Sources endpoints" in line or "Filters:" in line or
                       "Devices:" in line):
            break
        if inside:
            m = re.match(r"\s*[│├└─\s]*(\*?)\s*(\d+)\.\s*(.+?)\s*\[vol:", line)
            if m:
                sinks.append({"default": m.group(1) == "*",
                              "id": int(m.group(2)),
                              "name": m.group(3).strip()})
    return sinks


# ---------------------------------------------------------------------------
# system state helpers
# ---------------------------------------------------------------------------
def wifi_enabled():
    return run(["nmcli", "radio", "wifi"]).strip() == "enabled"


def bt_enabled():
    for line in run(["bluetoothctl", "show"]).splitlines():
        if "Powered:" in line:
            return line.split(":")[1].strip().lower() == "yes"
    return False


def wifi_iface():
    for line in run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev",
                     "status"]).splitlines():
        f = tsplit(line)
        if len(f) >= 2 and f[1] == "wifi":
            return f[0]
    return "wlan0"


def wifi_info():
    iface = wifi_iface()
    ip = gw = dns = ""
    out = run(["nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS",
               "dev", "show", iface])
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.startswith("IP4.ADDRESS") and not ip:
            ip = v.split("/")[0]
        elif k == "IP4.GATEWAY" and not gw:
            gw = v
        elif k.startswith("IP4.DNS") and not dns:
            dns = v
    return iface, ip, gw, dns


def wifi_list():
    out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
               "dev", "wifi", "list", "--rescan", "no"])
    nets = []
    for line in out.splitlines():
        f = tsplit(line)
        while len(f) < 4:
            f.append("")
        inuse, ssid, signal, sec = f[0], f[1], f[2], f[3]
        if not ssid:
            continue
        try:
            sig = int(signal)
        except ValueError:
            sig = 0
        nets.append({"inuse": inuse.strip() in ("*", "yes"),
                     "ssid": ssid, "signal": sig, "sec": sec})
    # one entry per SSID, prefer the connected one
    merged = {}
    for n in nets:
        old = merged.get(n["ssid"])
        if old is None or n["inuse"] or n["signal"] > old["signal"]:
            merged[n["ssid"]] = n
    return list(merged.values())


def wifi_saved():
    """Map saved Wi-Fi connection name (usually the SSID) -> UUID."""
    conns = {}
    out = run(["nmcli", "-t", "-f", "NAME,TYPE,UUID", "connection", "show"])
    for line in out.splitlines():
        f = tsplit(line)
        if len(f) >= 3 and f[1] == "802-11-wireless":
            conns[f[0]] = f[2] or f[0]
    return conns


def bt_battery(mac):
    """Battery percentage reported by BlueZ (Battery1), or None."""
    out = run(["bluetoothctl", "info", mac])
    for line in out.splitlines():
        if "Battery Percentage" not in line:
            continue
        # bluetoothctl prints: Battery Percentage: 0x64 (100)
        m = re.search(r"Battery Percentage:\s*0x[0-9a-fA-F]+\s*\((\d+)\)", line)
        if m:
            return int(m.group(1))
        m = re.search(r"Battery Percentage:\s*(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def bt_devices():
    known, conn, paired = {}, set(), set()
    for line in run(["bluetoothctl", "devices"]).splitlines():
        p = line.split(" ", 2)
        if len(p) == 3 and p[0] == "Device":
            known[p[1]] = p[2]
    for line in run(["bluetoothctl", "devices", "Connected"]).splitlines():
        p = line.split(" ", 2)
        if len(p) == 3:
            conn.add(p[1])
    for line in run(["bluetoothctl", "devices", "Paired"]).splitlines():
        p = line.split(" ", 2)
        if len(p) == 3:
            paired.add(p[1])
    out = []
    for m, n in known.items():
        bat = bt_battery(m) if m in conn else None
        out.append({"mac": m, "name": n, "connected": m in conn,
                    "paired": m in paired, "battery": bat})
    return out


def sway_output():
    try:
        data = json.loads(run(["swaymsg", "-t", "get_outputs"]))
    except Exception:
        return "", ""
    for o in data:
        if not o.get("headless") and o.get("name"):
            return o["name"], o.get("transform", "normal")
    return "", ""


TRANSFORMS = ["normal", "90", "180", "270"]


def rotate_output():
    name, cur = sway_output()
    if not name:
        return "normal"
    try:
        nxt = TRANSFORMS[(TRANSFORMS.index(cur) + 1) % len(TRANSFORMS)]
    except ValueError:
        nxt = "90"
    qrun(["swaymsg", "output", name, "transform", nxt], timeout=8)
    return nxt


def zerotier_state():
    en = run([SYSTEMCTL, "is-enabled", ZEROTIER]).strip() == "enabled"
    ac = run([SYSTEMCTL, "is-active", ZEROTIER]).strip() == "active"
    return en, ac


def zerotier_toggle():
    """Enable+start or disable+stop. Returns an error string ('' on success)."""
    en, _ac = zerotier_state()
    steps = (["disable", "stop"] if en else ["enable", "start"])
    for step in steps:
        rc, _out, err = qrun([SUDO, "-n", SYSTEMCTL, step, ZEROTIER],
                             timeout=25)
        if rc != 0:
            return err or ("failed: systemctl %s" % step)
    return ""


def power_action(kind):
    cmd = [SYSTEMCTL, "poweroff" if kind == "off" else "reboot"]
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as e:
        plog("power action error %r" % e)


# ---------------------------------------------------------------------------
# custom slider (unchanged, follows the accent)
# ---------------------------------------------------------------------------
class HSlider(Gtk.DrawingArea):
    def __init__(self, lo, hi, value, cb, scale=1.0):
        super().__init__()
        self.lo, self.hi = lo, hi
        self.value = value
        self.cb = cb
        self.pad = max(8, int(round(23 * scale)))
        self.th = max(8, int(round(25 * scale)))
        self.knob = max(8, int(round(19 * scale)))
        self.set_size_request(-1, max(28, int(round(69 * scale))))
        self.set_hexpand(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON1_MOTION_MASK |
                        Gdk.EventMask.TOUCH_MASK)
        self.dragging = False
        self.armed = False
        GLib.timeout_add(600, self._arm)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("motion-notify-event", self.on_motion)

    def _arm(self):
        self.armed = True
        return False

    def set_value(self, v, notify=True):
        v = max(self.lo, min(self.hi, v))
        self.value = v
        self.queue_draw()
        if notify and self.cb:
            self.cb(v)

    def _value_from_x(self, x):
        w = self.get_allocated_width()
        left, right = self.pad, w - self.pad
        if right <= left:
            return self.value
        frac = max(0.0, min(1.0, (x - left) / float(right - left)))
        return self.lo + frac * (self.hi - self.lo)

    def on_press(self, _w, e):
        if not self.armed:
            return False
        self.dragging = True
        self.set_value(self._value_from_x(e.x))
        return True

    def on_release(self, _w, _e):
        self.dragging = False
        return False

    def on_motion(self, _w, e):
        if not self.dragging:
            return False
        self.set_value(self._value_from_x(e.x))
        return True

    def _round(self, cr, x, y, w, h, r):
        r = min(r, w / 2.0, h / 2.0) if h > 0 else w / 2.0
        if h <= 0 or w <= 0:
            return
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def on_draw(self, w, cr):
        W = self.get_allocated_width()
        H = self.get_allocated_height()
        cy = H / 2.0
        th = self.th
        y = cy - th / 2.0
        x0, x1 = self.pad, W - self.pad
        cr.set_source_rgb(0x1e / 255, 0x1e / 255, 0x2e / 255)
        self._round(cr, x0, y, x1 - x0, th, th / 2.0)
        cr.fill()
        frac = (self.value - self.lo) / float(self.hi - self.lo)
        fx = x0 + frac * (x1 - x0)
        cr.set_source_rgb(*hex_rgb(ACCENT))
        self._round(cr, x0, y, fx - x0, th, th / 2.0)
        cr.fill()
        cr.set_source_rgb(0xcd / 255, 0xd6 / 255, 0xf4 / 255)
        cr.arc(fx, cy, self.knob, 0, 2 * math.pi)
        cr.fill()


# ---------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------
class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(title="Settings")
        self.set_decorated(False)
        try:
            self.set_role("org.swaytablet.controlpanel")
        except Exception:
            pass
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

        self.guard = True
        self._sync = False
        self.scale = ui_scale()
        self.vol_pending = self.vol_to = None
        self.bri_pending = self.bri_to = None
        self.bri_max = 100
        self.wifi_nets = []
        self.bt_devs = []
        self.sink_list = []
        self._sink_guard = False
        self.streams = []
        self.app_sliders = []
        self.wall_cur = current_wallpaper()
        self.wall_pics = []
        self.wall_btns = {}
        self.wall_avail = 0
        self._wall_busy = False
        self._rot_pending = False
        self.zt_error = ""

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=int(8 * self.scale))
        for m in ("top", "start", "end"):
            getattr(root, "set_margin_" + m)(int(9 * self.scale))
        # fixed gap for waybar (its 48px layer is not covered by fullscreen)
        root.set_margin_bottom(WAYBAR_HEIGHT + int(round(BOTTOM_GAP * self.scale)))
        self.add(root)

        # ---- title bar ---------------------------------------------------
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=int(8 * self.scale))
        bar.get_style_context().add_class("bar")
        title = Gtk.Label(label="[+] Settings")
        title.get_style_context().add_class("title")
        title.set_xalign(0)
        bar.pack_start(title, True, True, 0)
        close = Gtk.Button(label="[x] Close")
        close.get_style_context().add_class("close")
        close.connect("clicked", lambda *a: Gtk.main_quit())
        bar.pack_end(close, False, False, 0)
        root.pack_start(bar, False, False, 0)

        # ---- scrolling body ---------------------------------------------
        v = int(read_volume())
        b, self.bri_max = read_backlight()
        self.vol_card, self.vol, self.vol_val = self.slider_card(
            "Volume", 0, 100, v, self.on_vol, devices=True, streams=True)
        self.bri_card, self.bri, self.bri_val = self.slider_card(
            "Brightness", 5, 100, b, self.on_bri)
        self.wifi_card = self.net_card("WiFi", "wifi")
        self.bt_card = self.net_card("Bluetooth", "bt")
        self.wall_card = self.wall_card_ui()

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=int(8 * self.scale))
        body.set_hexpand(True)
        for c in (self.vol_card, self.bri_card,
                  self.wifi_card, self.bt_card, self.wall_card):
            body.pack_start(c, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(True)
        scroll.add(body)
        root.pack_start(scroll, True, True, 0)

        # ---- fixed bottom action bar -------------------------------------
        root.pack_end(self.action_bar(), False, False, 0)

        self.guard = False
        try:
            disp = Gdk.Display.get_default()
            mon = disp.get_primary_monitor() or disp.get_monitor(0)
            if mon is not None:
                mon.connect("notify::geometry", self.on_monitor_geometry)
        except Exception:
            pass
        self.fullscreen()
        GLib.idle_add(self.first_refresh)
        GLib.timeout_add_seconds(5, self.refresh_sinks)
        GLib.timeout_add_seconds(1, self.poll_volume)
        GLib.timeout_add_seconds(2, self.refresh_streams)
        GLib.timeout_add_seconds(5, self._zt_tick)

    # ---- generic card / button helpers ----------------------------------
    def card_head(self, text, actions=None):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                       spacing=int(8 * self.scale))
        lbl = Gtk.Label(label=text)
        add_classes(lbl, "label-sub", "bold")
        lbl.set_xalign(0)
        head.pack_start(lbl, True, True, 0)
        for a in actions or []:
            head.pack_end(a, False, False, 0)
        return head

    def new_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=int(8 * self.scale))
        card.get_style_context().add_class("box")
        for m in ("top", "bottom", "start", "end"):
            getattr(card, "set_margin_" + m)(int(8 * self.scale))
        return card

    def mini(self, label, cb, danger=False):
        b = Gtk.Button(label=label)
        ctx = b.get_style_context()
        ctx.add_class("btn-item")
        ctx.add_class("btn-mini")
        if danger:
            ctx.add_class("btn-danger")
        b.set_halign(Gtk.Align.START)
        b.connect("clicked", lambda *a: cb())
        return b

    def net_item(self, active, name, meta, actions):
        """One network/device row: name + actions on one line, meta below."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=int(8 * self.scale))
        row.get_style_context().add_class("net-row")

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       spacing=int(2 * self.scale))
        left.set_hexpand(True)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=int(8 * self.scale))
        mark = Gtk.Label(label="[+]" if active else "[ ]")
        mark.get_style_context().add_class("tile-mark")
        if active:
            add_classes(mark, "label-sub", "accent")
        nm = Gtk.Label(label=name)
        nm.set_xalign(0)
        nm.set_ellipsize(Pango.EllipsizeMode.END)
        if active:
            add_classes(nm, "label-sub", "bold")
        top.pack_start(mark, False, False, 0)
        top.pack_start(nm, True, True, 0)
        left.pack_start(top, False, False, 0)

        sub = Gtk.Label(label=meta)
        sub.get_style_context().add_class("net-meta")
        sub.set_xalign(0)
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        sub.set_margin_start(int(26 * self.scale))
        left.pack_start(sub, False, False, 0)
        row.pack_start(left, True, True, 0)

        acts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                       spacing=int(5 * self.scale))
        acts.set_valign(Gtk.Align.START)
        for b in actions:
            acts.pack_start(b, False, False, 0)
        row.pack_end(acts, False, False, 0)
        return row

    def item_row(self, label, side, active, cb):
        b = Gtk.Button()
        b.get_style_context().add_class("btn-item")
        if active:
            add_classes(b, "on")
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                    spacing=int(7 * self.scale))
        l = Gtk.Label(label=label)
        l.set_xalign(0)
        l.set_ellipsize(Pango.EllipsizeMode.END)
        h.pack_start(l, True, True, 0)
        if side:
            s = Gtk.Label(label=side)
            s.get_style_context().add_class("label-sub")
            s.set_xalign(1)
            h.pack_end(s, False, False, 0)
        b.add(h)
        b.connect("clicked", lambda *a: cb())
        return b

    def _clear(self, box):
        for c in box.get_children():
            box.remove(c)

    def bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ---- cards ----------------------------------------------------------
    def slider_card(self, name, lo, hi, value, cb, devices=False,
                    streams=False):
        card = self.new_card()
        card.set_hexpand(True)
        val = Gtk.Label(label="%d%%" % int(value))
        add_classes(val, "label-sub", "accent")
        val.set_xalign(1)
        card.pack_start(self.card_head("[+] " + name, [val]), False, False, 0)
        scale = HSlider(lo, hi, int(value), cb, scale=self.scale)
        scale.set_valign(Gtk.Align.CENTER)
        card.pack_start(scale, False, False, 0)
        if devices:
            dlbl = Gtk.Label(label="[+] Output device")
            dlbl.get_style_context().add_class("label-sub")
            dlbl.set_xalign(0)
            card.pack_start(dlbl, False, False, 0)
            self.sink_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=int(5 * self.scale))
            card.pack_start(self.sink_box, False, False, 0)
        if streams:
            albl = Gtk.Label(label="[+] App volume")
            albl.get_style_context().add_class("label-sub")
            albl.set_xalign(0)
            albl.set_margin_top(int(7 * self.scale))
            card.pack_start(albl, False, False, 0)
            self.app_status = Gtk.Label(label="")
            self.app_status.get_style_context().add_class("label-sub")
            self.app_status.set_xalign(0)
            card.pack_start(self.app_status, False, False, 0)
            self.app_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=int(8 * self.scale))
            card.pack_start(self.app_box, False, False, 0)
        return card, scale, val

    def net_card(self, title, kind):
        card = self.new_card()

        sw = Gtk.Switch()
        sw.set_halign(Gtk.Align.END)
        card.pack_start(self.card_head("[+] " + title, [sw]), False, False, 0)

        status = Gtk.Label(label="")
        status.get_style_context().add_class("label-sub")
        status.set_xalign(0)
        status.set_line_wrap(True)
        card.pack_start(status, False, False, 0)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        spacing=int(7 * self.scale))
        scan = Gtk.Button(label="[+] Scan")
        scan.get_style_context().add_class("btn-item")
        scan.get_style_context().add_class("btn-mini")
        scan.set_halign(Gtk.Align.START)
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        spacing=int(5 * self.scale))
        inner.pack_start(scan, False, False, 0)
        inner.pack_start(items, False, False, 0)
        card.pack_start(inner, False, False, 0)

        if kind == "wifi":
            self.wifi_sw, self.wifi_rev = sw, inner
            self.wifi_status, self.wifi_box = status, items
            sw.set_active(wifi_enabled())
            sw.connect("notify::active", self.on_wifi)
            scan.connect("clicked", lambda *a: self.scan_wifi())
        else:
            self.bt_sw, self.bt_rev = sw, inner
            self.bt_status, self.bt_box = status, items
            sw.set_active(bt_enabled())
            sw.connect("notify::active", self.on_bt)
            scan.connect("clicked", lambda *a: self.scan_bt())
        return card

    def wall_card_ui(self):
        card = self.new_card()
        more = Gtk.Button(label="[+] Reload")
        more.get_style_context().add_class("btn-item")
        more.get_style_context().add_class("btn-mini")
        card.pack_start(self.card_head("[+] Wallpaper", [more]),
                        False, False, 0)
        more.connect("clicked", lambda *a: self.refresh_wall())

        self.wall_status = Gtk.Label(label="")
        self.wall_status.get_style_context().add_class("label-sub")
        self.wall_status.set_xalign(0)
        self.wall_status.set_line_wrap(True)
        card.pack_start(self.wall_status, False, False, 0)

        # Carousel: the picked wallpaper is always in the middle, with its
        # neighbours dimmed and smaller on both sides.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=int(6 * self.scale))
        prev = Gtk.Button(label="[<]")
        prev.get_style_context().add_class("btn-item")
        prev.get_style_context().add_class("btn-mini")
        prev.connect("clicked", lambda *a: self.wall_step(-1))
        nxt = Gtk.Button(label="[>]")
        nxt.get_style_context().add_class("btn-item")
        nxt.get_style_context().add_class("btn-mini")
        nxt.connect("clicked", lambda *a: self.wall_step(1))

        self.wall_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=int(8 * self.scale))
        self.wall_strip.set_halign(Gtk.Align.CENTER)
        self.wall_strip.set_hexpand(True)
        self.wall_row = row
        self.wall_prev = prev
        self.wall_next = nxt
        row.connect("size-allocate", self.on_wall_alloc)
        row.pack_start(prev, False, False, 0)
        row.pack_start(self.wall_strip, True, True, 0)
        row.pack_end(nxt, False, False, 0)
        card.pack_start(row, False, False, 0)
        return card

    # ---- fixed bottom action bar ---------------------------------------
    def action_tile(self, mark, name, sub, cb):
        b = Gtk.Button()
        ctx = b.get_style_context()
        ctx.add_class("btn-item")
        ctx.add_class("action-tile")
        h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                    spacing=int(6 * self.scale))
        m = Gtk.Label(label=mark)
        m.get_style_context().add_class("tile-mark")
        n = Gtk.Label(label=name)
        n.get_style_context().add_class("tile-name")
        h.pack_start(m, False, False, 0)
        h.pack_start(n, False, False, 0)
        s = Gtk.Label(label=sub)
        s.get_style_context().add_class("tile-sub")
        s.set_xalign(0)
        s.set_ellipsize(Pango.EllipsizeMode.END)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                    spacing=int(2 * self.scale))
        v.pack_start(h, False, False, 0)
        v.pack_start(s, False, False, 0)
        b.add(v)
        b.connect("clicked", lambda *a: cb())
        return b, m, s

    def action_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=int(6 * self.scale))
        bar.get_style_context().add_class("box")
        bar.get_style_context().add_class("action-box")

        self.rot_btn, self.rot_mark, self.rot_sub = self.action_tile(
            "[+]", "Rotate", "screen", self.do_rotate)
        self.pwr_btn, _m, _s = self.action_tile(
            "[-]", "Shut down", "power", lambda: power_action("off"))
        self.rst_btn, _m, _s = self.action_tile(
            "[-]", "Restart", "power", lambda: power_action("restart"))
        self.zt_btn, self.zt_mark, self.zt_sub = self.action_tile(
            "[+]", "ZeroTier", "checking...", self.do_zerotier)

        for t in (self.rot_btn, self.pwr_btn, self.rst_btn, self.zt_btn):
            t.set_hexpand(True)
            bar.pack_start(t, True, True, 0)
        return bar

    # ---- startup / periodic refresh ------------------------------------
    def first_refresh(self):
        self.refresh_wifi()
        self.refresh_bt()
        self.refresh_sinks()
        self.refresh_wall()
        self.refresh_streams()
        self.refresh_rotate()
        self.refresh_zerotier()
        return False

    def refresh_rotate(self):
        _name, cur = sway_output()
        deg = {"normal": "0°", "90": "90°", "180": "180°", "270": "270°"}
        self.rot_sub.set_text("screen %s" % deg.get(cur, cur or "-"))
        return False

    def refresh_zerotier(self):
        en, act = zerotier_state()
        if en:
            self.zt_mark.set_text("[+]")
            self.zt_btn.get_style_context().add_class("on")
            self.zt_sub.set_text("active" if act else "enabled (stopped)")
        else:
            self.zt_mark.set_text("[-]")
            self.zt_btn.get_style_context().remove_class("on")
            self.zt_sub.set_text("disabled")
        return False

    def _zt_tick(self):
        self.refresh_zerotier()
        return True

    def do_rotate(self):
        nxt = rotate_output()
        deg = {"normal": "0°", "90": "90°", "180": "180°", "270": "270°"}
        self.rot_sub.set_text("screen %s" % deg.get(nxt, nxt))

    def do_zerotier(self):
        self.zt_sub.set_text("working...")
        self.zt_error = ""

        def work():
            err = zerotier_toggle()
            GLib.idle_add(self._zt_done, err)
        self.bg(work)

    def _zt_done(self, err):
        self.refresh_zerotier()
        if err:
            self.zt_sub.set_text("failed (sudo?)")
            plog("zerotier: %s" % err)
        return False

    # ---- wifi -----------------------------------------------------------
    def refresh_wifi(self):
        en = wifi_enabled()
        self._set_switch(self.wifi_sw, en)
        self.wifi_nets = wifi_list() if en else []
        saved = wifi_saved()
        active = next((n for n in self.wifi_nets if n["inuse"]), None)
        if not en:
            self.wifi_status.set_text("disabled")
        elif active:
            txt = "[+] Connected: %s (%d%% \u00b7 %s)" % (
                active["ssid"], active["signal"],
                active["sec"] if active["sec"] and active["sec"] != "--"
                else "open")
            iface, ip, gw, dns = wifi_info()
            if iface:
                txt += "\n     Device: %s" % iface
            if ip:
                txt += "\n     IP: %s" % ip
                if gw:
                    txt += "  \u00b7  Gateway: %s" % gw
            if dns:
                txt += "\n     DNS: %s" % dns
            self.wifi_status.set_text(txt)
        else:
            iface, _ip, _gw, _dns = wifi_info()
            self.wifi_status.set_text(
                "[ ] Not connected" + (" (%s)" % iface if iface else ""))
        self._clear(self.wifi_box)
        nets = sorted(self.wifi_nets,
                      key=lambda n: (not n["inuse"], -n["signal"]))
        if not nets and en:
            empty = Gtk.Label(label="[ ] No networks - tap Scan")
            empty.get_style_context().add_class("label-sub")
            empty.set_xalign(0)
            self.wifi_box.pack_start(empty, False, False, 0)
        for n in nets:
            self.wifi_box.pack_start(self.wifi_row(n, saved), False, False, 0)
        self.wifi_box.show_all()
        self.wifi_rev.set_visible(en)

    def wifi_row(self, n, saved):
        sec = n["sec"] if n["sec"] and n["sec"] != "--" else "open"
        meta = "%d%% signal \u00b7 %s" % (n["signal"], sec)
        actions = []
        if n["inuse"]:
            actions.append(self.mini("[x] Disconnect", self.wifi_disconnect))
        else:
            actions.append(
                self.mini("[+] Connect", lambda nn=n: self.wifi_connect(nn)))
        if n["inuse"] or n["ssid"] in saved:
            actions.append(
                self.mini("[x] Forget",
                          lambda s=n["ssid"]: self.wifi_forget(s),
                          danger=True))
        return self.net_item(n["inuse"], n["ssid"], meta, actions)

    def scan_wifi(self):
        self.wifi_status.set_text("scanning...")

        def work():
            run(["nmcli", "dev", "wifi", "rescan"], timeout=15)
            time.sleep(4)
            GLib.idle_add(self.refresh_wifi)
        self.bg(work)

    def wifi_connect(self, n):
        ssid = n["ssid"]
        saved = wifi_saved()
        pw = None
        if n["sec"] and n["sec"] not in ("", "--") and ssid not in saved:
            pw = self.modal("Password",
                            "Password for %s" % ssid,
                            entry=True, ok_label="[+] Connect")
            if pw is None:
                return
        self.wifi_status.set_text("connecting %s..." % ssid)

        def work():
            cmd = ["nmcli", "dev", "wifi", "connect", ssid]
            if pw:
                cmd += ["password", pw]
            rc, out, err = qrun(cmd, timeout=35)
            if rc != 0:
                GLib.idle_add(self._wifi_error,
                              (err or out or "connection failed"))
            GLib.idle_add(self.refresh_wifi)
        self.bg(work)

    def _wifi_error(self, msg):
        self.wifi_status.set_text("[x] " + msg.splitlines()[-1][:160])
        return False

    def wifi_disconnect(self):
        self.wifi_status.set_text("disconnecting...")

        def work():
            qrun(["nmcli", "dev", "disconnect", wifi_iface()], timeout=20)
            GLib.idle_add(self.refresh_wifi)
        self.bg(work)

    def wifi_forget(self, ssid):
        if not self.modal("Forget network",
                          "Delete the saved profile for %s?" % ssid,
                          ok_label="[x] Forget"):
            return
        uuid = wifi_saved().get(ssid)
        if not uuid:
            return

        def work():
            if any(n["inuse"] and n["ssid"] == ssid for n in self.wifi_nets):
                qrun(["nmcli", "dev", "disconnect", wifi_iface()], timeout=20)
            qrun(["nmcli", "connection", "delete", uuid], timeout=20)
            GLib.idle_add(self.refresh_wifi)
        self.bg(work)

    # ---- bluetooth ------------------------------------------------------
    def refresh_bt(self):
        en = bt_enabled()
        self._set_switch(self.bt_sw, en)
        self.bt_devs = bt_devices() if en else []
        conn = [d for d in self.bt_devs if d["connected"]]
        if not en:
            self.bt_status.set_text("disabled")
        elif conn:
            self.bt_status.set_text(
                "[+] Connected: " + ", ".join(d["name"] for d in conn))
        else:
            self.bt_status.set_text("[ ] Not connected")
        self._clear(self.bt_box)
        devs = sorted(self.bt_devs,
                      key=lambda d: (not d["connected"], not d["paired"],
                                     d["name"].lower()))
        if not devs and en:
            empty = Gtk.Label(label="[ ] No devices yet - tap Scan")
            empty.get_style_context().add_class("label-sub")
            empty.set_xalign(0)
            self.bt_box.pack_start(empty, False, False, 0)
        for d in devs:
            self.bt_box.pack_start(self.bt_row(d), False, False, 0)
        self.bt_box.show_all()
        self.bt_rev.set_visible(en)

    def bt_row(self, d):
        if d["connected"]:
            state = "connected"
            if d.get("battery") is not None:
                state += " \u00b7 %d%% battery" % d["battery"]
        elif d["paired"]:
            state = "saved"
        else:
            state = "new"
        actions = []
        if d["connected"]:
            actions.append(
                self.mini("[x] Disconnect",
                          lambda dd=d: self.bt_disconnect(dd)))
        else:
            actions.append(
                self.mini("[+] Connect", lambda dd=d: self.bt_connect(dd)))
        if d["paired"] or d["connected"]:
            actions.append(
                self.mini("[x] Forget", lambda dd=d: self.bt_forget(dd),
                          danger=True))
        return self.net_item(d["connected"], d["name"], state, actions)

    def scan_bt(self):
        self.bt_status.set_text("scanning...")

        def work():
            run(["bluetoothctl", "--timeout", "8", "scan", "on"], timeout=15)
            GLib.idle_add(self.refresh_bt)
        self.bg(work)

    def bt_connect(self, d):
        self.bt_status.set_text("connecting %s..." % d["name"])

        def work():
            rc, out, err = qrun(["bluetoothctl", "connect", d["mac"]],
                                timeout=30)
            if rc != 0:
                GLib.idle_add(self._bt_error, err or out)
            GLib.idle_add(self.refresh_bt)
        self.bg(work)

    def _bt_error(self, msg):
        last = (msg or "failed").splitlines()[-1][:160]
        self.bt_status.set_text("[x] " + last)
        return False

    def bt_disconnect(self, d):
        self.bt_status.set_text("disconnecting %s..." % d["name"])

        def work():
            qrun(["bluetoothctl", "disconnect", d["mac"]], timeout=20)
            GLib.idle_add(self.refresh_bt)
        self.bg(work)

    def bt_forget(self, d):
        if not self.modal("Forget device",
                          "Remove %s from Bluetooth?" % d["name"],
                          ok_label="[x] Forget"):
            return

        def work():
            if d["connected"]:
                qrun(["bluetoothctl", "disconnect", d["mac"]], timeout=20)
            qrun(["bluetoothctl", "remove", d["mac"]], timeout=20)
            GLib.idle_add(self.refresh_bt)
        self.bg(work)

    # ---- modal dialog (DESIGN.md structure) -----------------------------
    def modal(self, title, prompt, entry=False, ok_label="[+] OK"):
        dlg = Gtk.Dialog(transient_for=self, modal=True)
        dlg.set_decorated(False)
        dlg.set_default_size(int(430 * self.scale), -1)
        dlg.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        area = dlg.get_content_area()
        area.set_spacing(int(10 * self.scale))
        for m in ("top", "bottom", "start", "end"):
            getattr(area, "set_margin_" + m)(int(12 * self.scale))

        cancel = Gtk.Button(label="[x] Cancel")
        cancel.get_style_context().add_class("close")
        cancel.connect("clicked", lambda *a: dlg.response(Gtk.ResponseType.CANCEL))
        area.pack_start(self.card_head("[+] " + title, [cancel]),
                        False, False, 0)

        lbl = Gtk.Label(label=prompt)
        lbl.get_style_context().add_class("label-sub")
        lbl.set_xalign(0)
        lbl.set_line_wrap(True)
        area.pack_start(lbl, False, False, 0)

        ent = None
        if entry:
            ent = Gtk.Entry()
            ent.set_visibility(False)
            ent.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            ent.set_placeholder_text("password")
            ent.connect("activate",
                        lambda *a: dlg.response(Gtk.ResponseType.OK))
            area.pack_start(ent, False, False, 0)

        ok = Gtk.Button(label=ok_label)
        ok.get_style_context().add_class("btn-danger")
        ok.connect("clicked", lambda *a: dlg.response(Gtk.ResponseType.OK))
        area.pack_start(ok, False, False, 0)

        dlg.show_all()
        resp = dlg.run()
        val = ent.get_text() if ent is not None else None
        dlg.destroy()
        if entry:
            return val if resp == Gtk.ResponseType.OK else None
        return resp == Gtk.ResponseType.OK

    # ---- sliders / audio ------------------------------------------------
    def on_vol(self, value):
        v = int(value)
        self.vol_val.set_text("%d%%" % v)
        if self.guard:
            return
        self.vol_pending = v
        if self.vol_to is None:
            self.vol_to = GLib.timeout_add(120, self._apply_vol)

    def _apply_vol(self):
        self.vol_to = None
        if self.vol_pending is not None:
            v = max(0, min(100, int(self.vol_pending)))
            run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                 "%.2f" % (v / 100.0)])
        return False

    def poll_volume(self):
        if self.guard or self.vol is None:
            return True
        if self.vol_to is None and not self.vol.dragging:
            v = int(read_volume())
            if abs(v - self.vol.value) >= 1:
                self.vol.set_value(v, notify=False)
                self.vol_val.set_text("%d%%" % v)
        return True

    def on_bri(self, value):
        v = int(value)
        self.bri_val.set_text("%d%%" % v)
        if self.guard:
            return
        self.bri_pending = v
        if self.bri_to is None:
            self.bri_to = GLib.timeout_add(120, self._apply_bri)

    def _apply_bri(self):
        self.bri_to = None
        if self.bri_pending is not None:
            raw = max(1, int(round(self.bri_pending * self.bri_max / 100.0)))
            try:
                with open(BACKLIGHT + "/brightness", "w") as f:
                    f.write(str(raw))
            except Exception:
                pass
        return False

    def _set_switch(self, sw, val):
        if sw.get_active() == val:
            return
        self._sync = True
        sw.set_active(val)
        self._sync = False

    def on_wifi(self, sw, _p):
        if self.guard or self._sync:
            return
        rc, _o, err = qrun(["nmcli", "radio", "wifi",
                            "on" if sw.get_active() else "off"], timeout=15)
        if rc != 0:
            plog("wifi radio rc=%s err=%r" % (rc, err))
        GLib.timeout_add(900, self.refresh_wifi)

    def on_bt(self, sw, _p):
        if self.guard or self._sync:
            return
        rc, _o, err = qrun(["bluetoothctl", "power",
                            "on" if sw.get_active() else "off"], timeout=15)
        if rc != 0:
            plog("bt power rc=%s err=%r" % (rc, err))
        GLib.timeout_add(900, self.refresh_bt)

    def on_sink(self, sink):
        if self._sink_guard or sink["default"]:
            return
        run(["wpctl", "set-default", str(sink["id"])])
        GLib.timeout_add(700, self._reload_volume)

    def _reload_volume(self):
        v = int(read_volume())
        self.vol.set_value(v, notify=False)
        self.vol_val.set_text("%d%%" % v)
        return False

    def refresh_streams(self):
        for sl in getattr(self, "app_sliders", []) or []:
            if getattr(sl, "dragging", False):
                return True
        self.streams = list_streams()
        self._clear(self.app_box)
        self.app_sliders = []
        if not self.streams:
            self.app_status.set_text("No apps playing audio")
            self.app_box.show_all()
            return True
        self.app_status.set_text("%d app%s" % (len(self.streams), "" if len(self.streams) == 1 else "s"))
        for s in self.streams:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                          spacing=int(4 * self.scale))
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                          spacing=int(6 * self.scale))
            lbl = Gtk.Label(label=s["app"])
            lbl.set_xalign(0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            top.pack_start(lbl, True, True, 0)
            val = Gtk.Label(label=("%d%%" % s["vol"]) if not s["mute"]
                            else "mute")
            add_classes(val, "label-sub", "accent")
            val.set_xalign(1)
            top.pack_end(val, False, False, 0)
            mute = Gtk.Button(label="Mute" if not s["mute"] else "Unmute")
            mute.get_style_context().add_class("btn-item")
            mute.get_style_context().add_class("btn-mini")
            if s["mute"]:
                add_classes(mute, "on")
            mute.connect("clicked",
                         lambda b, ss=s: self.toggle_stream_mute(ss))
            top.pack_end(mute, False, False, 0)
            row.pack_start(top, False, False, 0)
            sl = HSlider(0, 100, min(100, s["vol"]),
                         lambda v, ss=s: self.set_stream_vol(ss, v),
                         scale=self.scale * 0.85)
            sl.set_valign(Gtk.Align.CENTER)
            row.pack_start(sl, False, False, 0)
            self.app_sliders.append(sl)
            self.app_box.pack_start(row, False, False, 0)
        self.app_box.show_all()
        return True

    def set_stream_vol(self, s, value):
        v = max(0, min(100, int(value)))
        run(["pw-cli", "s", str(s["id"]), "Props",
             "{ volume: %.3f }" % (v / 100.0)])

    def toggle_stream_mute(self, s):
        run(["pw-cli", "s", str(s["id"]), "Props",
             "{ mute: %s }" % ("false" if s["mute"] else "true")])
        GLib.timeout_add(300, self.refresh_streams)

    def refresh_sinks(self):
        self._sink_guard = True
        try:
            self.sink_list = list_sinks()
            self._clear(self.sink_box)
            for s in self.sink_list:
                self.sink_box.pack_start(
                    self.item_row(s["name"], "active" if s["default"] else "",
                                  bool(s["default"]),
                                  lambda ss=s: self.on_sink(ss)),
                    False, False, 0)
            self.sink_box.show_all()
        finally:
            self._sink_guard = False
        return True

    # ---- wallpaper (carousel) -------------------------------------------
    def thumb_btn(self, path, side, dim=None):
        b = Gtk.Button()
        b.get_style_context().add_class("btn-thumb")
        if dim == "near":
            b.get_style_context().add_class("wall-near")
        elif dim == "far":
            b.get_style_context().add_class("wall-far")
        img = Gtk.Image()
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, side, side, True)
            img.set_from_pixbuf(pb)
        except Exception:
            img.set_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)
            img.set_pixel_size(side)
        b.add(img)
        b.set_tooltip_text(os.path.basename(path))
        b.connect("clicked", lambda *a: self.set_wallpaper(path))
        return b

    def _wall_avail_fallback(self):
        """Approximate the strip width before the first allocation."""
        pw = self.get_allocated_width() or 800
        s = self.scale
        inner = pw - int(round(9 * s)) * 2 - int(round(8 * s)) * 2
        btn = int(round(52 * s))
        return max(int(round(160 * s)), inner - 2 * (btn + int(round(6 * s))))

    def _wall_available(self):
        """Width the strip may use, derived from the window (stable)."""
        pw = self.get_allocated_width()
        # While rotating, the window allocation can briefly (or permanently,
        # until the minimum width shrinks) stay at the old landscape size.
        # Never let the carousel size itself from more than the monitor.
        mw, _mh = monitor_size()
        if mw > 50:
            pw = mw if pw <= 50 else min(pw, mw)
        if pw <= 50:
            return self._wall_avail_fallback()
        s = self.scale
        # root margins + card margins + the card's hairline border, plus a
        # small safety allowance so the window's minimum width never exceeds
        # the portrait screen (otherwise the right edge is clipped after a
        # rotation back from landscape).
        inner = (pw - 2 * int(round(9 * s)) - 2 * int(round(8 * s))
                 - 2 * int(round(1 * s)) - int(round(12 * s)))
        pw_btn = self.wall_prev.get_allocated_width() if self.wall_prev else 1
        nw_btn = self.wall_next.get_allocated_width() if self.wall_next else 1
        sp = self.wall_row.get_spacing() if self.wall_row else 0
        if pw_btn <= 1 or nw_btn <= 1:
            btn = int(round(56 * s))
            return max(1, inner - 2 * btn - 2 * sp)
        return max(1, inner - pw_btn - nw_btn - 2 * sp)

    def wall_slot_cap(self):
        """Hard limit on visible thumbnails: 7 portrait, 11 landscape."""
        # Monitor geometry follows rotation immediately; the window
        # allocation lags behind (and can stay at the old size), so it is
        # not a reliable orientation source.
        w, h = monitor_size()
        if w > 50 and h > 50:
            return 7 if h >= w else 11
        try:
            w = self.get_allocated_width()
            h = self.get_allocated_height()
            if w > 50 and h > 50:
                return 7 if h >= w else 11
        except Exception:
            pass
        return 7 if self.scale >= 1.1 else 11

    def on_monitor_geometry(self, *_a):
        """Rebuild the carousel for the new orientation after a rotation.

        The old carousel keeps a large minimum width alive, which can stop
        the fullscreen window from shrinking back to portrait.  Clear it
        first, then rebuild with the new (monitor-based) geometry.
        """
        if self._rot_pending:
            return
        self._rot_pending = True
        self.wall_avail = 0
        self._clear(self.wall_strip)
        GLib.idle_add(self._rotation_settle)

    def _rotation_settle(self):
        self._rot_pending = False
        if self.wall_pics:
            self._wall_busy = True
            try:
                self.refresh_wall()
            finally:
                self._wall_busy = False
        self.wall_strip.show_all()
        self.queue_resize()
        # The compositor only reconfigures the fullscreen surface when the
        # window itself asks for the new size; GTK keeps the old, wider size
        # even after the carousel minimum has shrunk.
        mw, mh = monitor_size()
        if mw > 50 and mh > 50 and (mw, mh) != self.get_size():
            # A plain resize() is ignored while fullscreen, so drop out and
            # back in to make the compositor configure the new size.
            self.unfullscreen()
            self.fullscreen()
        return False

    def on_wall_alloc(self, _w, alloc):
        """Rebuild the carousel when the available width changes."""
        if self._wall_busy or alloc.width <= 50:
            return
        avail = self._wall_available()
        if abs(avail - self.wall_avail) > 12:
            self.wall_avail = avail
            if self.wall_pics:
                self._wall_busy = True
                try:
                    self.refresh_wall()
                finally:
                    self._wall_busy = False

    def refresh_wall(self):
        self.wall_cur = current_wallpaper()
        pics = list_wallpapers()
        self.wall_pics = pics
        self._clear(self.wall_strip)
        self.wall_btns = {}
        if not pics:
            self.wall_status.set_text(
                "Put images in ~/wallpapers and tap Reload")
            self.wall_strip.show_all()
            return
        try:
            ci = pics.index(self.wall_cur)
        except ValueError:
            ci = 0
        n = len(pics)

        # ---- adaptive carousel ------------------------------------------
        # Use as many slots as fit in the row.  If there are more wallpapers
        # than slots they are scaled down until all of them fit; if there are
        # fewer, the list is looped so the row still looks full.
        avail = self._wall_available()
        self.wall_avail = avail
        gap = max(2, int(round(8 * self.scale)))
        big = max(28, int(round(132 * self.scale)))
        near = max(20, int(round(88 * self.scale)))
        far = max(16, int(round(66 * self.scale)))

        # A thumbnail's real width depends on the image aspect ratio (the
        # wallpapers are portrait) plus the button chrome (2px padding and a
        # 1px border on each side).
        aspects = []
        for p in pics:
            try:
                _fmt, iw, ih = GdkPixbuf.Pixbuf.get_file_info(p)
                aspects.append((iw / float(ih)) if ih else 1.0)
            except Exception:
                aspects.append(1.0)
        chrome = 6

        def size_of(off):
            d = abs(off)
            return big if d == 0 else (near if d == 1 else far)

        def image_width(k):
            start = -(k // 2)
            total = 0
            for off in range(start, start + k):
                idx = (ci + off) % n
                total += int(round(size_of(off) * aspects[idx]))
            return total

        def total_width(k):
            return image_width(k) + chrome * k + gap * (k - 1)

        # Orientation caps: 7 slots portrait, 11 landscape. Never show more
        # than what fits in the row; fewer images are looped to fill it.
        cap = self.wall_slot_cap()
        kmax = 1
        for k in range(1, cap + 1):
            if total_width(k) <= avail:
                kmax = k
            else:
                break
        slots = 1 if n == 1 else kmax

        # Stretch the tiles so the slots span the whole row instead of
        # leaving empty space on the left and right.  Only grow (never
        # shrink), keep a small safety margin, and stop at a sane maximum.
        fill = 1.0
        if slots > 1:
            margin = 2 * slots + int(round(4 * self.scale))
            room = (avail - chrome * slots - gap * (slots - 1) - margin)
            base_img = image_width(slots)
            if base_img > 0:
                fill = room / float(base_img)
            fill = max(1.0, min(fill, 2.6))
        big = max(16, int(round(big * fill)))
        near = max(12, int(round(near * fill)))
        far = max(10, int(round(far * fill)))

        self.wall_strip.set_spacing(gap)

        self.wall_status.set_text(
            "%d image%s \u00b7 %d/%d" % (n, "" if n == 1 else "s", ci + 1, n))

        start = -(slots // 2)
        for off in range(start, start + slots):
            idx = (ci + off) % n
            d = abs(off)
            side = big if d == 0 else (near if d == 1 else far)
            dim = None if d == 0 else ("near" if d == 1 else "far")
            b = self.thumb_btn(pics[idx], side, dim)
            if off == 0:
                b.get_style_context().add_class("on")
            self.wall_btns[pics[idx]] = b
            self.wall_strip.pack_start(b, False, False, 0)
        self.wall_strip.show_all()

    def wall_step(self, delta):
        if not self.wall_pics:
            return
        try:
            ci = self.wall_pics.index(self.wall_cur)
        except ValueError:
            ci = 0
        self.set_wallpaper(self.wall_pics[(ci + delta) % len(self.wall_pics)])

    def set_wallpaper(self, path):
        self.wall_cur = path
        try:
            os.makedirs(os.path.dirname(WALL_FILE), exist_ok=True)
            with open(WALL_FILE, "w") as f:
                f.write(path)
        except Exception as e:
            plog("wall save err %r" % e)
        self.refresh_wall()
        if self.wall_status:
            self.wall_status.set_text("applied: %s" % os.path.basename(path))
        cmd = ("pkill -x swaybg; sleep 0.2; exec setsid swaybg -i %s -m fill"
               % shlex.quote(path))
        try:
            subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as e:
            plog("swaybg err %r" % e)
        self._refresh_accent()

    def _refresh_accent(self):
        def work():
            run([os.path.join(HOME, ".local", "bin", "accent-update")],
                timeout=25)
            GLib.idle_add(self._accent_done)
        self.bg(work)

    def _accent_done(self):
        apply_css(self.scale)
        for s in (self.vol, self.bri):
            s.queue_draw()
        return False

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()


def main():
    import traceback

    def _hook(t, v, tb):
        plog("EXC " + "".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = _hook
    # GTK3 on Wayland derives app_id from the program name; set it before the
    # first window is created so waybar can find/kill this panel by app_id.
    GLib.set_prgname("org.swaytablet.controlpanel")
    try:
        Gdk.set_program_class("org.swaytablet.controlpanel")
    except Exception:
        pass
    plog("--- panel start pid=%s scale=%s accent=%s ---" %
         (os.getpid(), ui_scale(), load_accent()[0]))
    apply_css(ui_scale())
    win = Panel()
    win.show_all()
    win.fullscreen()
    Gtk.main()


if __name__ == "__main__":
    main()
