#!/usr/bin/env python3
# Wacom Center - one window for the drawing-tablet settings Plasma scatters.
# Part of plasma-wacom-center (MIT).
#
# Precision tab: area size (% of screen width, tablet-shaped) and dim
#   strength, written to ~/.config/tabprec.conf, which tablet-precision.sh
#   sources on every toggle.
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

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QKeySequence
from PyQt6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSlider,
                             QTabWidget, QVBoxLayout, QWidget)

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabprec.conf"
TOGGLE = Path.home() / ".local/bin/tablet-precision.sh"
MODIFIER_ONLY = {"Shift", "Control", "Ctrl", "Alt", "Meta"}
KW, MGR, IF = "org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDevice"


def busget(path, prop):
    try:
        return subprocess.run(
            ["busctl", "--user", "get-property", KW, path,
             IF if path != MGR else "org.kde.KWin.InputDeviceManager", prop],
            capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


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


def read_conf():
    values = {"SCALE": 0.7071, "DIM": 0.35}
    try:
        for line in CONF.read_text().splitlines():
            key, _, val = line.partition("=")
            if key.strip() in values:
                values[key.strip()] = float(val.strip())
    except (OSError, ValueError):
        pass
    return values


def write_conf(scale, dim):
    CONF.write_text(f"SCALE={scale:.4f}\nDIM={dim:.2f}\n")


def kread(pad, idx):
    out = subprocess.run(
        ["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds",
         "--group", "Tablet", "--group", pad, "--key", str(idx)],
        capture_output=True, text=True).stdout.strip()
    return out.removeprefix("Key,") if out.startswith("Key,") else ""


def kwrite(pad, idx, seq):
    subprocess.run(
        ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group",
         "ButtonRebinds", "--group", "Tablet", "--group", pad,
         "--key", str(idx)] + (["--delete"] if not seq else [f"Key,{seq}"]),
        check=True)


class PrecisionTab(QWidget):
    def __init__(self, aspect):
        super().__init__()
        self.aspect = aspect
        conf = read_conf()
        screen = QGuiApplication.primaryScreen().size()
        self.sw, self.sh = screen.width(), screen.height()

        layout = QVBoxLayout(self)
        self.size_label = QLabel()
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(5, 80)
        self.size.setValue(round(conf["SCALE"] * 100))
        self.dim_label = QLabel()
        self.dim = QSlider(Qt.Orientation.Horizontal)
        self.dim.setRange(0, 80)
        self.dim.setValue(round(conf["DIM"] * 100))
        toggle = QPushButton("Toggle precision now")
        toggle.clicked.connect(lambda: subprocess.Popen([str(TOGGLE)]))
        hint = QLabel("Wacom-style placement: the cursor stays put on toggle, "
                      "the area keeps the tablet's own proportions (no stretch "
                      "inside it) and never leaves the screen. Changes apply on "
                      "the next toggle or ring tick.")
        hint.setWordWrap(True)

        for w in (self.size_label, self.size, self.dim_label, self.dim, toggle, hint):
            layout.addWidget(w)
        layout.addStretch()
        for slider in (self.size, self.dim):
            slider.valueChanged.connect(self.update_labels)
            slider.sliderReleased.connect(self.save)
        self.update_labels()

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
        write_conf(self.size.value() / 100, self.dim.value() / 100)


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


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon.fromTheme("input-tablet"))
    pad, aspect = detect_devices()
    win = QWidget()
    win.setWindowTitle("Wacom Center")
    tabs = QTabWidget()
    tabs.addTab(PrecisionTab(aspect), "Precision")
    tabs.addTab(PadTab(pad), "Pad buttons")
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
