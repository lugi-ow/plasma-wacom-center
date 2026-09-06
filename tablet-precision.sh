#!/bin/bash
# tablet-precision.sh - drawing-tablet "precision mode" toggle for KDE Plasma 6
# on Wayland. Part of plasma-wacom-center (MIT).
#
# Usage: tablet-precision.sh [toggle|resize|where]   (default: toggle)
#
# toggle ON:  maps the pen to a TABLET-SHAPED rectangle (width = SCALE of the
#      screen, height follows the tablet's own aspect ratio, so there is no
#      stretch inside the area), placed so the cursor DOES NOT MOVE:
#      rect = norm * (screen - rect), the rule Wacom's Windows driver uses -
#      the area drifts toward a border slower than the cursor and can never
#      leave the screen. Pen position comes from tablet-pen-pos.py; the mouse
#      cursor is the fallback. A click-through overlay dims everything
#      OUTSIDE the mapped rectangle (tablet-overlay.py + .qml).
# toggle OFF: restores the mapping that was active before ON (not blindly
#      full screen). Toggle state = the state file, not the area value.
# resize: while ON, recompute the area with the current SCALE from the conf
#      (the ring size control calls this); no-op when OFF.
# where:  print "X Y W H DIM SW SH" - the rectangle a toggle ON would map right now,
#      nothing changed (tablet-hover.py draws the ghost from it).
#
# Config: ~/.config/tabprec.conf - SCALE (0.05-0.80 of screen width), DIM
# (0-0.8). Wacom Center and tablet-precision-size.sh write it. Silent by
# design: the overlay is the feedback; only errors notify.
#
# Devices are found by capability (tabletTool property), not by name, and
# looked up on every run - Bluetooth reconnects renumber the event nodes.
#
# Assumption: the base mapping is the default full-tablet stretch. If you set
# a letterboxed mapping on the Display page, the cursor-stationary math needs
# the inputArea transform added.
#
# Bind the toggle to a pad button through chords built from F-KEYS AND
# MODIFIERS ONLY: KWin's rebind injector resolves letters through the active
# keyboard layout, so letter chords die silently under any non-Latin layout.

export LC_ALL=C.UTF-8    # decimal point regardless of locale; UTF-8 keeps Qt quiet
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/tabprec.conf"
[ -f "$CONF" ] && . "$CONF"
SCALE=${SCALE:-0.7071}
DIM=${DIM:-0.35}
MODE=${1:-toggle}
KW=org.kde.KWin
MGR=/org/kde/KWin/InputDevice
IF=org.kde.KWin.InputDevice
SCR=org.kde.kwin.Scripting
RD="${XDG_RUNTIME_DIR:-/tmp}/tabprec"
mkdir -p "$RD"
DIR=$(cd "$(dirname "$0")" && pwd)
STATE="$RD/saved-area"

note() { notify-send -a Tablet -i input-tablet -t 1800 "Precision mode" "$1" 2>/dev/null; }
kload() { qdbus6 $KW /Scripting $SCR.unloadScript "$2" >/dev/null 2>&1
          qdbus6 $KW /Scripting $SCR.loadScript "$1" "$2" >/dev/null &&
          qdbus6 $KW /Scripting $SCR.start; }
kunload() { qdbus6 $KW /Scripting $SCR.unloadScript "$1" >/dev/null 2>&1; }

pen=""
for n in $(busctl --user get-property $KW $MGR $KW.InputDeviceManager devicesSysNames 2>/dev/null \
           | tr -d '"' | cut -d' ' -f3-); do
    tool=$(busctl --user get-property $KW $MGR/$n $IF tabletTool 2>/dev/null)
    case "$tool" in *true*) pen=$n; break;; esac
done
if [ -z "$pen" ]; then
    note "No tablet pen found (tablet asleep?)"
    exit 1
fi

compute_area() {  # sets W H X Y (px) and FX FY FW FH (fractions) for the pen's position
    if POS=$(python3 "$DIR/tablet-pen-pos.py" 2>/dev/null); then
        set -- $POS
    else
        NON=$(date +%s%N)
        printf 'print("TPREC %s " + workspace.cursorPos.x + " " + workspace.cursorPos.y + " " + workspace.virtualScreenSize.width + " " + workspace.virtualScreenSize.height);\n' "$NON" > "$RD/probe.js"
        kload "$RD/probe.js" tabprec_probe
        line=""
        for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
            line=$(journalctl --user -u plasma-kwin_wayland.service -n 200 --no-pager 2>/dev/null | grep "TPREC $NON" | tail -1)
            [ -n "$line" ] && break
            sleep 0.2
        done
        kunload tabprec_probe
        if [ -z "$line" ]; then
            note "Could not read a pointer position"
            return 1
        fi
        set -- ${line#*"TPREC $NON"}
    fi
    CX=$1 CY=$2 SW=$3 SH=$4
    TABSIZE=$(busctl --user get-property $KW $MGR/$pen $IF size 2>/dev/null | cut -d' ' -f2-)
    read -r W H X Y FX FY FW FH <<EOF
$(awk -v s="$SCALE" -v cx="$CX" -v cy="$CY" -v sw="$SW" -v sh="$SH" -v tab="${TABSIZE:-16 10}" 'BEGIN{
    split(tab, t, " "); aspect = (t[2] > 0) ? t[1] / t[2] : 1.6;
    if (s > 0.8) s = 0.8; if (s < 0.05) s = 0.05;
    w = int(sw * s + 0.5); h = int(w / aspect + 0.5);
    if (h > sh) { h = sh; w = int(h * aspect + 0.5) }
    x = int(cx / sw * (sw - w) + 0.5); y = int(cy / sh * (sh - h) + 0.5);
    printf "%d %d %d %d %.6f %.6f %.6f %.6f", w,h,x,y, x/sw,y/sh,w/sw,h/sh}')
EOF
}

apply_area() {  # compute + set the precision mapping and (re)spawn the overlay
    compute_area || return 1
    busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "$FX" "$FY" "$FW" "$FH" || { note "Mapping change failed"; return 1; }
    [ -f "$RD/overlay.pid" ] && kill "$(cat "$RD/overlay.pid")" 2>/dev/null
    nohup python3 "$DIR/tablet-overlay.py" "$X" "$Y" "$W" "$H" "$DIM" > "$RD/overlay.log" 2>&1 &
    echo $! > "$RD/overlay.pid"
}

case "$MODE" in
resize)
    [ -f "$STATE" ] && apply_area
    ;;
where)
    compute_area && echo "$X $Y $W $H $DIM $SW $SH"
    ;;
*)
    if [ ! -f "$STATE" ]; then
        CUR=$(busctl --user get-property $KW $MGR/$pen $IF outputArea | cut -d' ' -f2-)
        if apply_area; then
            echo "$CUR" > "$STATE"
        fi
    else
        set -- $(cat "$STATE")
        busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "${1:-0}" "${2:-0}" "${3:-1}" "${4:-1}"
        rm -f "$STATE"
        if [ -f "$RD/overlay.pid" ]; then
            kill "$(cat "$RD/overlay.pid")" 2>/dev/null
            rm -f "$RD/overlay.pid"
        fi
    fi
    ;;
esac
