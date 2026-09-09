#!/usr/bin/env python3
# Offline harness for tablet-hover.py: a named pipe plays the pad's hidraw
# node (Bluetooth layout: report 0x80, touch byte 283, press byte 282), the
# pen is faked, the toggle and both overlays are fakes in a scratch DIR, the
# live overlay's pipe is read by a thread. No GUI, no real devices.
# Usage: test_hover.py <scratch dir> <path to tablet-hover.py>
import importlib.util
import os
import select
import shutil
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRATCH = Path(sys.argv[1]) / "hover-test"
SRC = Path(sys.argv[2])
shutil.rmtree(SCRATCH, ignore_errors=True)
RD, CONFD, FAKE = SCRATCH / "rd", SCRATCH / "conf", SCRATCH / "fake"
for d in (RD / "tabprec", CONFD, FAKE):
    d.mkdir(parents=True)
os.environ["XDG_RUNTIME_DIR"] = str(RD)
os.environ["XDG_CONFIG_HOME"] = str(CONFD)
CONF = CONFD / "tabprec.conf"
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")   # the rig's timings assume these, not the defaults

spec = importlib.util.spec_from_file_location("hover", SRC)
hover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hover)
assert hover.RD == RD / "tabprec", hover.RD

# fakes the daemon runs from DIR: the toggle's "where" and the ghost overlay
GHOST_LOG = SCRATCH / "ghost.log"
os.environ["FAKE_LOG"] = str(GHOST_LOG)
(FAKE / "tablet-precision.sh").write_text(
    "#!/bin/bash\ncase \"$1\" in where) echo '909 475 742 490 0.10 2560 1440';; "
    "*) echo \"CALL $1\" >> \"$FAKE_LOG\";; esac\n")
shutil.copy(HERE / "fake" / "tablet-overlay.py", FAKE / "tablet-overlay.py")
shutil.copy(SRC.parent / "tablet-pointer-warp.py", FAKE / "tablet-pointer-warp.py")   # real Warper loads it (K)
for f in FAKE.iterdir():
    f.chmod(0o755)
hover.DIR = FAKE

PEN = [(0.5, 0.5)]
hover.pen_open = lambda: os.open("/dev/null", os.O_RDONLY)
hover.pen_norm = lambda fd: PEN[0]
WARPS = []                                # (pen position, mapped) per warp the daemon asked for
EVENTS = []                               # warps and chords in daemon order: the warp must precede the chord


class FakeWarper:                         # never the real one: it would move the desktop's mouse
    def __init__(self):
        self.held = {}

    def ensure(self):
        pass

    def warp(self, mapped, why="press"):
        WARPS.append((PEN[0], mapped))
        EVENTS.append(("warp", PEN[0]))

    def chord_down(self, tag, text, label):   # records what the daemon asked; validation is the real Warper's
        if tag not in self.held:
            self.held[tag] = text
            EVENTS.append(("down", tag, text))

    def chord_up(self, tag):
        if self.held.pop(tag, None) is not None:
            EVENTS.append(("up", tag))

    def release_all(self):
        for tag in list(self.held):
            self.chord_up(tag)


PAD = SCRATCH / "pad.fifo"
os.mkfifo(PAD)
hover.wacom_nodes = lambda: [(str(PAD), "bt", "0360")]

# the live overlay's pipe, read like the real overlay does (RDWR, no EOF)
FIFO = hover.FIFO
os.mkfifo(FIFO)
ffd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
lines = []
reading = True


def reader():
    buf = b""
    while reading:
        ready, _, _ = select.select([ffd], [], [], 0.05)
        if not ready:
            continue
        try:
            buf += os.read(ffd, 4096)
        except BlockingIOError:
            continue
        *done, buf = buf.split(b"\n")
        lines.extend(l.decode().strip() for l in done)


threading.Thread(target=reader, daemon=True).start()

writer = os.open(PAD, os.O_RDWR)          # a writer must exist before the daemon's blocking open
follower = hover.Follower()


def daemon():
    while True:
        if not hover.watch(hover.read_conf(), follower, FakeWarper()):
            time.sleep(0.2)


threading.Thread(target=daemon, daemon=True).start()
time.sleep(0.3)


