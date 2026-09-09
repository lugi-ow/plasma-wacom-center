#!/usr/bin/env python3
# tablet-hover.py [--simulate] - ExpressKey touch preview for precision mode.
#
# The Intuos Pro's express keys sense a resting finger before the press (what
# drives "Express View" in Wacom's own driver). While a finger rests on the
# precision-mode key, this daemon shows a GHOST of the area precision mode
# would map right now - same placement math as the toggle - and moves it
# with the pen; it removes the ghost when the finger lifts or the key is
# pressed, when the real toggle takes over. The ghost is the look of
# precision mode itself (tablet-overlay.py --waiting: the same dim bands and
# border, the border dashed and flowing clockwise - a preview, waiting to be
# activated).
#
# With precision mode already ON the same key RELOCATES it. Rest the finger
# for HOLD seconds (conf key, default 0.15, the Wacom Center field) and the REAL
# overlay, the precision UI itself and not the ghost, starts following the
# pen with the same placement math and the ghost's flowing border (the
# pipe lines "waiting" / "solid") while the pen gets the base mapping back
# (tablet-precision.sh suspend): the cursor roams the whole screen and the
# area travels around it. Press the key to map the area there; lift without
# pressing and the overlay snaps back and the old area is mapped again
# (tablet-precision.sh resume). The overlay is moved through its named pipe
# (tablet-overlay.py --fifo), the current geometry comes from the toggle's
# area file, and a marker file, kept fresh while the overlay follows, tells
# the toggle that the coming press is a move, not an OFF. All three live in
# $XDG_RUNTIME_DIR/tabprec next to the toggle's state file.
#
# HOLD has no floor. At 0 every touch starts a drag at once and every press
# is a move, so the way OUT is the LONG PRESS: keep the key pressed for LONG
# seconds after a press that confirmed a drag (conf key, default 0.7, the
# second Wacom Center field; 0 switches the long press off) and precision
# mode goes off. The area lands at the press first - KWin fires the toggle
# on the key-down and nothing can hold that back - and the daemon runs the
# toggle again LONG later; the toggle script serializes its runs with a
# lock, so the two land in a row whatever their timing.
#
# The kernel never exposes the touch sense: its Bluetooth pad parser reads
# only the key, centre-button and ring bytes of report 0x80, and the
# EXPRESSKEYCAP HID usage is unmapped. So this reads the tablet's raw HID
# reports from hidraw (one udev uaccess rule, printed by install.sh), every
# Wacom node at once.
#
# Zero configuration on known models: the report layout (which report,
# which byte holds the touch bits, which the press bits) is built in per
# product id below. The PRECISION KEY is defined, not guessed: Wacom
# Center's Precision column writes its bit to ~/.config/tabprec.conf as
# HOVER_MASK (no key ticked = no HOVER_MASK = the ghost and the drag stay
# off). Unknown models: run tablet-pad-probe.py once per connection type
# and write HOVER_REPORT_<BUS> / HOVER_BYTE_<BUS> / PRESS_BYTE_<BUS> (BUS
# = USB or BT); HOVER_MASK_<BUS> / PRESS_MASK_<BUS> override per bus. Conf
# keys always win over the built-ins. Bluetooth and USB use different
# layouts; the daemon switches by itself when the tablet changes bus.
#
# The pad reports only on change: a resting finger is ONE report, then
# silence, so the debounce is a timer. While a rectangle follows the pen,
# the pen is polled from its evdev node (EVIOCGABS, ~30 Hz) and the
# rectangle is re-placed with the toggle's formula x = cx/sw*(sw-w). After
# a press nothing happens until the finger has left the key. The conf is
# re-read when a line arrives on $XDG_RUNTIME_DIR/tabprec/hover.ctl -
# Wacom Center pokes that pipe on every Apply and delay change; after a
# hand edit, `echo reload > .../hover.ctl` does the same (a reload waits
# until no rectangle follows the pen). Hardware still polls: the nodes
# are rescanned every 2 s - the tablet announces nothing on its own.
# Messages go to stderr (the journal under autostart).
#
# A finger landing on ANY pad key also WARPS THE MOUSE onto the pen (and the
# press does it again). KWin keeps the mouse pointer and the pen cursor apart,
# and whatever asks it "where is the pointer" - Kando placing a pie,
# workspace.cursorPos - gets the mouse, so a menu bound to a pad key's chord
# opened wherever the mouse was left. For a key bound in kcminputrc the warp
# is a race the daemon LOSES: KWin synthesizes the chord inside its own
# handling of the pad button and Kando reads the pointer ~2 ms later, while
# the warp needs a userspace round trip from the same HID report - the pie
# opened one press behind, every time (measured 2026-09-09; the touch sense
# leads only sometimes over Bluetooth, so it cannot close the race either).
# CHORD_<n> in the conf ends the race: pad key n is set to DISABLED in
# kcminputrc (Disabled, not a deleted line - KWin hands an unbound pad
# button to a tablet-aware app) and the daemon presses the chord itself
# (tablet-pointer-warp.py parse_chord/chord: modifiers in KWin's own order,
# then one F-key) right after the warp on the SAME virtual device - one
# device, one write order, KWin processes the motion first,
# deterministically. The chord is held until the key is released, like a
# real key (Kando's turbo mode keeps working); a lost node releases it. n =
# the daemon's key number = press-byte bit n-1, the numbering HOVER_MASK
# uses. Conf WARP=0 switches the warp off (chords still fire); the touch
# warp stays as a best effort for keys kcminputrc still owns.
#
# TOUCH_CHORD_<n> holds a chord DOWN while a finger RESTS on key n and
# releases it at the lift - a held Ctrl for Blender's sculpt, a pie on a
# touch. The finger must rest key n's TOUCH REGISTER first (conf
# TOUCH_HOLD_<n>, the Pad tab's per-key column; conf HOLD is the fallback
# default; 0 = at once); a press that comes sooner wins - that contact fires
# only the press action and no touch chord until the finger has left the
# key. A press AFTER the chord engaged keeps it held (Ctrl+click combos).
# Bare modifiers are allowed here, except Meta alone (a lone synthetic
# Meta press-and-release is kglobalaccel's launcher tap). The warp repeats
# right before the chord engages, so a pie bound to a touch opens under
# the pen. The precision key's touch belongs to the ghost and the drag:
# a TOUCH_CHORD on that key is ignored.
#
# --simulate: draw the ghost for 3 s, following the pen, and exit.
import fcntl
import importlib.util
import os
import re
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tabprec.conf"
RD = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tabprec"
STATE = RD / "saved-area"           # exists while precision mode is ON
AREA = RD / "area"                  # "X Y W H DIM SW SH FX FY FW FH" of the mapping precision mode has on (the toggle writes it)
FIFO = RD / "overlay.fifo"          # the live overlay's geometry pipe (tablet-overlay.py --fifo)
MARK = RD / "relocate"              # kept fresh while the overlay follows the pen: the toggle moves (< 3 s old) instead of switching off
CTL = RD / "hover.ctl"              # a line here = re-read the conf (Wacom Center pokes it on Apply)
DIR = Path(__file__).resolve().parent
SHOW_DELAY = 0.06                    # touch sense must hold this long before the ghost (debounce)
HOLD_DEFAULT = 0.15                  # ...and this long before a relocation (precision on); conf key HOLD, Wacom Center field
LONG_DEFAULT = 0.7                   # a press that confirmed a drag, kept down this long, switches precision mode off; conf key LONG, 0 = off
RESCAN = 2.0                        # seconds between checks for new/lost hidraw nodes (hardware only)
TICK = 0.03                          # poll period while a rectangle follows the pen or a press is being judged
BUS = {"0003": "usb", "0005": "bt"}

