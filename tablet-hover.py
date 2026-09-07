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
# for HOLD seconds (conf key, default 0.6, the Wacom Center field - long
# enough that a normal press still switches the mode off) and the REAL
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
# The kernel never exposes the touch sense: its Bluetooth pad parser reads
# only the key, centre-button and ring bytes of report 0x80, and the
# EXPRESSKEYCAP HID usage is unmapped. So this reads the tablet's raw HID
# reports from hidraw (one udev uaccess rule, printed by install.sh), every
# Wacom node at once.
#
# Zero configuration on known models: the report layout (which report,
# which byte holds the touch bits, which the press bits) is built in per
# product id below, and the PRECISION KEY is learned - the first time a
# single key press is followed by precision mode switching on or off, that
# key's bit is saved to ~/.config/tabprec.conf as HOVER_MASK. Unknown
# models: run tablet-pad-probe.py once per connection type and write
# HOVER_REPORT_<BUS> / HOVER_BYTE_<BUS> / PRESS_BYTE_<BUS> (BUS = USB or
# BT); HOVER_MASK_<BUS> / PRESS_MASK_<BUS> override the learned key. Conf
# keys always win over the built-ins. Bluetooth and USB use different
# layouts; the daemon switches by itself when the tablet changes bus.
#
# The pad reports only on change: a resting finger is ONE report, then
# silence, so the debounce is a timer. While a rectangle follows the pen,
# the pen is polled from its evdev node (EVIOCGABS, ~30 Hz) and the
# rectangle is re-placed with the toggle's formula x = cx/sw*(sw-w). After
# a press nothing happens until the finger has left the key. The conf is
# re-read when it changes (HOLD, HOVER_* keys). Messages go to stderr (the
# journal under autostart).
#
# --simulate: draw the ghost for 3 s, following the pen, and exit.
import fcntl
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
DIR = Path(__file__).resolve().parent
SHOW_DELAY = 0.06                    # touch sense must hold this long before the ghost (debounce)
HOLD_DEFAULT = 0.6                   # ...and this long before a relocation (precision on); conf key HOLD, Wacom Center field
RESCAN = 2.0                        # seconds between checks for new/lost nodes and conf edits
TICK = 0.03                          # poll period while a rectangle follows the pen or a press is being judged
LEARN_WINDOW = 2.0                   # a precision toggle this soon after a one-key press names the key
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


# ── chunk: conf_stamp
def conf_stamp():
    try:
        return CONF.stat().st_mtime_ns
    except OSError:
        return None


# ── chunk: save_conf_key
def save_conf_key(key, value):
    """Set key=value in tabprec.conf and keep every other line."""
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
    CONF.write_text("\n".join(out) + "\n")      # in place: keeps watchers on the file


# ── chunk: as_int
def as_int(text, default=None):
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        return default


# ── chunk: hold_delay
def hold_delay(conf):
    """Seconds a finger must rest before anything moves: the ghost debounce
    with precision mode off, the relocation hold (conf HOLD) with it on."""
    if not STATE.exists():
        return SHOW_DELAY
    try:
        return max(0.3, float(conf.get("HOLD", HOLD_DEFAULT)))
    except ValueError:
        return HOLD_DEFAULT


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
    """Run tablet-precision.sh MODE (suspend / resume); False when it failed."""
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


# ── chunk: mask_text
def mask_text(mask):
    return "not learned yet" if mask is None else f"0x{mask:02x}"


# ── chunk: watch
def watch(conf, follower):
    """Follow the current set of hidraw nodes until it changes or goes away;
    a conf edit is reloaded in place. False = there was nothing to watch."""
    nodes = wacom_nodes()
    stamp = conf_stamp()
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
        return False
    pending = {}                      # fd -> time the touch began; None once acted on
    held = set()                      # fds whose key was pressed: nothing more until the finger leaves it
    down = {}                         # fd -> last press-byte value
    learn = None                      # (key bit, deadline, precision was on) after a one-key press
    last_scan = time.monotonic()
    try:
        while fds:
            now = time.monotonic()
            timeout = max(0.0, last_scan + RESCAN - now)
            for since in pending.values():
                if since is not None:
                    timeout = min(timeout, max(0.0, since + hold_delay(conf) - now))
            if follower.up or learn:
                timeout = min(timeout, TICK)
            ready, _, _ = select.select(list(fds), [], [], timeout)
            for fd in ready:
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
                    follower.hide(fd)
                    continue
                if report[0] != lay["report"] or len(report) <= lay["touch"]:
                    continue
                pb = lay["press"]
                press_bits = report[pb] if pb is not None and len(report) > pb else 0
                new_bits = press_bits & ~down.get(fd, 0)
                down[fd] = press_bits
                if new_bits and new_bits & (new_bits - 1) == 0:          # exactly one key went down
                    learn = (new_bits, time.monotonic() + LEARN_WINDOW, STATE.exists())
                if lay["mask"] is None:
                    continue                                              # key not known yet
                touched = bool(report[lay["touch"]] & lay["mask"])
                pressed = bool(press_bits & (lay["press_mask"] or lay["mask"]))
                if pressed:                     # the toggle takes over: ghost closes, a relocation is confirmed
                    pending.pop(fd, None)
                    held.add(fd)
                    follower.hide(fd, confirmed=True)
                elif touched:
                    if fd not in held:
                        pending.setdefault(fd, time.monotonic())
                else:                           # finger off the key: ghost closes, a relocation snaps back
                    held.discard(fd)
                    pending.pop(fd, None)
                    follower.hide(fd)
            now = time.monotonic()
            if learn:
                bit, deadline, was_on = learn
                if STATE.exists() != was_on:                              # that press toggled precision mode
                    learn = None
                    if any(node[3]["mask"] != bit for node in fds.values()):
                        conf["HOVER_MASK"] = f"0x{bit:02x}"
                        for node in fds.values():
                            node[3] = layout_for(conf, node[1], node[2])
                        try:
                            save_conf_key("HOVER_MASK", f"0x{bit:02x}")
                            stamp = conf_stamp()
                            log(f"learned: the precision key is mask 0x{bit:02x} (saved to {CONF})")
                        except OSError as err:
                            log(f"learned mask 0x{bit:02x} but could not save it: {err}")
                elif now > deadline:
                    learn = None
            for fd, since in list(pending.items()):
                if since is not None and now - since >= hold_delay(conf):
                    (follower.move if STATE.exists() else follower.show)(fd)
                    pending[fd] = None          # up (or refused); no timer until the next touch
            if follower.up:
                follower.follow()
            if now - last_scan >= RESCAN:
                last_scan = now
                if wacom_nodes() != nodes:
                    return True                 # bus switch or tablet gone: rescan
                if not follower.up and conf_stamp() != stamp:
                    conf = read_conf()          # conf edited (a ring tick, a Center slider): reload it in place,
                    stamp = conf_stamp()        # a finger already resting on the key stays known
                    for node in fds.values():
                        node[3] = layout_for(conf, node[1], node[2]) or node[3]
    finally:
        for fd in fds:
            os.close(fd)
        follower.hide()
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
    while True:
        if not watch(read_conf(), follower):
            time.sleep(RESCAN)         # tablet asleep or not yet connected: poll


if __name__ == "__main__":
    main()
