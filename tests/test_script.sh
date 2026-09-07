#!/bin/bash
# Drives tablet-precision.sh through on / move / resize / suspend / resume /
# off with stubbed busctl + notify-send, a fake pen reader and a fake overlay.
# No KWin, no GUI.
# Usage: test_script.sh <scratch dir> <path to tablet-precision.sh>
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=$1/script-test
SRC=$2
rm -rf "$S"; mkdir -p "$S/bin" "$S/rd" "$S/conf"
cp "$SRC" "$S/bin/tablet-precision.sh"
cp "$HERE/fake/tablet-overlay.py" "$HERE/fake/tablet-pen-pos.py" "$S/bin/"
chmod +x "$S/bin/"* "$HERE/stubs/"*
export PATH="$HERE/stubs:$PATH" XDG_RUNTIME_DIR="$S/rd" XDG_CONFIG_HOME="$S/conf"
export STUB_LOG="$S/busctl.log" FAKE_LOG="$S/overlay.log"
printf 'SCALE=0.29\nDIM=0.10\nHOVER_MASK=0x80\n' > "$S/conf/tabprec.conf"
T="$S/bin/tablet-precision.sh"
RD="$S/rd/tabprec"
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }
sets() { grep -c 'set-property' "$STUB_LOG"; }
SET='busctl --user set-property org.kde.KWin /org/kde/KWin/InputDevice/event5 org.kde.KWin.InputDevice outputArea (dddd)'

# 1: OFF -> ON. SCALE 0.29 of 2560 = 742 x 490 (aspect 224/148), pen at the centre -> 909 475.
"$T" toggle; sleep 0.4
check "1 base mapping saved"            '[ "$(cat "$RD/saved-area")" = "0 0 1 1" ]'
check "1 area file = px + fractions"     '[ "$(cat "$RD/area")" = "909 475 742 490 0.10 2560 1440 0.355078 0.329861 0.289844 0.340278" ]'
check "1 mapping set once"              '[ "$(sets)" -eq 1 ]'
check "1 outputArea fractions"          'grep -q "set-property.*outputArea (dddd) 0.355078 0.329861 0.289844 0.340278" "$STUB_LOG"'
check "1 overlay spawned with --fifo"   'grep -q "^SPAWN 909 475 742 490 0.10 --fifo $RD/overlay.fifo$" "$FAKE_LOG"'
check "1 fifo exists"                   '[ -p "$RD/overlay.fifo" ]'
check "1 pen sysname cached"            '[ "$(cat "$RD/pen")" = "event5" ]'
PID1=$(cat "$RD/overlay.pid")

# 2: fresh relocate marker + press -> MOVE (pen at 200 300 -> 142 198), still ON, overlay moved through the pipe.
touch "$RD/relocate"
FAKE_PEN="200 300 2560 1440" "$T" toggle; sleep 0.4
check "2 still on, base mapping kept"   '[ "$(cat "$RD/saved-area")" = "0 0 1 1" ]'
check "2 marker consumed"               '[ ! -f "$RD/relocate" ]'
check "2 mapping set again (2 calls)"   '[ "$(sets)" -eq 2 ]'
check "2 area file = 142 198 742 490 …" '[ "$(cat "$RD/area")" = "142 198 742 490 0.10 2560 1440 0.055469 0.137500 0.289844 0.340278" ]'
check "2 pipe line 142 198 742 490 0.10" 'grep -qx "142 198 742 490 0.10" "$FAKE_LOG"'
check "2 overlay NOT respawned"         '[ "$(cat "$RD/overlay.pid")" = "$PID1" ] && [ "$(grep -c SPAWN "$FAKE_LOG")" -eq 1 ]'

# 3: ring resize to SCALE 0.40 -> 1024 x 677 around the area's own centre (513, 443) -> 1 105, through
#    the pipe. The pen sits far away (2000 1000): a resize must not look at it.
sed -i 's/^SCALE=.*/SCALE=0.40/' "$S/conf/tabprec.conf"
FAKE_PEN="2000 1000 2560 1440" "$T" resize; sleep 0.4
check "3 resize keeps the centre: pipe line 1 105 1024 677 0.10" 'grep -qx "1 105 1024 677 0.10" "$FAKE_LOG"'
check "3 area file = 1 105 1024 677 …"  '[ "$(cat "$RD/area")" = "1 105 1024 677 0.10 2560 1440 0.000391 0.072917 0.400000 0.470139" ]'
check "3 resize did not respawn"        '[ "$(cat "$RD/overlay.pid")" = "$PID1" ] && [ "$(grep -c SPAWN "$FAKE_LOG")" -eq 1 ]'
check "3 mapping set (3 calls)"         '[ "$(sets)" -eq 3 ]'
check "3 resize ignores the pen: no line near 2000 1000" '! grep -q "^1[0-9][0-9][0-9] [0-9]* 1024 677" "$FAKE_LOG"'

