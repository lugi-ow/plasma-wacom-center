#!/usr/bin/env python3
# tablet-pointer-warp.py X Y [SW SH] - move the MOUSE pointer to screen pixel
# X,Y on Plasma 6 Wayland, without root, through a short-lived virtual
# absolute mouse on /dev/uinput (Kubuntu tags uinput "uaccess", so the
# seat user may write it).
#
# Why: KWin keeps the mouse pointer and the pen's tablet cursor apart, and
# everything that asks the compositor "where is the pointer" - Kando's menu
# placement, KWin scripting's workspace.cursorPos - gets the MOUSE. Warping
# the mouse onto the pen right before such a call makes the two agree.
#
# Waits until KWin has picked the virtual device up (its D-Bus device list),
# sends one absolute motion, holds the device a moment so the motion is
# processed, then removes it. Whole thing ~150 ms. SW SH default to the
# virtual screen size from X (XWayland root). Exit 1 if /dev/uinput is not
# writable or KWin never listed the device. DEBUG=1 traces.
#
# Units: X Y are pixels of the SW x SH screen - the X screen, i.e. PHYSICAL
# pixels, the same space tablet-pen-pos.py reports in. The motion is sent as
# a fraction of the axis range, so it lands on the same physical spot even
# when the display is scaled (a 2560x1440 panel at 133% is a 1920x1080
# logical screen to KWin: workspace.cursorPos then reads 0.75x these X Y).
import ctypes as C
import fcntl
import os
import struct
import subprocess
import sys
import time

debug = os.environ.get("DEBUG") == "1"


# ── chunk: trace
def trace(msg):
    if debug:
        print(f"# {msg}", file=sys.stderr)


# ── chunk: _IO
# ioctl numbers (asm-generic encoding: dir<<30 | size<<16 | type<<8 | nr)
def _IO(nr):
    return (ord("U") << 8) | nr


# ── chunk: _IOW
def _IOW(nr, size):
    return (1 << 30) | (size << 16) | (ord("U") << 8) | nr


# ── chunk: _IOR
def _IOR(nr, size):
    return (2 << 30) | (size << 16) | (ord("U") << 8) | nr


# ── chunk: uinput-constants
UI_DEV_CREATE, UI_DEV_DESTROY = _IO(1), _IO(2)
UI_DEV_SETUP = _IOW(3, 92)      # struct uinput_setup: input_id(8) + name[80] + u32
UI_ABS_SETUP = _IOW(4, 28)      # struct uinput_abs_setup: u16 code, pad, input_absinfo(24)
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT = _IOW(100, 4), _IOW(101, 4), _IOW(103, 4)
UI_GET_SYSNAME = _IOR(44, 64)
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y, BTN_LEFT, BUS_VIRTUAL = 0, 1, 0x110, 6
ABS_RANGE = 65536               # libinput: px = value * screen / (max - min + 1)


# ── chunk: screen_size
def screen_size():
    x11 = C.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = C.c_void_p
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    x11.XCloseDisplay.argtypes = [C.c_void_p]
    x11.XDefaultScreen.argtypes = [C.c_void_p]
    x11.XDisplayWidth.argtypes = [C.c_void_p, C.c_int]
    x11.XDisplayHeight.argtypes = [C.c_void_p, C.c_int]
    os.environ.setdefault("DISPLAY", ":0")
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        sys.exit("no X display for the screen size - pass SW SH")
    screen = x11.XDefaultScreen(dpy)
    size = x11.XDisplayWidth(dpy, screen), x11.XDisplayHeight(dpy, screen)
    x11.XCloseDisplay(dpy)
    return size


# ── chunk: kwin_sees
def kwin_sees(event_node, timeout=1.5):
    """Poll KWin's input device list until event_node shows up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        out = subprocess.run(
            ["busctl", "--user", "get-property", "org.kde.KWin",
             "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDeviceManager",
             "devicesSysNames"], capture_output=True, text=True).stdout
        if f'"{event_node}"' in out:
            return True
        time.sleep(0.02)
    return False


# ── chunk: emit
def emit(fd, etype, code, value):
    os.write(fd, struct.pack("<qqHHi", 0, 0, etype, code, value))


# ── chunk: main
def main():
    if len(sys.argv) not in (3, 5):
        sys.exit("usage: tablet-pointer-warp.py X Y [SW SH]")
    x, y = int(sys.argv[1]), int(sys.argv[2])
    sw, sh = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) == 5 else screen_size()
    x, y = max(0, min(sw - 1, x)), max(0, min(sh - 1, y))
    try:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    except OSError as err:
        sys.exit(f"/dev/uinput: {err}")
    try:
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)     # a button makes udev call it a mouse
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
        for code in (ABS_X, ABS_Y):
            fcntl.ioctl(fd, UI_SET_ABSBIT, code)
            fcntl.ioctl(fd, UI_ABS_SETUP,
                        struct.pack("<H2x6i", code, 0, 0, ABS_RANGE - 1, 0, 0, 0))
        fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack(
            "<HHHH80sI", BUS_VIRTUAL, 0x1209, 0x7ac0, 1, b"tablet pointer warp", 0))
        fcntl.ioctl(fd, UI_DEV_CREATE)
        buf = bytearray(64)
        fcntl.ioctl(fd, UI_GET_SYSNAME, buf)
        sysname = buf.split(b"\0", 1)[0].decode()
        nodes = [n for n in os.listdir(f"/sys/devices/virtual/input/{sysname}")
                 if n.startswith("event")]
        trace(f"virtual device {sysname} -> {nodes}")
        if not nodes or not kwin_sees(nodes[0]):
            sys.exit("KWin did not pick the virtual pointer up")
        emit(fd, EV_ABS, ABS_X, int((x + 0.5) * ABS_RANGE / sw))
        emit(fd, EV_ABS, ABS_Y, int((y + 0.5) * ABS_RANGE / sh))
        emit(fd, EV_SYN, 0, 0)
        time.sleep(0.05)                               # let KWin process it before the device goes
        trace(f"warped to {x} {y} on {sw}x{sh}")
    finally:
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)


if __name__ == "__main__":
    main()
