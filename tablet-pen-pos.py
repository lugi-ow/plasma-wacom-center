#!/usr/bin/env python3
# tablet-pen-pos.py - print "X Y SCREEN_W SCREEN_H" (px) for the tablet pen.
# Part of plasma-wacom-center (MIT).
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
# The evdev mapping assumes the default full-tablet -> full-screen stretch.
# DEBUG=1 traces sources and raw axis values.
import ctypes as C
import fcntl
import os
import re
import struct
import sys

os.environ.setdefault("DISPLAY", ":0")
debug = os.environ.get("DEBUG") == "1"


def trace(msg):
    if debug:
        print(f"# {msg}", file=sys.stderr)


def screen_size():
    x11 = C.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = C.c_void_p
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return None
    screen = x11.XDefaultScreen(dpy)
    return x11.XDisplayWidth(dpy, screen), x11.XDisplayHeight(dpy, screen), x11, dpy


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


class XIAnyClassInfo(C.Structure):
    _fields_ = [("type", C.c_int), ("sourceid", C.c_int)]


class XIValuatorClassInfo(C.Structure):
    _fields_ = [("type", C.c_int), ("sourceid", C.c_int), ("number", C.c_int),
                ("label", C.c_ulong), ("min", C.c_double), ("max", C.c_double),
                ("value", C.c_double), ("resolution", C.c_int), ("mode", C.c_int)]


class XIDeviceInfo(C.Structure):
    _fields_ = [("deviceid", C.c_int), ("name", C.c_char_p), ("use", C.c_int),
                ("attachment", C.c_int), ("enabled", C.c_int),
                ("num_classes", C.c_int),
                ("classes", C.POINTER(C.POINTER(XIAnyClassInfo)))]


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
print(f"{int(pos[0] * sw)} {int(pos[1] * sh)} {sw} {sh}")
