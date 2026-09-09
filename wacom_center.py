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
# Pad buttons tab: the pad as a table - each key pictured as printed on the
#   pad (the dot and dash marks), a Touch and a Press box per key, the
#   ring's four modes between keys 4 and 5, the Pie keys column and the
#   Precision column (one tick at most). A ticked pie key is Disabled in
#   kcminputrc plus CHORD_<n> in the conf (amber waiting outline); the
#   Precision key gets the toggle's global shortcut and HOVER_MASK, its
#   fields consumed (red outline). The delay row is conf HOLD. Every Apply
#   and delay change pokes the daemon's control pipe - no polling.
#   Explanations live in the column tooltips (STE), not the window.
# The pad device and the tablet aspect ratio are detected from the
# compositor's device list - no hardcoded model names.
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QLocale, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPalette,
                         QPen, QPixmap)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSlider,
                             QSpinBox, QTabWidget, QVBoxLayout, QWidget)

# ── chunk: paths
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabprec.conf"
TOGGLE = Path.home() / ".local/bin/tablet-precision.sh"
MODIFIER_ONLY = {"Shift", "Control", "Ctrl", "Alt", "Meta"}
RING_DEFAULT = ("Meta+Shift+F10", "Meta+Shift+F9", 600)   # bigger, smaller, KWin threshold = degrees x 120: every 5-degree step
KW, MGR, IF = "org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDevice"
AMBER = "#e6a817"                        # the overlay border's amber: the waiting look
RED = "#da4453"                          # Breeze negative: a row consumed by precision mode
TOGGLE_COMPONENT = "net.local.tabprec-toggle.desktop"        # kglobalshortcutsrc group of the toggle
TOGGLE_FALLBACK = "Meta+Shift+F12"
CTL = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tabprec" / "hover.ctl"
PIE_TIP = ("A pie key opens a Kando menu at the pen.\n"
           "1. In Kando, give the menu a shortcut.\n"
           "2. Type the same shortcut here, in Touch or in Press.\n"
           "3. Tick the matching side: left box = Touch, right = Press.\n"
           "4. Click Apply bindings.\n"
           "The toolkit moves the mouse to the pen, then presses the\n"
           "shortcut, so the menu opens at the pen. A touch pie opens on\n"
           "the rest; lift the finger on a slice to select it.\n"
           "A pie shortcut is F-keys plus modifiers; use each once.")
TP_TIP = ("Pie on the touch: the Touch shortcut opens a Kando menu.\n"
          "A full chord (modifiers plus one F-key). The key's raw\n"
          "press is swallowed.")
PP_TIP = ("Pie on the press: the Press shortcut opens a Kando menu.\n"
          "Stored as Disabled in kcminputrc plus CHORD in the conf.")
REG_TIP = ("Seconds a finger must rest on THIS key before its touch\n"
           "action starts - the touch chord, or the precision key's\n"
           "area drag. 0 = at once.")
SHORTCUT_TIP = ("The shortcut a pad key presses.\n"
                "An empty box gives the raw key to the focused program.\n"
                "Letters and digits fail when a non-Latin layout is active.\n"
                "F-keys and modifiers always work.")
TOUCH_TIP = ("A touch chord is held while a finger RESTS on the key.\n"
             "It engages after the key's Touch register and releases at\n"
             "the lift. Bare modifiers are allowed - Ctrl for Blender's\n"
             "sculpt - but not Meta alone (that is the launcher tap).\n"
             "A press within the register wins: no chord for that contact.\n"
             "Needs Wacom keys with a touch sensor (Intuos Pro and kin).")
RING_TIP = ("The shortcut for one turn direction.\n"
            "The mode with the two precision-size shortcuts controls the area size.\n"
            "The Precision tab sets that mode's tick angle and direction.")
PAD_TIP = ("The keys as printed on the tablet, top to bottom.\n"
           "On a tablet rotated 180 degrees the keys sit on the right\n"
           "and this table reads bottom-up; the key numbers do not move.")
