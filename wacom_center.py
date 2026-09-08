#!/usr/bin/env python3
# Wacom Center - one window for the drawing-tablet settings Plasma scatters.
# Part of plasma-wacom-center (MIT).
#
# Precision tab: area size (% of screen width, tablet-shaped), dim strength,
#   the hold time of the area drag and the long-press time that leaves the
#   mode (seconds, no floor), the ring step (points per tick), written to
#   ~/.config/tabprec.conf, which tablet-precision.sh sources on every toggle
#   and tablet-hover.py re-reads; the ring's tick angle and direction go into
#   its kcminputrc [TabletRing] binding.
# Pad buttons tab: the express keys' injected chords, read/written to
#   kcminputrc [ButtonRebinds] (the same mechanism the system page uses).
#   Letters/digits get a layout warning: injected letter chords die under
#   any non-Latin layout; F-keys and bare modifiers never do.
# The pad device and the tablet aspect ratio are detected from the
# compositor's device list - no hardcoded model names.
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QLocale, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QKeySequence
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

# ── chunk: paths
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabprec.conf"
TOGGLE = Path.home() / ".local/bin/tablet-precision.sh"
MODIFIER_ONLY = {"Shift", "Control", "Ctrl", "Alt", "Meta"}
RING_DEFAULT = ("Meta+Shift+F10", "Meta+Shift+F9", 600)   # bigger, smaller, KWin threshold = degrees x 120: every 5-degree step
KW, MGR, IF = "org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDevice"


# ── chunk: busget
def busget(path, prop):
    try:
        return subprocess.run(
            ["busctl", "--user", "get-property", KW, path,
             IF if path != MGR else "org.kde.KWin.InputDeviceManager", prop],
            capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ── chunk: detect_devices
def detect_devices():
    """Return (pad_device_name, tablet_aspect)."""
    pad_name, aspect = None, 1.6
    for sysname in busget(MGR, "devicesSysNames").replace('"', " ").split()[2:]:
        path = f"{MGR}/{sysname}"
        if pad_name is None and "true" in busget(path, "tabletPad"):
            out = busget(path, "name").split('"')
            if len(out) >= 2:
                pad_name = out[1]
        if "true" in busget(path, "tabletTool"):
            size = busget(path, "size").split()
            if len(size) >= 3 and float(size[2]) > 0:
                aspect = float(size[1]) / float(size[2])
    return pad_name, aspect


# ── chunk: read_conf
def read_conf():
    values = {"SCALE": 0.36, "DIM": 0.10, "HOLD": 0.15, "LONG": 0.7, "RING_STEP": 0.5}
    try:
        for line in CONF.read_text().splitlines():
            key, _, val = line.partition("=")
            if key.strip() in values:
                values[key.strip()] = float(val.strip())
    except (OSError, ValueError):
        pass
    return values


# ── chunk: write_conf
def write_conf(scale, dim, hold, long_press, ring_step):
    """Update SCALE, DIM, HOLD, LONG and RING_STEP in place; every other
    line (touch-preview keys, comments) stays."""
    try:
        rest = [l for l in CONF.read_text().splitlines()
                if l.split("=", 1)[0].strip() not in ("SCALE", "DIM", "HOLD", "LONG", "RING_STEP")]
    except OSError:
        rest = []
    CONF.write_text("\n".join([f"SCALE={scale:.4f}", f"DIM={dim:.2f}", f"HOLD={hold:.2f}",
                               f"LONG={long_press:.2f}", f"RING_STEP={ring_step:.1f}"] + rest) + "\n")


# ── chunk: kread
def kread(pad, idx):
    out = subprocess.run(
        ["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds",
         "--group", "Tablet", "--group", pad, "--key", str(idx)],
        capture_output=True, text=True).stdout.strip()
    return out.removeprefix("Key,") if out.startswith("Key,") else ""


# ── chunk: kwrite
def kwrite(pad, idx, seq):
    subprocess.run(
        ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group",
         "ButtonRebinds", "--group", "Tablet", "--group", pad,
         "--key", str(idx)] + (["--delete"] if not seq else [f"Key,{seq}"]),
        check=True)


# ── chunk: ring_read
def ring_read(pad):
    """(bigger chord, smaller chord, degrees per tick) of the ring binding, mode 1,
    in kcminputrc; the defaults when there is none. KWin stores degrees x 120."""
    if pad:
        out = subprocess.run(
            ["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds",
             "--group", "TabletRing", "--group", pad, "--group", "0", "--key", "0"],
            capture_output=True, text=True).stdout.strip().split(",")
        if len(out) == 4 and out[0] == "AxisKey":
            try:
                return out[1], out[2], int(out[3]) / 120
            except ValueError:
                pass
    return RING_DEFAULT[0], RING_DEFAULT[1], RING_DEFAULT[2] / 120


