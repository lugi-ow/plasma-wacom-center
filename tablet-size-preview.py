#!/usr/bin/env python3
# Centred fading preview of the precision area size (Plasma 6 Wayland).
# Part of plasma-wacom-center (MIT).
#
# Spawned by tablet-precision-size.sh on the first ring tick; watches
# ~/.config/tabprec.conf, refreshes on every change, fades out ~1.2 s after
# the last change and exits. Click-through overlay, same layer-shell pattern
# as tablet-overlay.py. Tablet aspect ratio is read from the compositor.
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabprec.conf"
HOLD_MS = 1200
FADE_MS = 450


def tablet_aspect():
    """Width/height of the pen tablet from KWin's device list; 1.6 fallback."""
    kw, mgr, iface = "org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDevice"
    try:
        out = subprocess.run(
            ["busctl", "--user", "get-property", kw, mgr,
             "org.kde.KWin.InputDeviceManager", "devicesSysNames"],
            capture_output=True, text=True, timeout=3).stdout
        for sysname in out.replace('"', " ").split()[2:]:
            tool = subprocess.run(
                ["busctl", "--user", "get-property", kw, f"{mgr}/{sysname}",
                 iface, "tabletTool"], capture_output=True, text=True, timeout=3).stdout
            if "true" not in tool:
                continue
            size = subprocess.run(
                ["busctl", "--user", "get-property", kw, f"{mgr}/{sysname}",
                 iface, "size"], capture_output=True, text=True, timeout=3).stdout.split()
            if len(size) >= 3 and float(size[2]) > 0:
                return float(size[1]) / float(size[2])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return 1.6


def read_scale():
    try:
        for line in CONF.read_text().splitlines():
            if line.startswith("SCALE="):
                return max(0.05, min(0.80, float(line.split("=", 1)[1])))
    except (OSError, ValueError):
        pass
    return 0.7071


app = QGuiApplication(sys.argv)
screen = app.primaryScreen().size()
ASPECT = tablet_aspect()
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tablet-size-preview.qml")))
if not engine.rootObjects():
    sys.exit(1)
root = engine.rootObjects()[0]

last_mtime = 0.0


def apply_scale():
    scale = read_scale()
    w = round(screen.width() * scale)
    h = round(w / ASPECT)
    if h > screen.height():
        h = screen.height()
        w = round(h * ASPECT)
    root.setProperty("pw", w)
    root.setProperty("ph", h)
    root.setProperty("pct", round(scale * 100))
    root.setProperty("shown", True)


def tick():
    global last_mtime
    try:
        mtime = CONF.stat().st_mtime
    except OSError:
        mtime = last_mtime
    if mtime != last_mtime:
        last_mtime = mtime
        quit_timer.stop()  # a tick mid-fade cancels the pending exit
        apply_scale()
        hold.start(HOLD_MS)


def start_fade():
    root.setProperty("shown", False)
    quit_timer.start(FADE_MS + 200)


quit_timer = QTimer()
quit_timer.setSingleShot(True)
quit_timer.timeout.connect(lambda: app.quit())
hold = QTimer()
hold.setSingleShot(True)
hold.timeout.connect(start_fade)
poll = QTimer()
poll.timeout.connect(tick)
poll.start(100)

try:
    last_mtime = CONF.stat().st_mtime
except OSError:
    pass
apply_scale()
hold.start(HOLD_MS)
sys.exit(app.exec())
