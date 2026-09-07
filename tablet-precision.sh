#!/bin/bash
# tablet-precision.sh - drawing-tablet "precision mode" toggle for KDE Plasma 6
# on Wayland. Part of plasma-wacom-center (MIT).
#
# Usage: tablet-precision.sh [toggle|resize|where|suspend|resume]   (default: toggle)
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
# toggle while ON with a FRESH relocate marker ($RD/relocate, under 3 s
#      old): a MOVE, not OFF - re-map at the pen's current position, the
#      saved base mapping stays. tablet-hover.py keeps the marker fresh while
#      it drags the live overlay after the pen (finger held on the key), so
#      the press that ends the drag lands the area where the overlay is.
# resize: while ON, the area takes the SCALE from the conf around ITS OWN
#      CENTRE, clamped to the screen (the ring size control calls this): the
#      area does not move, the base mapping saved at ON is kept. The cursor
#      scales with the area - the pen's place IN the area is what stays put,
#      not its place on the screen. No-op when OFF.
# where:  print "X Y W H DIM SW SH" - the rectangle a toggle ON would map right now,
#      nothing changed (tablet-hover.py draws the ghost from it).
# suspend / resume: while ON, put the base mapping back for the moment /
#      re-map the area on record - tablet-hover.py brackets a relocation with
#      them, so the cursor roams the whole screen while the area is aimed and
#      returns to the old area on a cancel (a confirm re-maps through toggle).
#
# The overlay is spawned once per ON with --fifo $RD/overlay.fifo and then
# MOVED through that pipe on a resize or a move (no respawn, no flicker);
# the geometry of the current mapping is kept in $RD/area for the daemon.
# Runs are serialized with flock on $RD/lock: two runs never interleave (a
# long press on the pad key = KWin's MOVE toggle, then the daemon's OFF).
# The conf is read after the lock and a resize that finds its width already
# on screen does nothing, so a burst of ring ticks (one process each, every
# 5 degrees) collapses into two resizes instead of a staircase; the pen's
# sysname is cached in $RD/pen (one D-Bus call to confirm it per run, not
# one per device).
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

# ── chunk: config-and-paths
export LC_ALL=C.UTF-8    # decimal point regardless of locale; UTF-8 keeps Qt quiet
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/tabprec.conf"
MODE=${1:-toggle}
KW=org.kde.KWin
MGR=/org/kde/KWin/InputDevice
IF=org.kde.KWin.InputDevice
SCR=org.kde.kwin.Scripting
RD="${XDG_RUNTIME_DIR:-/tmp}/tabprec"
mkdir -p "$RD"
exec 9>"$RD/lock"; flock -w 5 9 || exit 1   # one run at a time: a long press makes KWin's MOVE toggle and the daemon's OFF toggle land in a row
[ -f "$CONF" ] && . "$CONF"   # read AFTER the lock: a ring tick queued behind another applies the newest SCALE, not the one it was born with
SCALE=${SCALE:-0.36}
DIM=${DIM:-0.10}
DIR=$(cd "$(dirname "$0")" && pwd)
STATE="$RD/saved-area"
FIFO="$RD/overlay.fifo"    # the live overlay reads "X Y W H DIM" lines from it
AREA="$RD/area"            # "X Y W H DIM SW SH FX FY FW FH" of the current mapping (tablet-hover.py relocates from it)
MARK="$RD/relocate"        # fresh while tablet-hover.py drags the overlay: the next press moves instead of switching off
PEN_CACHE="$RD/pen"        # the pen's KWin sysname from the last walk over the device list: one D-Bus call confirms it
pen=""

# ── chunk: note
note() { notify-send -a Tablet -i input-tablet -t 1800 "Precision mode" "$1" 2>/dev/null; }
# ── chunk: kload
kload() { qdbus6 $KW /Scripting $SCR.unloadScript "$2" >/dev/null 2>&1
          qdbus6 $KW /Scripting $SCR.loadScript "$1" "$2" >/dev/null &&
          qdbus6 $KW /Scripting $SCR.start; }