def report(touch=0, press=0):
    r = bytearray(300)
    r[0], r[283], r[282] = 0x80, touch, press
    os.write(writer, bytes(r))
    time.sleep(0.05)                      # hidraw never merges reports; a pipe would


def poke():
    """A conf edit reaches the daemon through the control pipe, not a poll."""
    for _ in range(100):
        if hover.CTL.exists():
            break
        time.sleep(0.02)
    fd = os.open(hover.CTL, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, b"reload\n")
    os.close(fd)
    time.sleep(0.15)                      # the select loop wakes at once; margin for the reload


fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


STATE, AREA, MARK = hover.STATE, hover.AREA, hover.MARK
HOME = "909 475 742 490"
ghost = lambda: GHOST_LOG.read_text() if GHOST_LOG.exists() else ""

# --- A: precision OFF: the ghost, in the waiting look of the mode itself ---
report(touch=0x80)
time.sleep(0.25)
check("A ghost spawned 0.25 s after the touch, full dim, --waiting",
      "SPAWN 909 475 742 490 0.10 --waiting --follow\n" in ghost())
ghost_pid = follower.proc.pid if follower.proc else None
PEN[0] = (0.25, 0.25)
time.sleep(0.15)
check("A ghost follows the pen: 455 238 742 490", "455 238 742 490" in ghost())
report(touch=0)
time.sleep(0.25)
check("A lift ends the ghost process", ghost_pid and not os.path.exists(f"/proc/{ghost_pid}") and not follower.up)
check("A no marker, no pipe lines", not MARK.exists() and not lines)
check("A the finger landing warped once, at the touch, plain (precision off)", WARPS == [((0.5, 0.5), False)])

# --- W: a finger landing on ANY key warps the mouse onto the pen, the press again ---
PEN[0] = (0.25, 0.25)
report(touch=0x03)                         # keys 1+2 together, away from the precision key
time.sleep(0.05)
check("W finger lands on keys 1+2: one warp, plain", WARPS[1:] == [((0.25, 0.25), False)])
PEN[0] = (0.3, 0.3)
report(touch=0x03, press=0x03)
report(touch=0x03, press=0)
report(touch=0)
time.sleep(0.1)
check("W the press warps again at the pen's new spot; the release and lift do not", WARPS[2:] == [((0.3, 0.3), False)])
check("W keys 1+2: no ghost, no marker, nothing else", ghost().count("SPAWN") == 1 and not MARK.exists() and not lines)
report(press=0x03)                         # a press the touch sense never saw: still one warp
report(press=0)
time.sleep(0.1)
check("W a press without a touch warps too", len(WARPS) == 4)

# --- K: CHORD_<n> from the conf: the daemon presses the chord AFTER the warp ---
wspec = importlib.util.spec_from_file_location("warpmod", FAKE / "tablet-pointer-warp.py")
warpmod = importlib.util.module_from_spec(wspec)
wspec.loader.exec_module(warpmod)
check("K parse: Meta+Shift+F8 -> Shift, Meta, F8 (KWin's modifier order)",
      warpmod.parse_chord("Meta+Shift+F8") == [42, 125, 66])
check("K parse: case-blind, Super = Meta, the F13 block", warpmod.parse_chord("super+f13") == [125, 183])
check("K parse: a letter or an empty chord is refused",
      warpmod.parse_chord("Q+F1") is None and warpmod.parse_chord("") is None)
check("K parse: modifier-only refused for a press chord, two F-keys too",
      warpmod.parse_chord("Meta") is None and warpmod.parse_chord("Ctrl+Shift") is None
      and warpmod.parse_chord("F1+F2") is None)
check("K parse: touch chords allow bare modifiers, in KWin's order",
      warpmod.parse_chord("Ctrl", False) == [29] and warpmod.parse_chord("Ctrl+Shift", False) == [42, 29])
check("K parse: Meta alone refused even for a touch (the launcher tap)",
      warpmod.parse_chord("Meta", False) is None and warpmod.parse_chord("", False) is None)
