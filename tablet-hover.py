#!/usr/bin/env python3
# tablet-hover.py [--simulate] - ExpressKey touch preview for precision mode.
#
# The Intuos Pro's express keys sense a resting finger before the press (what
# drives "Express View" in Wacom's own driver). While a finger rests on the
# precision-mode key, this daemon shows a GHOST of the area precision mode
# would map right now - same placement math as the toggle - and moves it
# with the pen; it removes the ghost when the finger lifts or the key is
# pressed, when the real toggle takes over.
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
# silence, so the debounce is a timer. While the ghost is up the pen is
# polled from the Pen evdev node (EVIOCGABS, ~30 Hz) and the rectangle is
# re-placed with the toggle's formula x = cx/sw*(sw-w), streamed to
# tablet-overlay.py --follow through its stdin. Silent while precision mode
# is already ON. Messages go to stderr (the journal under autostart).
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
DIR = Path(__file__).resolve().parent
LABEL = "precision mode - press to map here"
SHOW_DELAY = 0.06                    # touch sense must hold this long (debounce)
GHOST_DIM = 0.5                      # fraction of the configured DIM for the ghost
RESCAN = 2.0                         # seconds between checks for new/lost nodes
TICK = 0.03                          # poll period while the ghost is up or a press is being judged
LEARN_WINDOW = 2.0                   # a precision toggle this soon after a one-key press names the key
BUS = {"0003": "usb", "0005": "bt"}

# Built-in layouts: family -> bus -> (report id, touch byte, press byte).
# One bit per key in both bytes, key N = bit N-1. Measured on the Intuos
# Pro M over USB and Bluetooth (2026-09). Bluetooth byte 282 is the key
# byte the kernel's wacom_intuos_pro2_bt_pad() reads; 283 is the touch
# sense it skips.
FAMILIES = {
    "intuos-pro-2017": {"usb": (0x11, 2, 1), "bt": (0x80, 283, 282)},
}
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


def log(msg):
    print(f"tablet-hover: {msg}", file=sys.stderr, flush=True)


def read_conf():
    values = {}
    try:
        for line in CONF.read_text().splitlines():
            key, _, val = line.partition("=")
            values[key.strip()] = val.split("#", 1)[0].strip()
    except OSError:
        pass
    return values


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


def as_int(text, default=None):
    try:
        return int(text, 0)
    except (TypeError, ValueError):
        return default


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


class Ghost:
    def __init__(self):
        self.proc = None
        self.owner = None            # fd whose reports drive the current ghost
        self.pen = None              # Pen evdev fd while the ghost is up
        self.geom = None             # (w, h, sw, sh) while the ghost is up
        self.last = None             # last (x, y) sent to the overlay

    @property
    def up(self):
        return self.proc is not None

    def show(self, owner):
        if self.proc is not None or STATE.exists():
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
            ["python3", str(DIR / "tablet-overlay.py"), x, y, w, h,
             f"{float(dim) * GHOST_DIM:.2f}", LABEL, "--follow"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.owner = owner
        self.pen = pen_open()

    def follow(self):
        """Re-place the ghost for the pen's current position (toggle formula)."""
        if self.proc is None or self.pen is None:
            return
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
        try:
            self.proc.stdin.write(f"{x} {y} {w} {h}\n".encode())
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.hide()

    def hide(self, owner=None):
        if self.proc is not None and owner in (None, self.owner):
            self.proc.terminate()
            self.proc = None
            self.owner = None
            if self.pen is not None:
                os.close(self.pen)
                self.pen = None


def mask_text(mask):
    return "not learned yet" if mask is None else f"0x{mask:02x}"


def watch(conf, ghost):
    """Follow the current set of hidraw nodes until it changes or goes away."""
    nodes = wacom_nodes()
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
        return
    pending = {}                      # fd -> time the touch began; None once the ghost is up
    down = {}                         # fd -> last press-byte value
    learn = None                      # (key bit, deadline, precision was on) after a one-key press
    last_scan = time.monotonic()
    try:
        while fds:
            now = time.monotonic()
            timeout = max(0.0, last_scan + RESCAN - now)
            for since in pending.values():
                if since is not None:
                    timeout = min(timeout, max(0.0, since + SHOW_DELAY - now))
            if ghost.up or learn:
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
                    down.pop(fd, None)
                    ghost.hide(fd)
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
                if touched and not pressed:
                    pending.setdefault(fd, time.monotonic())
                else:
                    pending.pop(fd, None)
                    ghost.hide(fd)
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
                            log(f"learned: the precision key is mask 0x{bit:02x} (saved to {CONF})")
                        except OSError as err:
                            log(f"learned mask 0x{bit:02x} but could not save it: {err}")
                elif now > deadline:
                    learn = None
            for fd, since in list(pending.items()):
                if since is not None and now - since >= SHOW_DELAY:
                    ghost.show(fd)
                    pending[fd] = None          # up (or refused); no timer until the next touch
            if ghost.up:
                ghost.follow()
            if now - last_scan >= RESCAN:
                last_scan = now
                if wacom_nodes() != nodes:
                    return                      # bus switch or tablet gone: rescan
    finally:
        for fd in fds:
            os.close(fd)
        ghost.hide()


def main():
    ghost = Ghost()
    if "--simulate" in sys.argv:
        ghost.show(None)
        if ghost.proc is None:
            sys.exit("no ghost: tablet-precision.sh where failed (tablet asleep?)")
        end = time.monotonic() + 3
        while time.monotonic() < end:
            ghost.follow()
            time.sleep(TICK)
        ghost.hide()
        return
    conf = read_conf()
    while True:
        watch(conf, ghost)
        time.sleep(RESCAN)         # tablet asleep or not yet connected: poll


if __name__ == "__main__":
    main()
