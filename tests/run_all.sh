#!/bin/bash
# tests/run_all.sh - every gate in one go, ~35 s: compile every Python file,
# syntax-check every shell script, the map gate (tests/check_map.py), then the
# three rigs - test_script.sh (the toggle with a stubbed busctl, a fake pen
# reader and a fake overlay), test_size.sh (the ring script with a stub toggle
# and a fake preview) and test_hover.py (the daemon with a named pipe as the
# pad, a fake pen, fake overlays and a fake toggle). Run from anywhere; needs
# python3 and bash only - no Qt, no tablet, no KWin. Exit 0 = all green.
set -o pipefail
cd "$(dirname "$0")/.." || exit 1
S="${TMPDIR:-/tmp}/tabprec-tests"        # the rigs wipe their own subfolders
red=0

echo "== py_compile"
python3 -m py_compile *.py tests/*.py tests/fake/*.py || red=1
echo "== bash -n"
for f in *.sh tests/*.sh; do bash -n "$f" || red=1; done
echo "== map"
python3 tests/check_map.py || red=1
echo "== toggle rig"
bash tests/test_script.sh "$S" "$PWD/tablet-precision.sh" 2>&1 | grep -E '^(FAIL|failures)' || red=1
echo "== ring rig"
bash tests/test_size.sh "$S" "$PWD/tablet-precision-size.sh" 2>&1 | grep -E '^(FAIL|failures)' || red=1
echo "== hover rig"
python3 tests/test_hover.py "$S" "$PWD/tablet-hover.py" 2>/dev/null | grep -E '^(FAIL|failures)' || red=1

echo
[ "$red" -eq 0 ] && echo "ALL GATES GREEN" || echo "GATES RED"
exit "$red"