# ── chunk: FAMILIES
# Built-in layouts: family -> bus -> (report id, touch byte, press byte).
# One bit per key in both bytes, key N = bit N-1. Measured on the Intuos
# Pro M over USB and Bluetooth (2026-09). Bluetooth byte 282 is the key
# byte the kernel's wacom_intuos_pro2_bt_pad() reads; 283 is the touch
# sense it skips.
FAMILIES = {
    "intuos-pro-2017": {"usb": (0x11, 2, 1), "bt": (0x80, 283, 282)},
}
# ── chunk: MODELS
# (vendor, product) -> family. M measured; S and L share the firmware
# generation and the kernel's Bluetooth pad parser, so the same layout is
# expected - the probe confirms it in a minute if the ghost never shows.
MODELS = {
    ("056A", "0357"): "intuos-pro-2017",   # Intuos Pro M (PTH-660), USB
    ("056A", "0360"): "intuos-pro-2017",   # Intuos Pro M, Bluetooth
    ("056A", "0358"): "intuos-pro-2017",   # Intuos Pro L (PTH-860), USB
    ("056A", "0361"): "intuos-pro-2017",   # Intuos Pro L, Bluetooth
    ("056A", "0392"): "intuos-pro-2017",   # Intuos Pro S (PTH-460), USB
    ("056A", "0393"): "intuos-pro-2017",   # Intuos Pro S, Bluetooth
}