rw = hover.Warper()                        # the real one: mod loads from FAKE, fd stays None - no device touched
rw.chord_down(("press", 2), "Meta+Shift+F8", "key 2")
rw.chord_down(("press", 3), "Q+F1", "key 3")
check("K real Warper without a device: nothing held, no crash", rw.held == {})
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\nCHORD_2=Meta+Shift+F8\nCHORD_3=Q+F1\n")
poke()
n_ev = len(EVENTS)
PEN[0] = (0.4, 0.6)
report(press=0x06)                         # keys 2+3 down in one report, no touch first
time.sleep(0.05)
check("K press: one warp first, then the chords in key order",
      EVENTS[n_ev:] == [("warp", (0.4, 0.6)), ("down", ("press", 2), "Meta+Shift+F8"),
                        ("down", ("press", 3), "Q+F1")])
report(press=0x04)                         # key 2 up, key 3 still down
time.sleep(0.05)
check("K key 2's release lifts its chord only", EVENTS[n_ev + 3:] == [("up", ("press", 2))])
report(press=0)
time.sleep(0.05)
check("K key 3's release lifts the rest", EVENTS[n_ev + 4:] == [("up", ("press", 3))])
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\nWARP=0\nCHORD_2=Meta+Shift+F8\n")
poke()
n_ev = len(EVENTS)
report(press=0x02)
report(press=0)
time.sleep(0.05)
check("K WARP=0: no warp, the chord still fires",
      EVENTS[n_ev:] == [("down", ("press", 2), "Meta+Shift+F8"), ("up", ("press", 2))])

# --- T: TOUCH_CHORD_<n>: held after the delay, released at the lift ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.3\nLONG=1.0\n"
                "TOUCH_CHORD_2=Ctrl\nTOUCH_CHORD_3=Shift\nCHORD_3=Meta+Shift+F5\n")
poke()
n_ev = len(EVENTS)
PEN[0] = (0.6, 0.4)
report(touch=0x02)                         # finger lands on key 2: warp now, the chord only after HOLD
time.sleep(0.15)
check("T no touch chord before the delay (0.15 s into 0.3)",
      EVENTS[n_ev:] == [("warp", (0.6, 0.4))])
PEN[0] = (0.7, 0.5)                        # the pen moves during the delay
time.sleep(0.3)
check("T engaged after the delay: a FRESH warp, then the chord held",
      EVENTS[n_ev + 1:] == [("warp", (0.7, 0.5)), ("down", ("touch", 2), "Ctrl")])
report(touch=0)
time.sleep(0.05)
check("T lift releases the touch chord", EVENTS[n_ev + 3:] == [("up", ("touch", 2))])
n_ev = len(EVENTS)
report(touch=0x02)                         # a press before the delay wins: no touch chord this contact
report(touch=0x02, press=0x02)
report(touch=0x02, press=0)
report(touch=0)
time.sleep(0.5)                            # well past the delay: nothing may engage late either
check("T press before the delay: warps only, no chord this contact",
      [e for e in EVENTS[n_ev:] if e[0] != "warp"] == [])
n_ev = len(EVENTS)
report(touch=0x04)                         # key 3: engage, then press on top of the held chord
time.sleep(0.45)
report(touch=0x04, press=0x04)
time.sleep(0.05)
check("T press after the engage: the touch chord stays held, the press chord joins",
      EVENTS[n_ev + 1:] == [("warp", (0.7, 0.5)), ("down", ("touch", 3), "Shift"),
                            ("warp", (0.7, 0.5)), ("down", ("press", 3), "Meta+Shift+F5")])
report(touch=0x04, press=0)
report(touch=0)
time.sleep(0.05)
check("T releases mirror their triggers, the press first",
      EVENTS[n_ev + 5:] == [("up", ("press", 3)), ("up", ("touch", 3))])
n_ev = len(EVENTS)
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=1.0\nLONG=1.0\n"
                "TOUCH_CHORD_2=Ctrl\nTOUCH_HOLD_2=0.1\n")
poke()
report(touch=0x02)                         # key 2's own register (0.1) beats the HOLD fallback (1.0)
time.sleep(0.35)
check("T per-key register: TOUCH_HOLD_2 overrides HOLD",
      ("down", ("touch", 2), "Ctrl") in EVENTS[n_ev:])