# 3a: the same SCALE again (a ring tick queued behind the one that did the work): nothing happens.
"$T" resize; sleep 0.3
check "3a resize with the width already on screen: no mapping call, no pipe line" '[ "$(sets)" -eq 3 ] && [ "$(wc -l < "$FAKE_LOG")" -eq 3 ]'

# 3b: suspend -> the saved base mapping while still ON; resume -> the area's fractions again; overlay untouched.
"$T" suspend; sleep 0.3
check "3b suspend: base mapping 0 0 1 1, still on" '[ "$(tail -1 "$STUB_LOG")" = "$SET 0 0 1 1" ] && [ -f "$RD/saved-area" ]'
"$T" resume; sleep 0.3
check "3b resume: area re-mapped 0.000391 0.072917 0.400000 0.470139" '[ "$(tail -1 "$STUB_LOG")" = "$SET 0.000391 0.072917 0.400000 0.470139" ]'
check "3b overlay untouched (1 spawn, 3 log lines)" '[ "$(grep -c SPAWN "$FAKE_LOG")" -eq 1 ] && [ "$(wc -l < "$FAKE_LOG")" -eq 3 ]'
check "3b mapping set (5 calls)"        '[ "$(sets)" -eq 5 ]'

# 3c: an area file from before the fractions were recorded (7 fields): resume computes them.
echo "142 198 742 490 0.10 2560 1440" > "$RD/area"
"$T" resume; sleep 0.3
check "3c resume from a 7-field area file: 0.055469 0.137500 0.289844 0.340278" '[ "$(tail -1 "$STUB_LOG")" = "$SET 0.055469 0.137500 0.289844 0.340278" ] && [ "$(sets)" -eq 6 ]'

# 3d: grow to SCALE 0.80 from that area (centre 513 443): 2048 x 1353 cannot stay centred there - clamped to 0 0.
sed -i 's/^SCALE=.*/SCALE=0.80/' "$S/conf/tabprec.conf"
"$T" resize; sleep 0.4
check "3d resize clamped to the screen: 0 0 2048 1353" 'grep -qx "0 0 2048 1353 0.10" "$FAKE_LOG"'
check "3d area file rewritten with fractions" '[ "$(cat "$RD/area")" = "0 0 2048 1353 0.10 2560 1440 0.000000 0.000000 0.800000 0.939583" ] && [ "$(sets)" -eq 7 ]'

# 4: STALE marker (10 s old) + press -> OFF, not move.
touch -d '10 seconds ago' "$RD/relocate"
"$T" toggle; sleep 0.4
check "4 off: state, area, marker gone" '[ ! -f "$RD/saved-area" ] && [ ! -f "$RD/area" ] && [ ! -f "$RD/relocate" ]'
check "4 base mapping restored"         '[ "$(tail -1 "$STUB_LOG")" = "$SET 0 0 1 1" ] && [ "$(sets)" -eq 8 ]'
"$T" suspend; "$T" resume; "$T" resize; sleep 0.3
check "4 suspend/resume/resize are no-ops when off" '[ "$(sets)" -eq 8 ]'
check "4 overlay killed"                '[ ! -d "/proc/$PID1" ]'
check "4 pid file removed"              '[ ! -f "$RD/overlay.pid" ]'

# 5: ON again (a second overlay, reusing the pipe), then OFF with no marker.
"$T" toggle; sleep 0.4
PID2=$(cat "$RD/overlay.pid")
check "5 on: new overlay alive"         '[ "$PID2" != "$PID1" ] && [ -d "/proc/$PID2" ] && [ "$(grep -c SPAWN "$FAKE_LOG")" -eq 2 ]'
"$T" toggle; sleep 0.4
check "5 off again"                     '[ ! -f "$RD/saved-area" ] && [ ! -d "/proc/$PID2" ]'

# 6: runs are serialized: a toggle waits for the lock another run holds; the overlay it spawns
#    must not inherit the lock (or the OFF toggle would wait 5 s and give up).
( flock 9; sleep 1.2 ) 9>"$RD/lock" &
sleep 0.2; t0=$(date +%s%N); "$T" toggle; t1=$(date +%s%N); wait
check "6 toggle waited for the lock (>= 0.8 s)" '[ $(( (t1 - t0) / 1000000 )) -ge 800 ] && [ -f "$RD/saved-area" ]'
PID3=$(cat "$RD/overlay.pid")
t0=$(date +%s%N); "$T" toggle; t1=$(date +%s%N); sleep 0.4
check "6 off again in under 2 s: the overlay did not hold the lock" '[ $(( (t1 - t0) / 1000000 )) -lt 2000 ] && [ ! -f "$RD/saved-area" ] && [ ! -d "/proc/$PID3" ]'
check "no notifications (no errors)"    '! grep -q notify-send "$STUB_LOG"'

echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