PRM_TIP = ("One key toggles precision mode.\n"
           "Tick it: Apply gives the key the toggle shortcut, the ghost\n"
           "and the area drag. Red outlines = fields the mode consumes.\n"
           "Moving the tick moves all of it. No tick = no ghost, no drag;\n"
           "also clear the Press box to take the toggle off the pad.")


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
def write_conf(scale, dim, long_press, ring_step):
    """Update SCALE, DIM, LONG and RING_STEP in place; every other line
    (HOLD - the Pad tab's delay row - chords, comments) stays."""
    try:
        rest = [l for l in CONF.read_text().splitlines()
                if l.split("=", 1)[0].strip() not in ("SCALE", "DIM", "LONG", "RING_STEP")]
    except OSError:
        rest = []
    CONF.write_text("\n".join([f"SCALE={scale:.4f}", f"DIM={dim:.2f}",
                               f"LONG={long_press:.2f}", f"RING_STEP={ring_step:.1f}"] + rest) + "\n")


# ── chunk: save_conf_key
def save_conf_key(key, value):
    """Set key=value in tabprec.conf and keep every other line (the same
    surgery tablet-hover.py does; the daemon re-reads within 2 s)."""
    try:
        lines = CONF.read_text().splitlines()
    except OSError:
        lines = []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{key}={value}")
    CONF.write_text("\n".join(out) + "\n")


# ── chunk: drop_conf_key
def drop_conf_key(key):
    """Remove key from tabprec.conf, keeping every other line."""
    try:
        lines = CONF.read_text().splitlines()
    except OSError:
        return
    out = [line for line in lines if line.split("=", 1)[0].strip() != key]
    if len(out) != len(lines):
        CONF.write_text("\n".join(out) + ("\n" if out else ""))


# ── chunk: conf_value
def conf_value(key):
    """One raw conf value (comments stripped), or '' when the key is absent."""
    try:
        for line in CONF.read_text().splitlines():
            k, _, val = line.partition("=")
            if k.strip() == key:
                return val.split("#", 1)[0].strip()
    except OSError:
        pass
    return ""