# ── chunk: kunload
kunload() { qdbus6 $KW /Scripting $SCR.unloadScript "$1" >/dev/null 2>&1; }

# ── chunk: find_pen
find_pen() {  # the pen's KWin sysname into $pen: the cached one when KWin still calls it a tablet tool (one D-Bus call), else a walk over every device; exits 1 when there is none
    [ -n "$pen" ] && return 0
    pen=$(cat "$PEN_CACHE" 2>/dev/null)
    if [ -n "$pen" ]; then
        case "$(busctl --user get-property $KW $MGR/$pen $IF tabletTool 2>/dev/null)" in *true*) return 0;; esac
        pen=""
    fi
    for n in $(busctl --user get-property $KW $MGR $KW.InputDeviceManager devicesSysNames 2>/dev/null \
               | tr -d '"' | cut -d' ' -f3-); do
        tool=$(busctl --user get-property $KW $MGR/$n $IF tabletTool 2>/dev/null)
        case "$tool" in *true*) pen=$n; break;; esac
    done
    if [ -z "$pen" ]; then
        note "No tablet pen found (tablet asleep?)"
        exit 1
    fi
    echo "$pen" > "$PEN_CACHE"
}

# ── chunk: area_math
area_math() {  # W H X Y (px) and FX FY FW FH (fractions) for SCALE and the tablet's aspect. $1 = "pen": placed around the pen at $2 $3 so the cursor stays put; "centre": centred on $2 $3, clamped to the screen. $4 $5 = the screen size.
    find_pen
    CX=$2 CY=$3 SW=$4 SH=$5
    TABSIZE=$(busctl --user get-property $KW $MGR/$pen $IF size 2>/dev/null | cut -d' ' -f2-)
    read -r W H X Y FX FY FW FH <<EOF
$(awk -v mode="$1" -v s="$SCALE" -v cx="$CX" -v cy="$CY" -v sw="$SW" -v sh="$SH" -v tab="${TABSIZE:-16 10}" 'BEGIN{
    split(tab, t, " "); aspect = (t[2] > 0) ? t[1] / t[2] : 1.6;
    if (s > 0.8) s = 0.8; if (s < 0.05) s = 0.05;
    w = int(sw * s + 0.5); h = int(w / aspect + 0.5);
    if (h > sh) { h = sh; w = int(h * aspect + 0.5) }
    if (mode == "centre") {
        x = int(cx - w / 2 + 0.5); y = int(cy - h / 2 + 0.5);
        if (x > sw - w) x = sw - w; if (y > sh - h) y = sh - h;
        if (x < 0) x = 0; if (y < 0) y = 0;
    } else { x = int(cx / sw * (sw - w) + 0.5); y = int(cy / sh * (sh - h) + 0.5) }
    printf "%d %d %d %d %.6f %.6f %.6f %.6f", w,h,x,y, x/sw,y/sh,w/sw,h/sh}')
EOF
}

# ── chunk: compute_area
compute_area() {  # the area for the pen's CURRENT position (toggle ON, a move, the ghost): pen position, then area_math pen
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
    area_math pen "$1" "$2" "$3" "$4"
}

# ── chunk: apply_area
apply_area() {  # map the computed area (W H X Y FX FY FW FH SW SH), record it, then move the live overlay or (re)spawn it
    busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "$FX" "$FY" "$FW" "$FH" || { note "Mapping change failed"; return 1; }
    echo "$X $Y $W $H $DIM $SW $SH $FX $FY $FW $FH" > "$AREA"
    if [ -f "$RD/overlay.pid" ] && kill -0 "$(cat "$RD/overlay.pid")" 2>/dev/null && [ -p "$FIFO" ] &&
       timeout 1 sh -c 'echo "$1" > "$2"' _ "$X $Y $W $H $DIM" "$FIFO" 2>/dev/null; then
        return 0                 # the overlay is alive and took the new geometry
    fi
    [ -f "$RD/overlay.pid" ] && kill "$(cat "$RD/overlay.pid")" 2>/dev/null
    nohup python3 "$DIR/tablet-overlay.py" "$X" "$Y" "$W" "$H" "$DIM" --fifo "$FIFO" > "$RD/overlay.log" 2>&1 9>&- &   # 9>&-: the overlay must not inherit the lock
    echo $! > "$RD/overlay.pid"
}

