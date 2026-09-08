#!/usr/bin/env python3
# tablet-pen-pos.py [--mapped] - print "X Y SCREEN_W SCREEN_H" (px) for the
# tablet pen. Part of plasma-wacom-center (MIT).
#
# Three sources, best first:
# 1. Kernel evdev state of the pen node (EVIOCGABS): always current whenever
#    the pen is in proximity, regardless of which window it hovers. Needs
#    read access to /dev/input/event* - grant once with the udev uaccess
#    rule printed by install.sh.
# 2. XWayland's stylus device (XInput2 via ctypes): fresh only while the pen
#    hovers an X11 window (Krita, GIMP, Blender); stale over native Wayland
#    windows.
# 3. Neither -> exit 1; the caller falls back to the mouse cursor.
#
# Evdev tells where the pen is ON THE TABLET, which is where it is on the
# screen only while the whole tablet is mapped to the whole screen. --mapped
# puts that through the pen's live outputArea - the rectangle precision mode
# maps it to - so the caller gets the pixel the pen cursor is really on. Plain,
# the raw full-tablet -> full-screen stretch is printed: that is what the
# cursor-stationary math in tablet-precision.sh works in. XWayland already
# reports the mapped position (its valuators are the screen scaled into
# 0..262143), so --mapped leaves that source alone. An inputArea other than
# 0,0,1,1 (a cropped tablet) is not handled.
# DEBUG=1 traces sources and raw axis values.
import ctypes as C
import fcntl
import os
import re
import struct
import subprocess
import sys

os.environ.setdefault("DISPLAY", ":0")
debug = os.environ.get("DEBUG") == "1"


# ── chunk: trace
def trace(msg):
    if debug:
        print(f"# {msg}", file=sys.stderr)


# ── chunk: screen_size
def screen_size():
    x11 = C.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = C.c_void_p
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return None
    screen = x11.XDefaultScreen(dpy)
    return x11.XDisplayWidth(dpy, screen), x11.XDisplayHeight(dpy, screen), x11, dpy


# ── chunk: evdev_pen_norm
def evdev_pen_norm():
    """Normalized (0..1) pen position from the kernel, or None."""
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    node = None
    for block in blocks:
        name_match = re.search(r'Name="([^"]*)"', block)
        if not name_match:
            continue
        name = name_match.group(1).lower()
        if "pen" not in name and "stylus" not in name:
            continue
        handler = re.search(r"Handlers=.*?(event\d+)", block)
        if handler:
            node = f"/dev/input/{handler.group(1)}"
        break
    if not node:
        trace("evdev: no pen/stylus node in /proc/bus/input/devices")
        return None
    try:
        fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except PermissionError:
        trace(f"evdev: no read access to {node} (udev uaccess rule not applied)")
        return None
    except OSError as err:
        trace(f"evdev: {err}")
        return None
    try:
        result = []
        for code in (0, 1):  # ABS_X, ABS_Y
            buf = bytearray(24)
            fcntl.ioctl(fd, 0x80184540 + code, buf)  # EVIOCGABS(code)
            value, lo, hi, _, _, _ = struct.unpack("6i", buf)
            trace(f"evdev: abs{code} value={value} range={lo}..{hi}")
            if hi <= lo:
                return None
            result.append((value - lo) / (hi - lo))
        return tuple(result)
    except OSError as err:
        trace(f"evdev ioctl: {err}")
        return None
    finally:
        os.close(fd)


# ── chunk: XIAnyClassInfo
class XIAnyClassInfo(C.Structure):
    _fields_ = [("type", C.c_int), ("sourceid", C.c_int)]


# ── chunk: XIValuatorClassInfo
class XIValuatorClassInfo(C.Structure):
    _fields_ = [("type", C.c_int), ("sourceid", C.c_int), ("number", C.c_int),
                ("label", C.c_ulong), ("min", C.c_double), ("max", C.c_double),
                ("value", C.c_double), ("resolution", C.c_int), ("mode", C.c_int)]


# ── chunk: XIDeviceInfo
class XIDeviceInfo(C.Structure):
    _fields_ = [("deviceid", C.c_int), ("name", C.c_char_p), ("use", C.c_int),
                ("attachment", C.c_int), ("enabled", C.c_int),
                ("num_classes", C.c_int),
                ("classes", C.POINTER(C.POINTER(XIAnyClassInfo)))]


