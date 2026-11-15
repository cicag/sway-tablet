"""Shared helpers for sway-tablet Python tools.

Deployed next to the scripts by install.sh so each helper imports from the
same directory (sys.path[0] when run as python3 <dir>/script.py).
"""
import json
import os
import subprocess

HOME = os.path.expanduser("~")
ACCENT_FILE = os.path.join(HOME, ".config", "sway", "accent")
ACCENT_DEF = "#8c272e"
ONACC_DEF = "#f5f5f5"


def load_accent(accent_file=ACCENT_FILE, accent_def=None, onacc_def=None):
    """Read (accent, foreground) from the sway accent file.

    Falls back to the given defaults (or the module defaults) when the file
    is missing or unparsable.
    """
    accent_def = ACCENT_DEF if accent_def is None else accent_def
    onacc_def = ONACC_DEF if onacc_def is None else onacc_def
    try:
        t = open(accent_file).read().split()
    except OSError:
        return accent_def, onacc_def
    return (t[0] if t else accent_def,
            t[1] if len(t) > 1 else onacc_def)


def hex_to_rgba(c, a):
    """Convert '#rrggbb' to 'rgba(r, g, b, a)'."""
    c = (c or "#000000").lstrip("#")
    try:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return "rgba(%d, %d, %d, %s)" % (r, g, b, a)
    except Exception:
        return "rgba(140, 39, 46, %s)" % a


def run(cmd, timeout=12):
    """Run a command, return its stripped stdout (or '' on failure)."""
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=timeout,
                             env=dict(os.environ, NO_COLOR="1"))
        return out.stdout.decode(errors="replace").strip()
    except Exception:
        return ""


def qrun(cmd, timeout=12):
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout, env=dict(os.environ, NO_COLOR="1"))
        return (p.returncode,
                p.stdout.decode(errors="replace").strip(),
                p.stderr.decode(errors="replace").strip())
    except Exception as e:
        return -1, "", str(e)


def sway_first_output():
    """(name, transform) of the first non-headless sway output, else ('', '')."""
    try:
        data = json.loads(run(["swaymsg", "-t", "get_outputs"]))
    except Exception:
        return "", ""
    for o in data:
        if not o.get("headless") and o.get("name"):
            return o["name"], o.get("transform", "normal")
    return "", ""
