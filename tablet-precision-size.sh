#!/bin/bash
# tablet-precision-size.sh {up|down} - step the precision area size +/-2%.
#
# Called by the tablet ring (mode 1) through two F-key chords. Writes SCALE
# to ~/.config/tabprec.conf, live-resizes the mapping when precision mode is
# on (tablet-precision.sh resize), and keeps the centred fading preview
# (tablet-size-preview.py) alive - the preview watches the conf itself.

export LC_ALL=C.UTF-8
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/tabprec.conf"
[ -f "$CONF" ] && . "$CONF"
SCALE=${SCALE:-0.7071}
DIM=${DIM:-0.35}
RD="${XDG_RUNTIME_DIR:-/tmp}/tabprec"
mkdir -p "$RD"
DIR=$(cd "$(dirname "$0")" && pwd)

STEP=0.02
[ "$1" = "down" ] && STEP=-0.02
SCALE=$(awk -v s="$SCALE" -v d="$STEP" 'BEGIN{
    s += d; if (s > 0.80) s = 0.80; if (s < 0.05) s = 0.05;
    printf "%.4f", s}')
printf 'SCALE=%s\nDIM=%s\n' "$SCALE" "$DIM" > "$CONF"

"$DIR/tablet-precision.sh" resize

if ! { [ -f "$RD/preview.pid" ] && kill -0 "$(cat "$RD/preview.pid")" 2>/dev/null; }; then
    nohup python3 "$DIR/tablet-size-preview.py" > "$RD/preview.log" 2>&1 &
    echo $! > "$RD/preview.pid"
fi