# ── chunk: poke_daemon
def poke_daemon():
    """One line into the daemon's control pipe: re-read the conf now. No
    daemon or no pipe yet = nothing to do (it reads the conf at start)."""
    try:
        fd = os.open(CTL, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return
    try:
        os.write(fd, b"reload\n")
    except OSError:
        pass
    os.close(fd)


# ── chunk: toggle_chord
def toggle_chord():
    """The precision toggle's global shortcut from kglobalshortcutsrc - what
    the Precision column writes onto the ticked key; the documented default
    when the entry is missing."""
    out = subprocess.run(
        ["kreadconfig6", "--file", "kglobalshortcutsrc", "--group", TOGGLE_COMPONENT,
         "--key", "_launch"], capture_output=True, text=True).stdout.strip()
    seq = out.split(",", 1)[0].strip()
    return seq if seq and seq.lower() != "none" else TOGGLE_FALLBACK


# ── chunk: chord_rules
def chord_rules():
    """parse_chord from tablet-pointer-warp.py beside this file - the daemon's
    own chord alphabet, so the Pad tab refuses what the daemon would refuse.
    None when the import fails: the pie validation is skipped then."""
    try:
        spec = importlib.util.spec_from_file_location(
            "tablet_pointer_warp", Path(__file__).resolve().parent / "tablet-pointer-warp.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.parse_chord
    except Exception:                    # noqa: BLE001 - any import trouble = no validation, the tab still works
        return None


# ── chunk: kread
def kread(pad, idx):
    out = subprocess.run(
        ["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds",
         "--group", "Tablet", "--group", pad, "--key", str(idx)],
        capture_output=True, text=True).stdout.strip()
    if out == "Disabled":
        return "Disabled"
    return out.removeprefix("Key,") if out.startswith("Key,") else ""


# ── chunk: kwrite
def kwrite(pad, idx, seq):
    """A chord, the literal Disabled (KWin swallows the key - what a
    CHORD_<n> key needs: a DELETED entry falls through to the focused
    app), or empty = delete."""
    value = (["--delete"] if not seq else
             ["Disabled"] if seq.lower() == "disabled" else [f"Key,{seq}"])
    subprocess.run(
        ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group",
         "ButtonRebinds", "--group", "Tablet", "--group", pad,
         "--key", str(idx)] + value,
        check=True)


# ── chunk: ring_read
def ring_read(pad, mode=0):
    """(bigger chord, smaller chord, degrees per tick) of one ring mode's
    binding in kcminputrc (KWin groups 0-3), or None when that mode is
    unbound. KWin stores degrees x 120."""
    if pad:
        out = subprocess.run(
            ["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds",
             "--group", "TabletRing", "--group", pad, "--group", str(mode), "--key", "0"],
            capture_output=True, text=True).stdout.strip().split(",")
        if len(out) == 4 and out[0] == "AxisKey":
            try:
                return out[1], out[2], int(out[3]) / 120
            except ValueError:
                pass
    return None


# ── chunk: ring_write
def ring_write(pad, up, down, degrees, mode=0):
    """Bind one ring mode: UP fires every DEGREES of travel one way, DOWN the
    other way. Both chords empty = the mode unbound. KWin compares its
    threshold with degrees x 120 and the ring reports 5-degree steps, so 5
    is the finest tick."""
    if not pad:
        return
    if not up and not down:
        subprocess.run(
            ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group", "ButtonRebinds",
             "--group", "TabletRing", "--group", pad, "--group", str(mode), "--key", "0",
             "--delete"], check=True)
    else:
        subprocess.run(
            ["kwriteconfig6", "--notify", "--file", "kcminputrc", "--group", "ButtonRebinds",
             "--group", "TabletRing", "--group", pad, "--group", str(mode), "--key", "0",
             f"AxisKey,{up},{down},{max(1, round(degrees * 120))}"], check=True)
    subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"])


# ── chunk: precision_ring_mode
def precision_ring_mode(pad):
    """(mode, binding) of the ring mode that carries the two precision-size
    shortcuts, wherever the Pad tab moved them; (0, the defaults) when no
    mode has the pair. The Precision tab's angle and direction go there."""
    pair = {RING_DEFAULT[0], RING_DEFAULT[1]}
    for mode in range(4):
        bound = ring_read(pad, mode)
        if bound and {bound[0], bound[1]} == pair:
            return mode, bound
    return 0, (RING_DEFAULT[0], RING_DEFAULT[1], RING_DEFAULT[2] / 120)


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
        self.long_press = self.seconds_field(conf["LONG"])
        long_row = QHBoxLayout()
        long_row.addWidget(QLabel("Keep it pressed this long after a move to leave precision "
                                  "mode (0 = never):"))
        long_row.addWidget(self.long_press)
        long_row.addStretch()
        self.ring_mode, (self.ring_up, self.ring_down, degrees) = precision_ring_mode(pad)
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
        layout.addLayout(long_row)
        layout.addLayout(ring_row)
        layout.addLayout(tick_row)
        layout.addWidget(toggle)
        layout.addStretch()
        for slider in (self.size, self.dim):
            slider.valueChanged.connect(self.update_labels)
            slider.sliderReleased.connect(self.save)
        self.long_press.valueChanged.connect(self.save)
        self.ring_step.valueChanged.connect(self.save)
        self.ring_degrees.valueChanged.connect(self.apply_ring)
        self.ring_swap.toggled.connect(self.apply_ring)
        self.update_labels()

    def apply_ring(self):
        """The tick angle and the direction go straight into the ring binding,
        on whichever mode carries the precision-size pair."""
        up, down = ((self.ring_down, self.ring_up) if self.ring_swap.isChecked()
                    else (self.ring_up, self.ring_down))
        ring_write(self.pad, up, down, self.ring_degrees.value(), self.ring_mode)

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
        write_conf(self.size.value() / 100, self.dim.value() / 100,
                   self.long_press.value(), self.ring_step.value())
        poke_daemon()                       # LONG matters to the daemon; it hears at once


