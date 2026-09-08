#!/bin/bash
# tablet-pie.sh [MENU] - open a Kando pie menu UNDER THE PEN (default: Krita).
# Part of plasma-wacom-center (MIT).
#
# Kando asks KWin where the pointer is, and KWin answers with the MOUSE - the
# pen's tablet cursor is a separate thing - so a pie opened from a pad key
# lands wherever the mouse was last left. Fix: read the pen's screen position
# (tablet-pen-pos.py, kernel evdev), warp the mouse there (tablet-pointer-
# warp.py, a short-lived virtual mouse on /dev/uinput, no root), then open
# the menu. No pen position (tablet asleep, udev rule missing) -> plain
# kando --menu at the mouse, as before.
#
# --mapped: in precision mode the pen is mapped to a small rectangle, so the
# pen's place on the TABLET is not its place on the screen - without the flag
# the menu jumped to the matching spot of the whole screen (the area centre
# opened it at the screen centre).
#
# install.sh binds Meta+Shift+F11 -> net.local.tabpie.desktop -> this file;
# put that chord on a pad button (F-keys + modifiers only, see the README).
# ── chunk: warp-then-open
DIR=$(cd "$(dirname "$0")" && pwd)
MENU=${1:-Krita}
if POS=$(python3 "$DIR/tablet-pen-pos.py" --mapped 2>/dev/null); then
    set -- $POS
    python3 "$DIR/tablet-pointer-warp.py" "$1" "$2" "$3" "$4" 2>/dev/null
fi
exec kando --menu "$MENU"
