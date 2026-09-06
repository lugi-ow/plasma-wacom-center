#!/usr/bin/env python3
# Dim-around overlay for tablet precision mode (Plasma 6 Wayland).
# Usage: tablet-overlay.py X Y W H [DIM [LABEL]] [--follow]
# Draws dim bands around a clear centre plus a thin inset border, on the
# compositor overlay layer, click-through. Killed by tablet-precision.sh.
# With LABEL the clear rectangle is tinted and captioned - the "ghost" that
# tablet-hover.py shows while a finger rests on the precision key.
# --follow: read "X Y W H" lines from stdin and move the rectangle live (the
# ghost follows the pen). The overlay quits by itself when stdin closes.
import os
import sys

from PyQt6.QtCore import QSocketNotifier, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

follow = "--follow" in sys.argv
args = [a for a in sys.argv[1:] if a != "--follow"]
if len(args) not in (4, 5, 6):
    sys.exit("usage: tablet-overlay.py X Y W H [DIM [LABEL]] [--follow]")

app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
NAMES = ("px", "py", "pw", "ph")
for name, value in zip(NAMES, map(int, args[:4])):
    ctx.setContextProperty(name, value)
ctx.setContextProperty("dimval", float(args[4]) if len(args) >= 5 else 0.35)
ctx.setContextProperty("label", args[5] if len(args) == 6 else "")
qml = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tablet-overlay.qml")
engine.load(QUrl.fromLocalFile(qml))
if not engine.rootObjects():
    sys.exit(1)

if follow:
    os.set_blocking(0, False)
    pending = b""

    def on_stdin():
        global pending
        try:
            chunk = os.read(0, 4096)
        except BlockingIOError:
            return
        if not chunk:                      # writer gone: the ghost goes with it
            app.quit()
            return
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in reversed(lines):       # newest complete line wins
            parts = line.split()
            if len(parts) != 4:
                continue
            try:
                values = list(map(int, parts))
            except ValueError:
                continue
            for name, value in zip(NAMES, values):
                ctx.setContextProperty(name, value)
            break

    notifier = QSocketNotifier(0, QSocketNotifier.Type.Read)
    notifier.activated.connect(on_stdin)

sys.exit(app.exec())