# ── chunk: log
def log(msg):
    print(f"tablet-hover: {msg}", file=sys.stderr, flush=True)


# ── chunk: read_conf
def read_conf():
    values = {}
    try:
        for line in CONF.read_text().splitlines():
            key, _, val = line.partition("=")
            values[key.strip()] = val.split("#", 1)[0].strip()
    except OSError:
        pass
    return values


# ── chunk: as_int
def as_int(text, default=None):
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        return default


# ── chunk: touch_delay
def touch_delay(conf, n=None):
    """Key n's touch register (the Pad tab's per-key column): seconds a
    resting finger waits before its touch action starts - a touch chord,
    the area drag. Conf TOUCH_HOLD_<n>, falling back to HOLD, then the
    default. No floor: 0 = at the first touch report."""
    keys = (f"TOUCH_HOLD_{n}", "HOLD") if n else ("HOLD",)
    for key in keys:
        try:
            return max(0.0, float(conf[key]))
        except (KeyError, ValueError):
            continue
    return HOLD_DEFAULT


# ── chunk: hold_delay
def hold_delay(conf, n=None):
    """Seconds a finger must rest before a rectangle moves: the ghost
    debounce with precision mode off, the precision key's touch register
    with it on."""
    return touch_delay(conf, n) if STATE.exists() else SHOW_DELAY


# ── chunk: long_delay
def long_delay(conf):
    """Seconds a press that confirmed a drag must stay down to switch
    precision mode off (conf LONG); 0 or less = no long press."""
    try:
        return float(conf.get("LONG", LONG_DEFAULT))
    except ValueError:
        return LONG_DEFAULT


# ── chunk: layout_for
def layout_for(conf, bus, product):
    """Report layout for one node: conf keys over built-ins. None = unknown.
    Returns {report, touch, press, mask, press_mask}; mask None = not learned yet."""
    def pick(key, fallback=None):
        val = as_int(conf.get(f"{key}_{bus.upper()}", conf.get(key)))
        return fallback if val is None else val
    builtin = FAMILIES.get(MODELS.get(("056A", product.upper()), ""), {}).get(bus) or (None, None, None)
    touch = pick("HOVER_BYTE", builtin[1])
    if touch is None:
        return None
    mask = pick("HOVER_MASK")
    return {"report": pick("HOVER_REPORT", builtin[0] if builtin[0] is not None else 0x80),
            "touch": touch, "press": pick("PRESS_BYTE", builtin[2]),
            "mask": mask, "press_mask": pick("PRESS_MASK", mask)}


# ── chunk: wacom_nodes
def wacom_nodes():
    """[(path, bus, product)] for every Wacom hidraw node (vendor 056A)."""
    found = []
    base = "/sys/class/hidraw"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return found
    for name in names:
        try:
            uevent = open(f"{base}/{name}/device/uevent").read()
        except OSError:
            continue
        match = re.search(r"^HID_ID=(\d{4}):0000056A:0000([0-9A-F]{4})", uevent, re.M | re.I)
        if match:
            found.append((f"/dev/{name}", BUS.get(match.group(1), match.group(1)),
                          match.group(2).upper()))
    return found


