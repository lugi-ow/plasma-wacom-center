#!/usr/bin/env python3
# Dim-around overlay for tablet precision mode (Plasma 6 Wayland).
# Usage: tablet-overlay.py X Y W H [DIM]   (clear rectangle in px; DIM 0-1)
# Draws dim bands around a clear centre plus a thin inset border, on the
# compositor overlay layer, click-through. Killed by tablet-precision.sh.
import os
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

if len(sys.argv) not in (5, 6):
    sys.exit("usage: tablet-overlay.py X Y W H [DIM]")

app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
ctx = engine.rootContext()
for name, value in zip(("px", "py", "pw", "ph"), map(int, sys.argv[1:5])):
    ctx.setContextProperty(name, value)
ctx.setContextProperty("dimval", float(sys.argv[5]) if len(sys.argv) == 6 else 0.35)
qml = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tablet-overlay.qml")
engine.load(QUrl.fromLocalFile(qml))
if not engine.rootObjects():
    sys.exit(1)
sys.exit(app.exec())