report(touch=0)
time.sleep(0.05)
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")
poke()

# --- B: precision ON: hold -> relocation, lift -> snap back ---
STATE.write_text("0 0 1 1\n")
AREA.write_text("909 475 742 490 0.10 2560 1440 0.355078 0.329861 0.289844 0.340278\n")
PEN[0] = (0.5, 0.5)
report(touch=0x80)
time.sleep(0.35)
check("B nothing 0.35 s into the touch (hold is 0.6)", not MARK.exists() and not lines and "CALL" not in ghost())
time.sleep(0.6)
check("B marker fresh after the hold", MARK.exists() and time.time() - MARK.stat().st_mtime < 0.5)
check("B waiting border first, then the overlay at the aim: 909 475 742 490", lines == ["waiting", HOME])
check("B suspend called once (cursor freed)", ghost().count("CALL suspend") == 1 and "CALL resume" not in ghost())
PEN[0] = (0.1, 0.9)
time.sleep(0.15)
check("B follows the pen: 182 855 742 490", lines[-1] == "182 855 742 490")
n = len(lines)
report(touch=0)
time.sleep(0.25)
check("B lift: home line 909 475 742 490, then solid", len(lines) == n + 2 and lines[-2:] == [HOME, "solid"])
check("B lift: marker removed", not MARK.exists())
check("B lift: resume called (old area mapped again)", ghost().count("CALL resume") == 1)
check("B no ghost while ON", ghost().count("SPAWN") == 1)

# --- C: hold -> press confirms: border solid where it is, marker kept, no snap back, the resting finger after it is ignored ---
PEN[0] = (0.5, 0.5)
report(touch=0x80)
time.sleep(0.9)
check("C relocating again: waiting, then the aim", MARK.exists() and lines[-2:] == ["waiting", HOME])
PEN[0] = (0.9, 0.1)
time.sleep(0.15)
check("C aimed: 1636 95 742 490", lines[-1] == "1636 95 742 490")
n = len(lines)
t_press = time.time()
report(touch=0x80, press=0x80)
time.sleep(0.25)
check("C press: marker kept for the toggle", MARK.exists())
check("C press: border solid, no snap back", lines[n:] == ["solid"])
check("C press mid-drag warps to the plain position (base mapping while aiming)", WARPS[-1] == ((0.9, 0.1), False))
n = len(lines)
report(touch=0x80, press=0)               # key released, finger still resting
PEN[0] = (0.2, 0.2)
time.sleep(1.4)
check("C resting 1.4 s after the press: no new relocation, marker not refreshed",
      len(lines) == n and MARK.exists() and MARK.stat().st_mtime <= t_press + 0.05)
report(touch=0)
time.sleep(0.25)
check("C lift after a press: no snap back, marker still there", len(lines) == n and MARK.exists())
check("C confirm: no resume (the toggle maps the new area), no long press; suspend 2, resume 1",
      ghost().count("CALL suspend") == 2 and ghost().count("CALL resume") == 1
      and "CALL toggle" not in ghost())
MARK.unlink()                              # the toggle would have consumed it

# --- D: a quick press while ON (toggle off) never relocates ---
n = len(lines)
report(touch=0x80)
report(touch=0x80, press=0x80)
time.sleep(0.1)
report(touch=0x80)
report(touch=0)
time.sleep(0.9)
check("D quick press: no marker, no pipe lines, no suspend", not MARK.exists() and len(lines) == n
      and ghost().count("CALL suspend") == 2)
check("D quick press while ON warps through the area (mapped)", WARPS[-1] == ((0.2, 0.2), True))

# --- E: HOLD from the conf, picked up through the control pipe ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=1.2\nWARP=0\n")
poke()
n_warps = len(WARPS)
report(press=0x03)
report(press=0)
time.sleep(0.1)
check("E WARP=0 reloaded: a press warps nothing", len(WARPS) == n_warps)
n = len(lines)
report(touch=0x80)
time.sleep(0.9)
check("E HOLD=1.2 reloaded: nothing 0.9 s into the touch", not MARK.exists() and len(lines) == n)
time.sleep(0.5)
check("E HOLD=1.2 reloaded: relocating 1.4 s into the touch", MARK.exists() and len(lines) == n + 2)
report(touch=0)
time.sleep(0.25)
check("E lift snaps home", lines[-2:] == [HOME, "solid"] and not MARK.exists())