# ── chunk: ring_write
def ring_write(pad, up, down, degrees):
    """Bind the ring (mode 1): UP fires every DEGREES of travel one way, DOWN
    the other way. KWin compares its threshold with degrees x 120 and the
    ring reports 5-degree steps, so 5 is the finest tick."""
    if not pad:
        return
    subprocess.run(
        ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group", "ButtonRebinds",
         "--group", "TabletRing", "--group", pad, "--group", "0", "--key", "0",
         f"AxisKey,{up},{down},{max(1, round(degrees * 120))}"], check=True)
    subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"])


# ── chunk: PrecisionTab
class PrecisionTab(QWidget):
    def __init__(self, aspect, pad):
        super().__init__()
        self.aspect = aspect
        self.pad = pad
        conf = read_conf()
        screen = QGuiApplication.primaryScreen()
        self.sw = screen.size().width() if screen else 0
        self.sh = screen.size().height() if screen else 0
        if self.sw < 1 or self.sh < 1:      # no output (the monitor asleep): Qt hands out a 0x0 placeholder screen
            self.sw, self.sh = 1920, 1080   # a plausible desktop, so the labels still read; the conf keeps a fraction, never these pixels

        layout = QVBoxLayout(self)
        self.size_label = QLabel()
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(5, 80)
        self.size.setValue(round(conf["SCALE"] * 100))
        self.dim_label = QLabel()
        self.dim = QSlider(Qt.Orientation.Horizontal)
        self.dim.setRange(0, 80)
        self.dim.setValue(round(conf["DIM"] * 100))
        self.hold = self.seconds_field(conf["HOLD"])
        self.long_press = self.seconds_field(conf["LONG"])
        hold_row = QHBoxLayout()
        hold_row.addWidget(QLabel("Rest a finger on the precision key this long to start "
                                  "dragging the area (0 = at once):"))
        hold_row.addWidget(self.hold)
        hold_row.addStretch()
        long_row = QHBoxLayout()
        long_row.addWidget(QLabel("Keep it pressed this long after a move to leave precision "
                                  "mode (0 = never):"))
        long_row.addWidget(self.long_press)
        long_row.addStretch()
        self.ring_up, self.ring_down, degrees = ring_read(pad)
        self.ring_step = QDoubleSpinBox()
        self.ring_step.setRange(0.1, 50.0)
        self.ring_step.setSingleStep(0.5)
        self.ring_step.setDecimals(1)
        self.ring_step.setSuffix(" points of screen width")
        self.ring_step.setLocale(QLocale.c())
        self.ring_step.setKeyboardTracking(False)
        self.ring_step.setValue(conf["RING_STEP"])
        self.ring_degrees = QSpinBox()
        self.ring_degrees.setRange(1, 180)
        self.ring_degrees.setSuffix("° of ring travel")
        self.ring_degrees.setKeyboardTracking(False)
        self.ring_degrees.setValue(max(1, round(degrees)))
        self.ring_degrees.setToolTip("The ring reports 5° steps, so 5 is the finest tick; 1 to 5 behave the same.")
        self.ring_swap = QCheckBox("Swap the ring direction")
        ring_row = QHBoxLayout()
        ring_row.addWidget(QLabel("Ring: each tick changes the size by"))
        ring_row.addWidget(self.ring_step)
        ring_row.addStretch()
        tick_row = QHBoxLayout()
        tick_row.addWidget(QLabel("A tick every"))
        tick_row.addWidget(self.ring_degrees)
        tick_row.addWidget(self.ring_swap)
        tick_row.addStretch()
        toggle = QPushButton("Toggle precision now")
        toggle.clicked.connect(lambda: subprocess.Popen([str(TOGGLE)]))
        toggle.setToolTip("The pad button bound to Meta+Shift+F12 does the same. Size and dim apply "
                          "on the next toggle or ring tick, the times within two seconds, the ring "
                          "step at the next tick.")

        for w in (self.size_label, self.size, self.dim_label, self.dim):
            layout.addWidget(w)
        layout.addLayout(hold_row)
        layout.addLayout(long_row)
        layout.addLayout(ring_row)
        layout.addLayout(tick_row)
        layout.addWidget(toggle)
        layout.addStretch()
        for slider in (self.size, self.dim):
            slider.valueChanged.connect(self.update_labels)
            slider.sliderReleased.connect(self.save)
        self.hold.valueChanged.connect(self.save)
        self.long_press.valueChanged.connect(self.save)
        self.ring_step.valueChanged.connect(self.save)
        self.ring_degrees.valueChanged.connect(self.apply_ring)
        self.ring_swap.toggled.connect(self.apply_ring)
        self.update_labels()

    def apply_ring(self):
        """The tick angle and the direction go straight into the ring binding."""
        up, down = ((self.ring_down, self.ring_up) if self.ring_swap.isChecked()
                    else (self.ring_up, self.ring_down))
        ring_write(self.pad, up, down, self.ring_degrees.value())

    @staticmethod
    def seconds_field(value):
        """A time in seconds: 2 decimals, from 0 (no floor - the conf takes any value), dot decimal."""
        box = QDoubleSpinBox()
        box.setRange(0.0, 60.0)
        box.setSingleStep(0.05)
        box.setDecimals(2)
        box.setSuffix(" s")
        box.setLocale(QLocale.c())          # dot decimal like the conf file, whatever the desktop locale
        box.setKeyboardTracking(False)      # save on Enter, focus-out or a step, not per keystroke
        box.setValue(value)
        return box

    def update_labels(self):
        pct = self.size.value()
        w = round(self.sw * pct / 100)
        h = round(w / self.aspect)
        if h > self.sh:
            h = self.sh
            w = round(h * self.aspect)
        area_pct = round(100 * w * h / (self.sw * self.sh))
        self.size_label.setText(
            f"Precision area: {pct}% of screen width -> {w} x {h} px "
            f"(tablet-shaped, {area_pct}% of the screen)")
        self.dim_label.setText(f"Dim strength outside the area: {self.dim.value()}%")

    def save(self):
        write_conf(self.size.value() / 100, self.dim.value() / 100, self.hold.value(),
                   self.long_press.value(), self.ring_step.value())


