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
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\n")

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
for f in FAKE.iterdir():
    f.chmod(0o755)
hover.DIR = FAKE

PEN = [(0.5, 0.5)]
hover.pen_open = lambda: os.open("/dev/null", os.O_RDONLY)
hover.pen_norm = lambda fd: PEN[0]
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
        if not hover.watch(hover.read_conf(), follower):
            time.sleep(0.2)


threading.Thread(target=daemon, daemon=True).start()
time.sleep(0.3)


def report(touch=0, press=0):
    r = bytearray(300)
    r[0], r[283], r[282] = 0x80, touch, press
    os.write(writer, bytes(r))
    time.sleep(0.05)                      # hidraw never merges reports; a pipe would


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
n = len(lines)
report(touch=0x80, press=0)               # key released, finger still resting
PEN[0] = (0.2, 0.2)
time.sleep(1.4)
check("C resting 1.4 s after the press: no new relocation, marker not refreshed",
      len(lines) == n and MARK.exists() and MARK.stat().st_mtime <= t_press + 0.05)
report(touch=0)
time.sleep(0.25)
check("C lift after a press: no snap back, marker still there", len(lines) == n and MARK.exists())
check("C confirm: no resume (the toggle maps the new area); suspend 2, resume 1",
      ghost().count("CALL suspend") == 2 and ghost().count("CALL resume") == 1)
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

# --- E: HOLD from the conf, picked up without a restart ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=1.2\n")
time.sleep(2.6)                            # the 2 s rescan reloads it
n = len(lines)
report(touch=0x80)
time.sleep(0.9)
check("E HOLD=1.2 reloaded: nothing 0.9 s into the touch", not MARK.exists() and len(lines) == n)
time.sleep(0.5)
check("E HOLD=1.2 reloaded: relocating 1.4 s into the touch", MARK.exists() and len(lines) == n + 2)
report(touch=0)
time.sleep(0.25)
check("E lift snaps home", lines[-2:] == [HOME, "solid"] and not MARK.exists())

# --- G: the conf edited while the finger already rests (a ring tick, a Center slider): the hold still ends in a drag ---
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=2.5\n")
time.sleep(2.6)
n = len(lines)
report(touch=0x80)
time.sleep(0.3)
CONF.write_text("SCALE=0.31\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=2.5\n")   # a ring tick mid-rest; a rescan sees it before the hold ends
time.sleep(2.6)
check("G conf edited mid-rest: the drag still starts", MARK.exists() and len(lines) == n + 2 and lines[-2] == "waiting")
report(touch=0)
time.sleep(0.25)
check("G lift snaps home", lines[-2:] == [HOME, "solid"] and not MARK.exists())
CONF.write_text("SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nHOLD=0.6\n")
time.sleep(2.6)

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