# ── chunk: pen_open
def pen_open():
    """fd of the tablet's Pen evdev node (uaccess ACL), or None."""
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    for block in blocks:
        if 'Name="Wacom' in block and 'Pen"' in block:
            match = re.search(r"Handlers=.*?(event\d+)", block)
            if match:
                try:
                    return os.open(f"/dev/input/{match.group(1)}", os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    return None
    return None


# ── chunk: pen_norm
def pen_norm(fd):
    """Normalized (0..1) pen position from the kernel's current ABS state."""
    result = []
    for code in (0, 1):                      # ABS_X, ABS_Y
        buf = bytearray(24)
        try:
            fcntl.ioctl(fd, 0x80184540 + code, buf)   # EVIOCGABS(code)
        except OSError:
            return None
        value, lo, hi = struct.unpack("6i", buf)[:3]
        if hi <= lo:
            return None
        result.append((value - lo) / (hi - lo))
    return tuple(result)


# ── chunk: toggle
def toggle(mode):
    """Run tablet-precision.sh MODE (suspend / resume / toggle); False when it failed."""
    try:
        return subprocess.run([str(DIR / "tablet-precision.sh"), mode], timeout=5,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ── chunk: Follower
class Follower:
    """The rectangle that follows the pen. Precision OFF: the GHOST, an
    overlay of its own in the waiting look. Precision ON: the real overlay,
    dragged through its pipe for a RELOCATION with the waiting border -
    snapped back home and solid again on a lift, left where it is and
    solid for the toggle on a press."""

    def __init__(self):
        self.proc = None             # the ghost overlay process (its stdin is the geometry pipe)
        self.sink = None             # fd the geometry lines go to; None = nothing follows
        self.owner = None            # hidraw fd whose reports drive the current follow
        self.pen = None              # Pen evdev fd while following
        self.geom = None             # (w, h, sw, sh)
        self.last = None             # last (x, y) written
        self.home = None             # relocation only: the line that puts the overlay back

    @property
    def up(self):
        return self.sink is not None

    def show(self, owner):
        """Precision OFF: draw the ghost where a toggle would map right now."""
        if self.up or STATE.exists():
            return
        try:
            out = subprocess.run([str(DIR / "tablet-precision.sh"), "where"],
                                 capture_output=True, text=True, timeout=5).stdout.split()
            x, y, w, h, dim, sw, sh = out[:7]
            self.geom = tuple(map(int, (w, h, sw, sh)))
            self.last = (int(x), int(y))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        self.proc = subprocess.Popen(
            ["python3", str(DIR / "tablet-overlay.py"), x, y, w, h, dim, "--waiting", "--follow"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sink = self.proc.stdin.fileno()
        self.home = None
        self.owner = owner
        self.pen = pen_open()

    def move(self, owner):
        """Precision ON: drag the real overlay after the pen until a press (the
        toggle re-maps there) or a lift (snap back)."""
        if self.up or not STATE.exists():
            return
        try:
            x, y, w, h, _dim, sw, sh = AREA.read_text().split()[:7]
            self.geom = tuple(map(int, (w, h, sw, sh)))
            self.sink = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)   # ENXIO: no overlay reads the pipe
        except (OSError, ValueError) as err:
            log(f"cannot relocate ({err}): switch precision mode off and on again")
            return
        self.home = f"{x} {y} {w} {h}\n".encode()
        self._send(b"waiting\n")              # the flowing border: a preview until the press
        self.last = None                      # the first tick places the rectangle at the pen's aim
        self.owner = owner
        self.pen = pen_open()
        MARK.touch()
        if not toggle("suspend"):             # base mapping while aiming: the cursor roams, the area travels with it
            log("suspend failed: the cursor stays inside the old area while aiming")

    def follow(self):
        """Re-place the rectangle for the pen's current position (toggle formula)."""
        if not self.up or self.pen is None:
            return
        if self.home is not None:
            MARK.touch()                      # still relocating: the marker stays fresh for the toggle
        norm = pen_norm(self.pen)
        if norm is None:
            return
        w, h, sw, sh = self.geom
        cx, cy = int(norm[0] * sw), int(norm[1] * sh)
        x = int(cx / sw * (sw - w) + 0.5)
        y = int(cy / sh * (sh - h) + 0.5)
        if (x, y) == self.last:
            return
        self.last = (x, y)
        if not self._send(f"{x} {y} {w} {h}\n".encode()):
            self.hide()

    def _send(self, line):
        try:
            os.write(self.sink, line)
            return True
        except OSError:
            return False

    def hide(self, owner=None, confirmed=False):
        """Ghost: close it. Relocation: cancelled - the overlay goes home and
        the marker is dropped - unless confirmed, when the overlay stays put
        and the marker waits for the toggle."""
        if not self.up or owner not in (None, self.owner):
            return
        if self.home is not None and confirmed:
            log(f"relocation confirmed: overlay at {self.last}, the toggle maps there")
            self._send(b"solid\n")            # activated: the border stops flowing where it is
        elif self.home is not None:
            log("relocation cancelled: overlay back home")
            self._send(self.home + b"solid\n")
            MARK.unlink(missing_ok=True)
            toggle("resume")                  # the old area is mapped again
        if self.proc is not None:
            self.proc.stdin.close()           # closes the sink fd; the ghost quits on EOF
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                pass
            self.proc = None
        else:
            os.close(self.sink)
        self.sink = self.owner = self.home = None
        if self.pen is not None:
            os.close(self.pen)
            self.pen = None


# ── chunk: Warper
class Warper:
    """The mouse pointer moved onto the pen when a finger lands on a pad key
    (and again at the press), so that whatever the key's chord opens - a
    Kando pie bound in Kando's own editor, anything that asks KWin where the
    pointer is - lands under the pen. One virtual absolute mouse
    (tablet-pointer-warp.py, imported from this file's folder), created once
    and kept for the daemon's life: KWin lists it a single time and a warp
    costs one motion event. The device also carries the chord alphabet's
    keyboard keys: chord_down presses a conf CHORD_<n> right after the warp
    on the same device (write order = KWin's processing order, so the warp
    is in place before the chord opens anything), chord_up releases it with
    the pad key, release_all sweeps up when a node goes away. Precision ON:
    the pen's tablet position goes through the area's fractions from the
    area file (the correction tablet-pen-pos.py --mapped makes); during a
    drag the base mapping is back and the plain position is right. No
    /dev/uinput, no KWin: the warper stays off with a line in the log,
    retried every 30 s, and chords are skipped with a line."""
    RETRY = 30.0

    def __init__(self):
        self.fd = None
        self.next_try = 0.0
        self.screen = None           # (sw, sh) for the log's pixels, when X answers
        self.held = {}               # ("press" | "touch", key number) -> (codes, label) currently down
        self.mod = None
        try:
            spec = importlib.util.spec_from_file_location(
                "tablet_pointer_warp", DIR / "tablet-pointer-warp.py")
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        except Exception as err:                     # noqa: BLE001 - any import trouble = no warp, the rest runs
            log(f"no pointer warp: {err}")

    def ensure(self):
        """Create the virtual mouse when there is none; a failure waits RETRY s."""
        if self.fd is not None or self.mod is None or time.monotonic() < self.next_try:
            return
        self.next_try = time.monotonic() + self.RETRY
        try:
            self.fd, node = self.mod.create(self.mod.CHORD_KEYS)
        except (OSError, RuntimeError) as err:
            log(f"pointer warp off ({err}); next try in {self.RETRY:.0f} s")
            return
        try:
            self.screen = self.mod.screen_size()
        except (SystemExit, OSError):
            self.screen = None
        log(f"pointer warp ready: virtual mouse {node}")

    def close(self):
        if self.fd is not None:
            self.mod.destroy(self.fd)   # the kernel releases any keys still down
            self.fd = None
        self.held.clear()

    def chord_down(self, tag, text, label):
        """Press a conf chord on the virtual device - called right after the
        warp that triggered it, so the same fd carries the motion first and
        the chord second. tag = ("press" | "touch", key number); a press
        chord must carry one non-modifier key, a touch chord may be bare
        modifiers (it is held, not tapped)."""
        if tag in self.held:
            return
        codes = self.mod.parse_chord(text, tag[0] == "press") if self.mod else None
        if codes is None:
            log(f"chord ({label}) '{text}': outside the chord rules, ignored")
            return
        if self.fd is None:
            log(f"chord ({label}): no virtual device, skipped")
            return
        try:
            self.mod.chord(self.fd, codes, True)
        except OSError as err:
            log(f"chord failed ({err}); the virtual mouse is recreated")
            self.close()
            return
        self.held[tag] = (codes, label)
        log(f"chord ({label}): {text} down")

    def chord_up(self, tag):
        """Release a held chord: its pad key came up, the finger lifted, or
        its node went away."""
        entry = self.held.pop(tag, None)
        if entry is None or self.fd is None:
            return
        codes, label = entry
        try:
            self.mod.chord(self.fd, codes, False)
        except OSError as err:
            log(f"chord release failed ({err}); the virtual mouse is recreated")
            self.close()
            return
        log(f"chord ({label}): up")

    def release_all(self):
        """Every held chord up - a hidraw node vanished mid-press, or the
        watch loop is leaving."""
        for tag in list(self.held):
            self.chord_up(tag)

    def warp(self, mapped, why="press"):
        """Move the mouse onto the pen; mapped = through the area on record.
        why names the trigger in the log (touch / press)."""
        if self.fd is None:
            return
        pen = pen_open()
        if pen is None:
            return
        try:
            norm = pen_norm(pen)
        finally:
            os.close(pen)
        if norm is None:
            return
        fx, fy = norm
        if mapped:
            try:
                ax, ay, aw, ah = map(float, AREA.read_text().split()[7:11])
                fx, fy = ax + fx * aw, ay + fy * ah
            except (OSError, ValueError):
                pass                                 # no fractions on record: the plain stretch
        try:
            self.mod.warp(self.fd, fx, fy)
        except OSError as err:
            log(f"pointer warp failed ({err}); the virtual mouse is recreated")
            self.close()
            return
        where = (f"({int(fx * self.screen[0])}, {int(fy * self.screen[1])})" if self.screen
                 else f"({fx:.4f}, {fy:.4f}) of the screen")
        log(f"warp ({why}): mouse to {where}" + (" in the precision area" if mapped else ""))


# ── chunk: mask_text
def mask_text(mask):
    return "none (no Precision key ticked)" if mask is None else f"0x{mask:02x}"


# ── chunk: watch
def watch(conf, follower, warper=None):
    """Follow the current set of hidraw nodes until it changes or goes away.
    A line on the control pipe reloads the conf (deferred while a rectangle
    follows the pen). False = there was nothing to watch."""
    if warper is not None:
        warper.ensure()
    nodes = wacom_nodes()
    try:
        os.mkfifo(CTL)
    except FileExistsError:
        pass
    except OSError as err:
        log(f"no control pipe ({err}): conf reloads need a daemon restart")
    try:
        ctl = os.open(CTL, os.O_RDWR | os.O_NONBLOCK)   # RDWR: pokers may come and go
    except OSError:
        ctl = None
    fds = {}                          # fd -> [path, bus, product, layout]
    for path, bus, product in nodes:
        layout = layout_for(conf, bus, product)
        if layout is None:
            log(f"{path} ({bus}, product {product}): unknown layout - run tablet-pad-probe.py")
            continue
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError as err:
            log(f"{path}: {err}")
            continue
        fds[fd] = [path, bus, product, layout]
        log(f"{path}: {bus} report 0x{layout['report']:02x}, touch byte {layout['touch']}, "
            f"press byte {layout['press']}, precision key {mask_text(layout['mask'])}")
    if not fds:
        if ctl is not None:
            os.close(ctl)
        return False
    pending = {}                      # fd -> time the touch began; None once acted on
    held = set()                      # fds whose key was pressed: nothing more until the finger leaves it
    down = {}                         # fd -> last press-byte value
    rest = {}                         # fd -> last touch-byte value (a finger landing on any key warps the mouse)
    long_press = {}                   # fd -> deadline while a key pressed after a drag stays down: precision mode off at the deadline
    touch_since = {}                  # (fd, bit) -> when the finger landed on a TOUCH_CHORD key; gone once engaged, pressed or lifted
    reload_pending = False            # a control-pipe poke arrived; applied once nothing follows the pen
    last_scan = time.monotonic()
    try:
        while fds:
            now = time.monotonic()
            timeout = max(0.0, last_scan + RESCAN - now)
            for pfd, since in pending.items():
                if since is not None:
                    mask_n = (fds[pfd][3]["mask"] or 0).bit_length() or None
                    timeout = min(timeout, max(0.0, since + hold_delay(conf, mask_n) - now))
            for (tfd, bit), since in touch_since.items():
                timeout = min(timeout, max(0.0, since + touch_delay(conf, bit + 1) - now))
            for deadline in long_press.values():
                timeout = min(timeout, max(0.0, deadline - now))
            if follower.up:
                timeout = min(timeout, TICK)
            readable = list(fds) + ([ctl] if ctl is not None else [])
            ready, _, _ = select.select(readable, [], [], timeout)
            for fd in ready:
                if fd == ctl:
                    os.read(ctl, 4096)                        # drain; any content means "reload"
                    reload_pending = True
                    continue
                lay = fds[fd][3]
                try:
                    report = os.read(fd, 4096)
                except OSError:
                    report = b""
                if not report:
                    os.close(fd)
                    del fds[fd]
                    pending.pop(fd, None)
                    held.discard(fd)
                    down.pop(fd, None)
                    long_press.pop(fd, None)
                    for key in [k for k in touch_since if k[0] == fd]:
                        del touch_since[key]
                    follower.hide(fd)
                    if warper is not None:
                        warper.release_all()      # a chord must not outlive its pad key's node
                    continue
                if report[0] != lay["report"] or len(report) <= lay["touch"]:
                    continue
                pb = lay["press"]
                press_bits = report[pb] if pb is not None and len(report) > pb else 0
                new_bits = press_bits & ~down.get(fd, 0)
                gone_bits = down.get(fd, 0) & ~press_bits
                down[fd] = press_bits
                touch_bits = report[lay["touch"]]
                new_touch = touch_bits & ~rest.get(fd, 0)
                gone_touch = rest.get(fd, 0) & ~touch_bits
                rest[fd] = touch_bits
                if (new_touch or new_bits) and warper is not None and conf.get("WARP", "1") != "0":
                    # the mouse onto the pen when a finger LANDS on any key, and again at the press.
                    # For a key kcminputrc owns this is best effort (KWin fires the chord inside its
                    # own handling of the pad button; the warp can lose). A CHORD_<n> key is exact:
                    # its chord goes out below, AFTER these motion frames, on the same device. Mapped
                    # through the area while precision mode is on, unless a drag has the base mapping back.
                    warper.warp(STATE.exists() and not (follower.up and follower.home is not None),
                                "press" if new_bits else "touch")
                if warper is not None and (new_bits or gone_bits or new_touch or gone_touch):
                    # conf CHORD_<n> / TOUCH_CHORD_<n>: the daemon presses the chords itself - such a
                    # key is Disabled in kcminputrc. Ups before downs (a report can swap keys); every
                    # release mirrors its trigger, so a held chord stays held (Kando's turbo mode).
                    # The precision key (the mask) is exempt: its touch is the ghost and the drag.
                    mask_bit = lay["mask"] or 0
                    for bit in range(8):
                        key = 1 << bit
                        if gone_touch & key:
                            warper.chord_up(("touch", bit + 1))
                            touch_since.pop((fd, bit), None)
                        if gone_bits & key:
                            warper.chord_up(("press", bit + 1))
                        if new_bits & key:
                            touch_since.pop((fd, bit), None)     # pressed before the delay: no touch chord this contact
                            text = conf.get(f"CHORD_{bit + 1}", "")
                            if text and not key & mask_bit:
                                warper.chord_down(("press", bit + 1), text, f"key {bit + 1}")
                        if (new_touch & key and not press_bits & key and not key & mask_bit
                                and conf.get(f"TOUCH_CHORD_{bit + 1}", "")):
                            touch_since[(fd, bit)] = time.monotonic()   # engages after the delay, below
                if lay["mask"] is None:
                    continue                                              # key not known yet
                touched = bool(report[lay["touch"]] & lay["mask"])
                pressed = bool(press_bits & (lay["press_mask"] or lay["mask"]))
                if pressed:                     # the toggle takes over: ghost closes, a relocation is confirmed
                    pending.pop(fd, None)
                    if fd not in held and follower.up and follower.owner == fd \
                            and follower.home is not None and long_delay(conf) > 0:
                        long_press[fd] = time.monotonic() + long_delay(conf)   # kept down: precision mode off
                    held.add(fd)
                    follower.hide(fd, confirmed=True)
                elif touched:
                    long_press.pop(fd, None)    # released, the finger still rests
                    if fd not in held:
                        pending.setdefault(fd, time.monotonic())
                else:                           # finger off the key: ghost closes, a relocation snaps back
                    long_press.pop(fd, None)
                    held.discard(fd)
                    pending.pop(fd, None)
                    follower.hide(fd)
            now = time.monotonic()
            for (tfd, bit), since in list(touch_since.items()):
                if now - since < touch_delay(conf, bit + 1):
                    continue                                              # not rested long enough yet
                del touch_since[(tfd, bit)]
                if tfd not in fds or down.get(tfd, 0) & (1 << bit):
                    continue                                              # pressed meanwhile: this contact is spent
                text = conf.get(f"TOUCH_CHORD_{bit + 1}", "")
                if not text or warper is None:
                    continue
                if conf.get("WARP", "1") != "0":
                    # a fresh warp right before the chord: the pen may have moved during the delay,
                    # and a pie bound to the touch must open where the pen is NOW
                    warper.warp(STATE.exists() and not (follower.up and follower.home is not None),
                                "touch")
                warper.chord_down(("touch", bit + 1), text, f"key {bit + 1} touch")
            for fd, since in list(pending.items()):
                mask_n = (fds[fd][3]["mask"] or 0).bit_length() or None
                if since is not None and now - since >= hold_delay(conf, mask_n):
                    (follower.move if STATE.exists() else follower.show)(fd)
                    pending[fd] = None          # up (or refused); no timer until the next touch
            for fd, deadline in list(long_press.items()):
                if now >= deadline:             # the key stayed down after the move: leave precision mode
                    del long_press[fd]
                    log("long press: precision mode off")
                    if not toggle("toggle"):
                        log("long press: the toggle failed, precision mode stays on")
            if follower.up:
                follower.follow()
            if reload_pending and not follower.up:
                reload_pending = False          # a Wacom Center Apply, a delay change, or a hand poke
                conf = read_conf()              # a finger already resting on a key stays known
                for node in fds.values():
                    node[3] = layout_for(conf, node[1], node[2]) or node[3]
                log("conf reloaded")
            if now - last_scan >= RESCAN:
                last_scan = now
                if warper is not None:
                    warper.ensure()                 # a virtual mouse lost or never created: another try
                if wacom_nodes() != nodes:
                    return True                 # bus switch or tablet gone: rescan
    finally:
        for fd in fds:
            os.close(fd)
        if ctl is not None:
            os.close(ctl)
        follower.hide()
        if warper is not None:
            warper.release_all()
    return True


# ── chunk: main
def main():
    follower = Follower()
    if "--simulate" in sys.argv:
        follower.show(None)
        if not follower.up:
            sys.exit("no ghost: tablet-precision.sh where failed (tablet asleep?)")
        end = time.monotonic() + 3
        while time.monotonic() < end:
            follower.follow()
            time.sleep(TICK)
        follower.hide()
        return
    warper = Warper()
    while True:
        if not watch(read_conf(), follower, warper):
            time.sleep(RESCAN)         # tablet asleep or not yet connected: poll


if __name__ == "__main__":
    main()