# ── chunk: pad_icon
def pad_icon(kind):
    """A 20 px key picture as printed on the pad: a box, plain or with the
    tactile dot or dash mark. Palette colors, so dark themes stay legible."""
    pal = QApplication.palette()
    ink, paper = pal.color(QPalette.ColorRole.Text), pal.color(QPalette.ColorRole.Base)
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(ink, 1.5))
    p.setBrush(paper)
    p.drawRoundedRect(QRectF(2, 4, 16, 12), 2, 2)
    if kind == "dot":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QPointF(10, 10), 2.4, 2.4)
    elif kind == "dash":
        p.setPen(QPen(ink, 2))
        p.drawLine(QPointF(7, 10), QPointF(13, 10))
    p.end()
    return pm


# ── chunk: ring_icon
def ring_icon(mode):
    """The pad ring as a 22 px doughnut with mode n's light lit: mode 1 sits
    at 7:30 on the clock face, the next modes continue clockwise."""
    pal = QApplication.palette()
    ink, paper = pal.color(QPalette.ColorRole.Text), pal.color(QPalette.ColorRole.Base)
    pm = QPixmap(22, 22)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(ink, 1.5))
    p.setBrush(paper)
    p.drawEllipse(QPointF(11, 11), 8, 8)
    p.drawEllipse(QPointF(11, 11), 3.4, 3.4)
    dx, dy = {1: (-1, 1), 2: (-1, -1), 3: (1, -1), 4: (1, 1)}[mode]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(AMBER))
    p.drawEllipse(QPointF(11 + dx * 4.07, 11 + dy * 4.07), 2, 2)
    p.end()
    return pm


