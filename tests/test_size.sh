#!/bin/bash
# Drives tablet-precision-size.sh with a stub toggle (logs its mode) and a fake
# size preview (logs itself, lives 1 s): the +/-2 % step and its clamps, the
# other conf lines kept, the resize only while precision mode is on, the
# preview only while it is off and once per spin, and nothing at all while a
# drag is in progress (a fresh relocate marker). No GUI, no KWin.
# Usage: test_size.sh <scratch dir> <path to tablet-precision-size.sh>
set -u
S=$1/size-test
SRC=$2
rm -rf "$S"; mkdir -p "$S/bin" "$S/rd/tabprec" "$S/conf"
cp "$SRC" "$S/bin/tablet-precision-size.sh"
printf '#!/bin/bash\necho "CALL $1" >> "$FAKE_LOG"\n' > "$S/bin/tablet-precision.sh"
printf '#!/usr/bin/env python3\nimport os, time\nopen(os.environ["FAKE_LOG"], "a").write("PREVIEW\\n")\ntime.sleep(1)\n' > "$S/bin/tablet-size-preview.py"
chmod +x "$S/bin/"*
export XDG_RUNTIME_DIR="$S/rd" XDG_CONFIG_HOME="$S/conf" FAKE_LOG="$S/calls.log"
CONF="$S/conf/tabprec.conf"
printf 'SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nRING_STEP=2\n' > "$CONF"   # 2 points a tick for the arithmetic below
RD="$S/rd/tabprec"
T="$S/bin/tablet-precision-size.sh"
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }
calls() { tr '\n' ' ' < "$FAKE_LOG" 2>/dev/null | sed 's/ $//'; }

# 1: mode OFF, up: SCALE +0.02, the rest of the conf kept, the preview spawned, no resize call
"$T" up; sleep 0.3
check "1 SCALE 0.29 -> 0.3100"                'grep -qx "SCALE=0.3100" "$CONF"'
check "1 DIM and HOVER_MASK kept"             'grep -qx "DIM=0.10" "$CONF" && grep -qx "HOVER_MASK=0x80" "$CONF"'
check "1 preview spawned, no resize (off)"    '[ "$(calls)" = "PREVIEW" ]'
check "1 preview pid recorded and alive"      '[ -f "$RD/preview.pid" ] && kill -0 "$(cat "$RD/preview.pid")"'

# 2: a second tick while the preview lives: the conf steps, the preview is not respawned
"$T" down; sleep 0.3
check "2 SCALE back to 0.2900"                'grep -qx "SCALE=0.2900" "$CONF"'
check "2 one preview per spin"                '[ "$(calls)" = "PREVIEW" ]'
sleep 1.2                                     # the fake preview ends

# 3: mode ON (state file): the area is resized, no preview
touch "$RD/saved-area"
"$T" up; sleep 0.3
check "3 SCALE 0.3100"                        'grep -qx "SCALE=0.3100" "$CONF"'
check "3 resize called, no preview (on)"      '[ "$(calls)" = "PREVIEW CALL resize" ]'

# 4: a drag in progress (fresh marker): nothing happens, not even the conf
touch "$RD/relocate"
"$T" up; sleep 0.3
check "4 fresh marker: SCALE unchanged"       'grep -qx "SCALE=0.3100" "$CONF"'
check "4 fresh marker: no call"               '[ "$(calls)" = "PREVIEW CALL resize" ]'

# 5: a stale marker (10 s old) is no drag
touch -d '10 seconds ago' "$RD/relocate"
"$T" down; sleep 0.3
check "5 stale marker: SCALE 0.2900"          'grep -qx "SCALE=0.2900" "$CONF"'
check "5 stale marker: resize called"         '[ "$(calls)" = "PREVIEW CALL resize CALL resize" ]'

# 6: the clamps
sed -i 's/^SCALE=.*/SCALE=0.79/' "$CONF"; "$T" up; "$T" up; sleep 0.3
check "6 up from 0.79 twice: clamped at 0.8000"   'grep -qx "SCALE=0.8000" "$CONF"'
sed -i 's/^SCALE=.*/SCALE=0.06/' "$CONF"; "$T" down; "$T" down; sleep 0.3
check "6 down from 0.06 twice: clamped at 0.0500" 'grep -qx "SCALE=0.0500" "$CONF"'
check "6 DIM still kept"                      'grep -qx "DIM=0.10" "$CONF"'

# 7: RING_STEP from the conf: 5 points per tick, then half a point; the line itself is kept
printf 'SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\nRING_STEP=5\n' > "$CONF"
"$T" up; sleep 0.3
check "7 RING_STEP=5: 0.29 -> 0.3400"         'grep -qx "SCALE=0.3400" "$CONF"'
check "7 RING_STEP line kept"                 'grep -qx "RING_STEP=5" "$CONF"'
sed -i 's/^RING_STEP=.*/RING_STEP=0.5/' "$CONF"; "$T" down; sleep 0.3
check "7 RING_STEP=0.5: 0.34 -> 0.3350"       'grep -qx "SCALE=0.3350" "$CONF"'
sed -i 's/^RING_STEP=.*/RING_STEP=junk/' "$CONF"; "$T" up; sleep 0.3
check "7 RING_STEP=junk: the half-point default" 'grep -qx "SCALE=0.3400" "$CONF"'

echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
