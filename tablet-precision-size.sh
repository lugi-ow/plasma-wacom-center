#!/bin/bash
# tablet-precision-size.sh {up|down} - step the precision area size by
# RING_STEP percentage points of the screen width (conf key, default 2;
# the Wacom Center ring field).
#
# Called by the tablet ring (mode 1) through two F-key chords. Writes SCALE
# to ~/.config/tabprec.conf, then: precision mode ON - the area itself takes
# the new size around its own centre (tablet-precision.sh resize) and nothing
# else shows; OFF - the centred size preview (tablet-size-preview.py, the
# look of the mode with the waiting border) shows the prospective size and
# fades by itself; it watches the conf, so one process serves a whole spin.
# While the area is being DRAGGED (tablet-hover.py keeps $RD/relocate under
# 3 s old) a tick does nothing at all - not even the conf changes.

export LC_ALL=C.UTF-8
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/tabprec.conf"
[ -f "$CONF" ] && . "$CONF"
SCALE=${SCALE:-0.7071}
DIM=${DIM:-0.35}
RD="${XDG_RUNTIME_DIR:-/tmp}/tabprec"
mkdir -p "$RD"
DIR=$(cd "$(dirname "$0")" && pwd)
MARK="$RD/relocate"

# ── chunk: drag-guard
if [ -f "$MARK" ] && [ $(( $(date +%s) - $(stat -c %Y "$MARK" 2>/dev/null || echo 0) )) -le 3 ]; then
    exit 0                   # a relocation is being aimed: the size stays
fi

# ── chunk: step
STEP=$(awk -v p="${RING_STEP:-2}" 'BEGIN{ if (p + 0 <= 0) p = 2; printf "%.4f", p / 100 }')   # points per tick, from the conf
[ "$1" = "down" ] && STEP="-$STEP"
SCALE=$(awk -v s="$SCALE" -v d="$STEP" 'BEGIN{
    s += d; if (s > 0.80) s = 0.80; if (s < 0.05) s = 0.05;
    printf "%.4f", s}')
# ── chunk: conf-write
# rewrite SCALE/DIM in place and keep every other line (touch-preview keys)
REST=$(grep -v -E '^[[:space:]]*(SCALE|DIM)=' "$CONF" 2>/dev/null)
{ printf 'SCALE=%s\nDIM=%s\n' "$SCALE" "$DIM"; [ -n "$REST" ] && printf '%s\n' "$REST"; } > "$CONF"

# ── chunk: resize-or-preview
if [ -f "$RD/saved-area" ]; then
    "$DIR/tablet-precision.sh" resize          # precision mode on: the area itself, around its centre
elif ! { [ -f "$RD/preview.pid" ] && kill -0 "$(cat "$RD/preview.pid")" 2>/dev/null; }; then
    nohup python3 "$DIR/tablet-size-preview.py" > "$RD/preview.log" 2>&1 &   # off: the centred preview
    echo $! > "$RD/preview.pid"
fi