# ── chunk: PadTab
class PadTab(QWidget):
    def __init__(self, pad):
        super().__init__()
        self.pad = pad
        layout = QGridLayout(self)
        if not pad:
            note = QLabel("No tablet pad detected. Wake the tablet and reopen "
                          "this window.")
            note.setWordWrap(True)
            layout.addWidget(note, 0, 0)
            return
        layout.addWidget(QLabel(f"Chord each express key of '{pad}' sends "
                                "(top to bottom). Blank = defer to application."),
                         0, 0, 1, 3)
        self.edits = {}
        for idx in range(8):
            layout.addWidget(QLabel(f"Key {idx + 1}"), idx + 1, 0)
            edit = QLineEdit(kread(pad, idx))
            edit.setPlaceholderText("e.g. Meta+Shift+F10, or Shift")
            self.edits[idx] = edit
            layout.addWidget(edit, idx + 1, 1)
        apply_btn = QPushButton("Apply bindings")
        apply_btn.clicked.connect(self.apply)
        layout.addWidget(apply_btn, 9, 1)
        note = QLabel("Letters and digits break while a non-Latin layout is "
                      "active (the injector maps through the current layout). "
                      "F-keys and bare modifiers always work.")
        note.setWordWrap(True)
        layout.addWidget(note, 10, 0, 1, 3)

    def apply(self):
        problems = []
        for idx, edit in self.edits.items():
            text = edit.text().strip()
            if text and text not in MODIFIER_ONLY and QKeySequence(text).isEmpty():
                problems.append(f"Key {idx + 1}: '{text}' is not a valid chord")
                continue
            kwrite(self.pad, idx, text)
        subprocess.run(["qdbus6", "org.kde.KWin", "/KWin",
                        "org.kde.KWin.reconfigure"])
        if problems:
            QMessageBox.warning(self, "Wacom Center", "\n".join(problems))


# ── chunk: main
def main():
    app = QApplication(sys.argv)
    app.setDesktopFileName("wacom-center")   # the Wayland app_id KWin reports; without it, the interpreter name
    app.setWindowIcon(QIcon.fromTheme("input-tablet"))
    pad, aspect = detect_devices()
    win = QWidget()
    win.setWindowTitle("Wacom Center")
    tabs = QTabWidget()
    tabs.addTab(PrecisionTab(aspect, pad), "Precision")
    tabs.addTab(PadTab(pad), "Pad buttons")
    if "pad" in sys.argv[1:]:                  # `wacom_center.py pad` opens on the Pad buttons tab (the README pictures)
        tabs.setCurrentIndex(1)
    links = QHBoxLayout()
    for label, cmd in (("Pie editor (Kando)", ["kando", "--settings"]),
                       ("System tablet page", ["systemsettings", "kcm_tablet"])):
        btn = QPushButton(label)
        btn.clicked.connect(lambda _, c=cmd: subprocess.Popen(c))
        links.addWidget(btn)
    layout = QVBoxLayout(win)
    layout.addWidget(tabs)
    layout.addLayout(links)
    win.resize(560, 480)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