# --- G: the conf reloaded while the finger already rests: the hold still ends in a drag ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=2.5\n")
poke()
n = len(lines)
report(touch=0x80)
time.sleep(0.3)
CONF.write_text("SCALE=0.31\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=2.5\n")   # a poke mid-rest reloads before the hold ends
poke()
time.sleep(2.6)
check("G conf reloaded mid-rest: the drag still starts", MARK.exists() and len(lines) == n + 2 and lines[-2] == "waiting")
report(touch=0)
time.sleep(0.25)
check("G lift snaps home", lines[-2:] == [HOME, "solid"] and not MARK.exists())
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")
poke()

# --- H: no floor on HOLD, and the LONG PRESS out of precision mode ---
calls = lambda: ghost().count("CALL toggle")
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0\nLONG=1.0\n")
poke()
n = len(lines)
report(touch=0x80)
time.sleep(0.1)
check("H HOLD=0: the drag starts at the first touch report", MARK.exists() and len(lines) == n + 2)
report(touch=0)
time.sleep(0.25)
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")
poke()
report(touch=0x80)
time.sleep(0.9)
check("H drag on, no toggle call so far", MARK.exists() and calls() == 0)
report(touch=0x80, press=0x80)            # the press lands the area (KWin's toggle, not modelled) and stays down
time.sleep(0.5)
check("H pressed 0.5 s: no exit yet", calls() == 0)
time.sleep(0.7)
check("H pressed 1.2 s: the daemon toggles precision mode off, once", calls() == 1)
report(touch=0x80, press=0)               # released, finger resting
time.sleep(1.3)
check("H after the release: no further toggle", calls() == 1)
report(touch=0)
time.sleep(0.25)
MARK.unlink(missing_ok=True)
report(touch=0x80)                        # a short press after a drag: a move, no exit
time.sleep(0.9)
report(touch=0x80, press=0x80)
time.sleep(0.3)
report(touch=0x80, press=0)
time.sleep(1.2)
check("H short press after a drag: no exit", calls() == 1)
report(touch=0)
time.sleep(0.25)
MARK.unlink(missing_ok=True)
report(touch=0x80)                        # a press before any drag (the toggle itself switches off): never armed
report(touch=0x80, press=0x80)
time.sleep(1.4)
check("H press before a drag, held 1.4 s: not armed", calls() == 1 and not MARK.exists())
report(touch=0)
time.sleep(0.25)
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=0\n")
poke()
report(touch=0x80)
time.sleep(0.9)
report(touch=0x80, press=0x80)
time.sleep(1.4)
check("H LONG=0: a press held 1.4 s after a drag does not exit", calls() == 1)
report(touch=0)
time.sleep(0.25)
MARK.unlink(missing_ok=True)
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")
poke()

# --- M: the precision key's touch and press belong to the mode, never to a chord ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.2\nLONG=1.0\n"
                "TOUCH_CHORD_8=Alt\nCHORD_8=Meta+Shift+F6\n")
poke()
n_ev = len(EVENTS)
report(touch=0x80)                         # resting on the precision key: the drag's, not a chord's
time.sleep(0.5)
report(touch=0x80, press=0x80)             # pressing it: the toggle's, not a chord's
time.sleep(0.05)
report(touch=0)
time.sleep(0.25)
check("M no chord ever for the mask key, warps only",
      [e for e in EVENTS[n_ev:] if e[0] != "warp"] == [])
MARK.unlink(missing_ok=True)               # the confirmed press left it for the (absent) toggle
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\nLONG=1.0\n")
poke()

# --- F: no live overlay reading the pipe -> the hold does nothing ---
reading = False
time.sleep(0.1)
os.close(ffd)
report(touch=0x80)
time.sleep(0.8)
check("F no overlay: no marker", not MARK.exists())
report(touch=0)
time.sleep(0.2)

print(f"failures: {fails}")
os.close(writer)
sys.exit(1 if fails else 0)
