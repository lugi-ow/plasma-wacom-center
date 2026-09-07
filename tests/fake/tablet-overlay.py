#!/usr/bin/env python3
# Test double for tablet-overlay.py: no GUI. Logs "SPAWN <args>" and every
# geometry line it receives (stdin with --follow, the named pipe with --fifo)
# to $FAKE_LOG, "EOF" when stdin closes. Runs until killed in --fifo mode.
import os
import sys

args = sys.argv[1:]
log = os.environ.get("FAKE_LOG", "/dev/stderr")
fifo = args[args.index("--fifo") + 1] if "--fifo" in args else None


def note(text):
    with open(log, "a") as f:
        f.write(text if text.endswith("\n") else text + "\n")


note("SPAWN " + " ".join(args))
if fifo:
    if not os.path.exists(fifo):
        os.mkfifo(fifo, 0o600)
    fd = os.open(fifo, os.O_RDWR)          # blocking, never EOF: like the real one
else:
    fd = 0
while True:
    chunk = os.read(fd, 4096)
    if not chunk:
        note("EOF")
        break
    note(chunk.decode())
