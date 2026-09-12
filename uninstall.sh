#!/bin/bash
# uninstall.sh - remove plasma-wacom-center for the current user. The
# reverse of install.sh. Your settings are kept; the paths and the one
# sudo line are printed at the end. Safe to re-run.
#
# Step 1 switches precision mode off FIRST, and stops if it cannot. KWin keeps
# the pen's mapping in kcminputrc and loads it again every time the tablet
# appears, so a precision rectangle left behind outlives the uninstall: the pen
# would stay in a small part of the screen with every tool that knew the full
# mapping deleted. The README says how to undo that by hand.
set -e
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
RD="${XDG_RUNTIME_DIR:-/tmp}/tabprec"

echo "== 1/5 Switching precision mode off"
if [ -f "$RD/saved-area" ]; then
    [ -x "$BIN/tablet-precision.sh" ] && "$BIN/tablet-precision.sh" >/dev/null 2>&1 || true
    if [ -f "$RD/saved-area" ]; then
        echo >&2
        echo "Precision mode is ON and this script cannot switch it off." >&2
        echo "Your pen would stay mapped to the small rectangle after the uninstall," >&2
        echo "because KWin keeps that mapping in kcminputrc." >&2
        echo "Switch precision mode off with its pad key, then run this script again." >&2
        echo "If the pad key does not work, see \"If the pen only reaches a small part" >&2
        echo "of the screen\" in the README." >&2
        exit 1
    fi
    echo "switched off"
else
    echo "was not on"
fi

echo "== 2/5 Stopping the daemon"
pkill -f "$BIN/tablet-hover.py" 2>/dev/null && echo "stopped" || echo "was not running"

echo "== 3/5 Removing the scripts from $BIN and the pen ledgers"
for f in tablet-precision.sh tablet-precision-size.sh tablet-pen-pos.py \
         tablet-overlay.py tablet-overlay.qml tablet-size-preview.py \
         tablet-pointer-warp.py tablet-hover.py tablet-pad-probe.py \
         wacom_center.py tablet-pie.sh tablet-size-preview.qml; do
    rm -f "$BIN/$f"                       # the last two: files older installs left behind
done
rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/tabprec"   # the pen ledgers (tablet-precision.sh heal)

echo "== 4/5 Removing the launcher entries and their shortcuts"
for e in net.local.tabprec-toggle net.local.tabprec-bigger \
         net.local.tabprec-smaller net.local.tabpie; do
    rm -f "$APPS/$e.desktop"
    # kglobalaccel nests every .desktop under [services]: a flat group deletes nothing at all
    kwriteconfig6 --file kglobalshortcutsrc --group services --group "$e.desktop" --key _launch --delete 2>/dev/null || true
    kwriteconfig6 --file kglobalshortcutsrc --group services --group "$e.desktop" --key _k_friendly_name --delete 2>/dev/null || true
done
rm -f "$APPS/wacom-center.desktop" "$HOME/.config/autostart/tablet-hover.desktop"
kbuildsycoca6 2>/dev/null || true

echo "== 5/5 What stays (yours to keep or delete)"
cat <<'EOF'

- ~/.config/tabprec.conf                    your settings; delete it to forget them
- the pad-key and ring entries in kcminputrc  what the pad keys send; clear them in
                                            Wacom Center before uninstalling, or in
                                            System Settings -> Drawing Tablet after
- the pen's screen mapping in kcminputrc    step 1 put it back. If the pen still
                                            reaches only a small part of the screen,
                                            see "If the pen only reaches a small part
                                            of the screen" in the README
- /etc/udev/rules.d/70-tablet-access.rules  the permission rule (one sudo):

  sudo rm /etc/udev/rules.d/70-tablet-access.rules && sudo udevadm control --reload

Log out and back in once, so the shortcut daemon forgets the entries.
Done.
EOF