# ── chunk: draw_ants
def draw_ants(widget, color, offset):
    """The flowing dashed outline - the overlay's waiting border in
    miniature - painted over a widget: amber marks a pie key's box, red a
    field consumed by precision mode. Shared by the two Ants widgets."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 2)
    pen.setStyle(Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([3, 3])
    pen.setDashOffset(offset)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(widget.rect()).adjusted(1, 1, -1, -1), 4, 4)
    p.end()


# ── chunk: AntsLineEdit
class AntsLineEdit(QLineEdit):
    """A shortcut box that can wear the waiting look: dashes flowing
    clockwise, amber for a pie key, red when precision mode consumes it."""

    def __init__(self):
        super().__init__()
        self._offset = 0.0
        self._color = AMBER
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)

    def set_ants(self, on, color=None):
        if color:
            self._color = color
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _advance(self):
        self._offset -= 0.4              # a shrinking offset flows the dashes forward (the overlay's trick)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._timer.isActive():
            draw_ants(self, self._color, self._offset)


# ── chunk: AntsCheckBox
class AntsCheckBox(QCheckBox):
    """A checkbox wearing the same flowing outline: red when its row is
    consumed by precision mode."""

    def __init__(self):
        super().__init__()
        self._offset = 0.0
        self._color = RED
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)

    def set_ants(self, on, color=None):
        if color:
            self._color = color
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _advance(self):
        self._offset -= 0.4
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._timer.isActive():
            draw_ants(self, self._color, self._offset)


# ── chunk: AntsRadio
class AntsRadio(QRadioButton):
    """The Precision column's round tick (one option at most), wearing the
    red outline while its row is the precision key. Exclusivity and
    click-again-to-clear live in PadTab, so no key at all is a valid
    state - autoExclusive is off."""

    def __init__(self):
        super().__init__()
        self.setAutoExclusive(False)
        self._offset = 0.0
        self._color = RED
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)

    def set_ants(self, on, color=None):
        if color:
            self._color = color
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _advance(self):
        self._offset -= 0.4
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._timer.isActive():
            draw_ants(self, self._color, self._offset)


# ── chunk: PadTab
class PadTab(QWidget):
    """The pad as a table: the keys pictured as printed on the pad, a Touch
    and a Press box per key, the per-key Touch register, the ring's four
    modes between keys 4 and 5, the Pie keys column (a tick per side) and
    the Precision column (a round tick, one at most). A ticked pie side is
    Disabled in kcminputrc + its conf chord (amber outline); the Precision
    key gets the toggle chord + HOVER_MASK, its chord fields consumed (red
    outline, read-only Press). Apply and a register change poke the
    daemon's control pipe."""
    MARKS = ("plain", "dash", "dot", "plain", "plain", "dot", "dash", "plain")

    def __init__(self, pad):
        super().__init__()
        self.pad = pad
        self.parse = chord_rules()
        self._prm_last = None
        grid = QGridLayout(self)
        if not pad:
            note = QLabel("No tablet pad detected. Wake the tablet and reopen "
                          "this window.")
            note.setWordWrap(True)
            grid.addWidget(note, 0, 0)
            return
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)
        for col, span, text, tip in ((0, 1, "| Pad keys |", PAD_TIP),
                                     (1, 2, "| Shortcuts |", SHORTCUT_TIP),
                                     (3, 1, "| Touch register |", REG_TIP),
                                     (4, 1, "| Pie keys |", PIE_TIP),
                                     (5, 1, "| Precision |", PRM_TIP)):
            head = QLabel(text)
            head.setToolTip(tip)
            grid.addWidget(head, 0, col, 1, span, Qt.AlignmentFlag.AlignHCenter)
        side = QLabel("(on the left side)")
        side.setToolTip(PAD_TIP)
        grid.addWidget(side, 1, 0, Qt.AlignmentFlag.AlignHCenter)
        for col, text, tip in ((1, "Touch", TOUCH_TIP), (2, "Press", SHORTCUT_TIP)):
            sub = QLabel(text)
            sub.setToolTip(tip)
            grid.addWidget(sub, 1, col, Qt.AlignmentFlag.AlignHCenter)
        info = QLabel()
        theme = QIcon.fromTheme("dialog-information")
        if theme.isNull():
            info.setText("(i)")
        else:
            info.setPixmap(theme.pixmap(16, 16))
        info.setToolTip(PIE_TIP)
        grid.addWidget(info, 1, 4, Qt.AlignmentFlag.AlignHCenter)
        self.touches, self.presses, self.regs = {}, {}, {}
        self.tp, self.pp, self.prms, self.rings = {}, {}, {}, {}
        hold_default = read_conf()["HOLD"]
        for idx in range(8):
            row = idx + 2 if idx < 4 else idx + 6    # the ring sits between keys 4 and 5, as on the pad
            picture = QLabel()
            picture.setPixmap(pad_icon(self.MARKS[idx]))
            picture.setToolTip(f"Key {idx + 1}")
            grid.addWidget(picture, row, 0, Qt.AlignmentFlag.AlignCenter)
            touch = AntsLineEdit()
            touch.setPlaceholderText("Ctrl, or Alt+F5")
            touch.setToolTip(TOUCH_TIP)
            touch.setText(conf_value(f"TOUCH_CHORD_{idx + 1}"))
            press = AntsLineEdit()
            press.setPlaceholderText("Meta+Shift+F10, or Shift")
            try:
                reg_value = float(conf_value(f"TOUCH_HOLD_{idx + 1}"))
            except ValueError:
                reg_value = hold_default
            reg = PrecisionTab.seconds_field(reg_value)
            reg.setToolTip(REG_TIP)
            reg.valueChanged.connect(lambda v, n=idx + 1: self.save_register(n, v))
            tp = AntsCheckBox()
            tp.setToolTip(TP_TIP)
            pp = AntsCheckBox()
            pp.setToolTip(PP_TIP)
            prm = AntsRadio()
            prm.setToolTip(PRM_TIP)
            bound, chord = kread(pad, idx), conf_value(f"CHORD_{idx + 1}")
            if chord and bound in ("Disabled", "", chord):
                press.setText(chord)
                pp.setChecked(True)
            else:
                press.setText(bound)
            if bound == "Disabled" and touch.text() and self.parse \
                    and self.parse(touch.text(), True) is not None:
                tp.setChecked(True)                  # a touch pie: Disabled + a full touch chord
            tp.toggled.connect(self.restyle)
            pp.toggled.connect(self.restyle)
            prm.clicked.connect(lambda _, i=idx: self.pick_prm(i))
            self.touches[idx], self.presses[idx], self.regs[idx] = touch, press, reg
            self.tp[idx], self.pp[idx], self.prms[idx] = tp, pp, prm
            grid.addWidget(touch, row, 1)
            grid.addWidget(press, row, 2)
            grid.addWidget(reg, row, 3)
            pies = QWidget()
            pair = QHBoxLayout(pies)
            pair.setContentsMargins(0, 0, 0, 0)
            pair.addWidget(tp)
            pair.addWidget(pp)
            grid.addWidget(pies, row, 4, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(prm, row, 5, Qt.AlignmentFlag.AlignCenter)
        try:
            mask = int(conf_value("HOVER_MASK"), 0)
        except (TypeError, ValueError):
            mask = 0
        for idx in range(8):
            if mask & (1 << idx):
                self.prms[idx].setChecked(True)
                self._prm_last = idx
                break
        for mode in range(4):
            picture = QLabel()
            picture.setPixmap(ring_icon(mode + 1))
            picture.setToolTip(f"Pad ring, mode {mode + 1}. The light on the tablet shows "
                               "the active mode. Press the ring button to change the mode.")
            grid.addWidget(picture, mode + 6, 0, Qt.AlignmentFlag.AlignCenter)
            pair = QHBoxLayout()
            boxes = []
            for way in ("clockwise", "counter-clockwise"):
                turn = QLineEdit()
                turn.setPlaceholderText(way)
                turn.setToolTip(RING_TIP)
                pair.addWidget(turn)
                boxes.append(turn)
            bound = ring_read(pad, mode)
            if bound:
                boxes[0].setText(bound[0])
                boxes[1].setText(bound[1])
            self.rings[mode] = boxes
            grid.addLayout(pair, mode + 6, 1, 1, 2)
        note = QLabel("Precision mode consumes <b>both</b> the Touch and Press fields, "
                      "and cannot be a pie key.")
        grid.addWidget(note, 14, 0, 1, 6)
        apply_btn = QPushButton("Apply bindings")
        apply_btn.clicked.connect(self.apply)
        grid.addWidget(apply_btn, 15, 2)
        self.restyle()

    def pick_prm(self, idx):
        """The round ticks: one key at most; a click on the active one
        clears it, so no precision key at all is a valid state."""
        if self._prm_last == idx and not self.prms[idx].isChecked():
            self._prm_last = None                    # Qt already cleared it? keep in step
        elif self._prm_last == idx:
            self.prms[idx].setChecked(False)         # click on the active tick = clear
            self._prm_last = None
        else:
            for other, prm in self.prms.items():
                if other != idx and prm.isChecked():
                    prm.setChecked(False)
            self.prms[idx].setChecked(True)
            self._prm_last = idx
        self.restyle()

    def prm_row(self):
        """The ticked Precision row, or None."""
        for idx, prm in self.prms.items():
            if prm.isChecked():
                return idx
        return None

    def restyle(self):
        """The outlines follow the state: red across the consumed precision
        row (its Press read-only, showing the toggle chord), amber on a
        ticked pie side's box. The register field stays plain - the
        precision key uses it too (the drag hold)."""
        m = self.prm_row()
        for idx in range(8):
            red = idx == m
            self.touches[idx].set_ants(red or self.tp[idx].isChecked(),
                                       RED if red else AMBER)
            press = self.presses[idx]
            press.setReadOnly(red)
            if red:
                press.setText(toggle_chord())
                press.set_ants(True, RED)
            else:
                press.set_ants(self.pp[idx].isChecked(), AMBER)
            self.tp[idx].set_ants(red, RED)
            self.pp[idx].set_ants(red, RED)
            self.prms[idx].set_ants(red, RED)

    def save_register(self, n, value):
        """Key n's touch register; the daemon hears about it at once."""
        save_conf_key(f"TOUCH_HOLD_{n}", f"{value:.2f}")
        poke_daemon()

    def apply(self):
        problems = []
        m = self.prm_row()
        if m is not None:
            save_conf_key("HOVER_MASK", f"0x{1 << m:02x}")
        else:
            drop_conf_key("HOVER_MASK")
        for idx in range(8):
            touch = self.touches[idx].text().strip()
            press = self.presses[idx].text().strip()
            tp, pp = self.tp[idx].isChecked(), self.pp[idx].isChecked()
            if idx == m:                             # consumed: the toggle chord, nothing else
                kwrite(self.pad, idx, toggle_chord())
                drop_conf_key(f"CHORD_{idx + 1}")
                drop_conf_key(f"TOUCH_CHORD_{idx + 1}")
                continue
            if touch:
                if self.parse and self.parse(touch, tp) is None:
                    problems.append(f"Key {idx + 1}: '{touch}' is not a "
                                    + ("pie touch chord (modifiers plus one F-key)" if tp else
                                       "touch chord (modifiers and F-keys; not Meta alone)"))
                    drop_conf_key(f"TOUCH_CHORD_{idx + 1}")
                else:
                    save_conf_key(f"TOUCH_CHORD_{idx + 1}", touch)
            else:
                drop_conf_key(f"TOUCH_CHORD_{idx + 1}")
                if tp:
                    problems.append(f"Key {idx + 1}: Pie on the touch needs a Touch shortcut")
            if tp or pp:                             # the key belongs to the daemon
                kwrite(self.pad, idx, "Disabled")    # never a deleted line: KWin would leak the raw button
                if pp:
                    if not press:
                        problems.append(f"Key {idx + 1}: Pie on the press needs a Press shortcut")
                        drop_conf_key(f"CHORD_{idx + 1}")
                    elif self.parse and self.parse(press) is None:
                        problems.append(f"Key {idx + 1}: a pie press chord is modifiers plus one F-key")
                        drop_conf_key(f"CHORD_{idx + 1}")
                    else:
                        save_conf_key(f"CHORD_{idx + 1}", press)
                else:
                    drop_conf_key(f"CHORD_{idx + 1}")
                    if press:
                        problems.append(f"Key {idx + 1}: the Press shortcut needs its Pie tick, "
                                        "or clear it")
                continue
            if press and press.lower() != "disabled" and press not in MODIFIER_ONLY \
                    and QKeySequence(press).isEmpty():
                problems.append(f"Key {idx + 1}: '{press}' is not a valid chord")
                continue
            kwrite(self.pad, idx, press)
            drop_conf_key(f"CHORD_{idx + 1}")
        for mode, (up, down) in self.rings.items():
            chords = (up.text().strip(), down.text().strip())
            if any(t and t not in MODIFIER_ONLY and QKeySequence(t).isEmpty() for t in chords):
                problems.append(f"Ring mode {mode + 1}: not a valid chord")
                continue
            kept = ring_read(self.pad, mode)
            ring_write(self.pad, chords[0], chords[1], kept[2] if kept else 5, mode)
        subprocess.run(["qdbus6", "org.kde.KWin", "/KWin",
                        "org.kde.KWin.reconfigure"])
        poke_daemon()
        self.restyle()
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
    win.resize(760, 720)                   # the Pad tab is a 6-column table now
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