[ "$MODE" = resize ] || find_pen      # resize looks the pen up only when it has something to apply
case "$MODE" in
# ── chunk: resize
resize)    # while ON: the conf's SCALE around the area's own centre (the pen's position only when there is no area on record); a queued tick whose width is already on screen does nothing
    if [ -f "$STATE" ]; then
        set -- $(cat "$AREA" 2>/dev/null)
        if [ -n "${7:-}" ]; then
            TARGET_W=$(awk -v s="$SCALE" -v sw="$6" 'BEGIN{ if (s > 0.8) s = 0.8; if (s < 0.05) s = 0.05; printf "%d", int(sw * s + 0.5) }')
            if [ "$TARGET_W" != "$3" ]; then
                CENTRE=$(awk -v x="$1" -v y="$2" -v w="$3" -v h="$4" 'BEGIN{printf "%.1f %.1f", x + w / 2, y + h / 2}')
                area_math centre $CENTRE "$6" "$7" && apply_area
            fi
        else
            compute_area && apply_area
        fi
    fi
    ;;
# ── chunk: where
where)
    compute_area && echo "$X $Y $W $H $DIM $SW $SH"
    ;;
# ── chunk: suspend
suspend)   # while ON: the base mapping for the moment, precision mode stays on (a relocation is aimed: the cursor roams)
    if [ -f "$STATE" ]; then
        set -- $(cat "$STATE")
        busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "${1:-0}" "${2:-0}" "${3:-1}" "${4:-1}"
    fi
    ;;
# ── chunk: resume
resume)    # while ON: the area on record again (the relocation was cancelled)
    if [ -f "$STATE" ] && [ -f "$AREA" ]; then
        set -- $(cat "$AREA")
        if [ -z "${11:-}" ] && [ -n "${7:-}" ]; then     # an area file from before the fractions were recorded: compute them
            set -- "$@" $(awk -v x="$1" -v y="$2" -v w="$3" -v h="$4" -v sw="$6" -v sh="$7" 'BEGIN{printf "%.6f %.6f %.6f %.6f", x/sw, y/sh, w/sw, h/sh}')
        fi
        [ -n "${11:-}" ] && busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "$8" "$9" "${10}" "${11}"
    fi
    ;;
# ── chunk: toggle
*)
    if [ ! -f "$STATE" ]; then
        CUR=$(busctl --user get-property $KW $MGR/$pen $IF outputArea | cut -d' ' -f2-)
        if compute_area && apply_area; then
            echo "$CUR" > "$STATE"
        fi
    elif [ -f "$MARK" ] && [ $(( $(date +%s) - $(stat -c %Y "$MARK" 2>/dev/null || echo 0) )) -le 3 ]; then
        rm -f "$MARK"            # relocation confirmed: re-map at the pen, the saved base mapping stays
        compute_area && apply_area
    else
        set -- $(cat "$STATE")
        busctl --user set-property $KW $MGR/$pen $IF outputArea '(dddd)' "${1:-0}" "${2:-0}" "${3:-1}" "${4:-1}"
        rm -f "$STATE" "$AREA" "$MARK"
        if [ -f "$RD/overlay.pid" ]; then
            kill "$(cat "$RD/overlay.pid")" 2>/dev/null
            rm -f "$RD/overlay.pid"
        fi
    fi
    ;;
esac