# ── chunk: xwayland_stylus_norm
def xwayland_stylus_norm(dpy):
    """Normalized (0..1) stylus position from XWayland, or None (may be stale)."""
    xi = C.CDLL("libXi.so.6")
    xi.XIQueryDevice.restype = C.POINTER(XIDeviceInfo)
    xi.XIQueryDevice.argtypes = [C.c_void_p, C.c_int, C.POINTER(C.c_int)]
    xi.XIQueryVersion.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)]
    xi.XIFreeDeviceInfo.argtypes = [C.POINTER(XIDeviceInfo)]
    major, minor = C.c_int(2), C.c_int(2)
    xi.XIQueryVersion(dpy, C.byref(major), C.byref(minor))
    count = C.c_int()
    devs = xi.XIQueryDevice(dpy, 0, C.byref(count))  # 0 = XIAllDevices
    pos = None
    for i in range(count.value):
        dev = devs[i]
        name = (dev.name or b"").decode("utf-8", "replace")
        if "stylus" not in name.lower() or not dev.enabled:
            continue
        axes = {}
        for j in range(dev.num_classes):
            if dev.classes[j].contents.type != 2:  # XIValuatorClass
                continue
            val = C.cast(dev.classes[j], C.POINTER(XIValuatorClassInfo)).contents
            if val.max > val.min:
                axes[val.number] = (val.value - val.min) / (val.max - val.min)
        if 0 in axes and 1 in axes:
            pos = (axes[0], axes[1])
            trace(f"xwayland: {name} -> {pos}")
            break
    xi.XIFreeDeviceInfo(devs)
    return pos


# ── chunk: output_area
def output_area():
    """The pen's KWin outputArea as (fx, fy, fw, fh) fractions, or None.

    Precision mode maps the pen to a rectangle of the screen and keeps it on
    the device as outputArea, so a tablet position n lands at fx + n * fw. The
    sysname comes from the cache tablet-precision.sh writes on every run that
    needs the pen: no cache (or one that is not the pen any more) means there
    is no precision mapping to undo, and the caller keeps the plain stretch.
    """
    cache = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "tabprec", "pen")
    try:
        with open(cache) as fh:
            sysname = fh.read().strip()
    except OSError:
        trace(f"outputArea: no {cache} - the pen is mapped to the whole screen")
        return None
    try:
        out = subprocess.run(
            ["busctl", "--user", "get-property", "org.kde.KWin",
             f"/org/kde/KWin/InputDevice/{sysname}", "org.kde.KWin.InputDevice",
             "tabletTool", "outputArea"],
            capture_output=True, text=True, timeout=2).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as err:
        trace(f"outputArea: busctl: {err}")
        return None
    if len(out) < 2:
        trace(f"outputArea: KWin said nothing about {sysname}")
        return None
    if out[0].strip() != "b true":
        trace(f"outputArea: {sysname} is not a tablet tool any more")
        return None
    fields = out[1].split()
    if len(fields) != 5 or fields[0] != "(dddd)":
        trace(f"outputArea: cannot read {out[1]!r}")
        return None
    try:
        fx, fy, fw, fh = (float(value) for value in fields[1:])
    except ValueError:
        trace(f"outputArea: cannot read {out[1]!r}")
        return None
    if fw <= 0 or fh <= 0:
        return None
    trace(f"outputArea: {fx} {fy} {fw} {fh}")
    return fx, fy, fw, fh


# ── chunk: main-flow
scr = screen_size()
if not scr:
    sys.exit(1)
sw, sh = scr[0], scr[1]

pos = evdev_pen_norm()
source = "evdev"
if pos is None:
    pos = xwayland_stylus_norm(scr[3])
    source = "xwayland"
if pos is None:
    sys.exit(1)
trace(f"source={source}")
if "--mapped" in sys.argv and source == "evdev":
    rect = output_area()
    if rect:
        pos = (rect[0] + pos[0] * rect[2], rect[1] + pos[1] * rect[3])
        trace(f"mapped -> {pos}")
print(f"{int(pos[0] * sw)} {int(pos[1] * sh)} {sw} {sh}")
