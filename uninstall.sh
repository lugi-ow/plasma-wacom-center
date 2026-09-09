#!/bin/bash
# uninstall.sh - remove plasma-wacom-center for the current user. The
# reverse of install.sh. Your settings are kept; the paths and the one
# sudo line are printed at the end. Safe to re-run.
set -e
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"

echo "== 1/4 Stopping the daemon"
pkill -f "$BIN/tablet-hover.py" 2>/dev/null && echo "stopped" || echo "was not running"

echo "== 2/4 Removing the scripts from $BIN"
for f in tablet-precision.sh tablet-precision-size.sh tablet-pen-pos.py \
         tablet-overlay.py tablet-overlay.qml tablet-size-preview.py \
         tablet-pointer-warp.py tablet-hover.py tablet-pad-probe.py \
         wacom_center.py tablet-pie.sh tablet-size-preview.qml; do
    rm -f "$BIN/$f"                       # the last two: files older installs left behind
done

echo "== 3/4 Removing the launcher entries and their shortcuts"
for e in net.local.tabprec-toggle net.local.tabprec-bigger \
         net.local.tabprec-smaller net.local.tabpie; do
    rm -f "$APPS/$e.desktop"
    kwriteconfig6 --file kglobalshortcutsrc --group "$e.desktop" --key _launch --delete 2>/dev/null || true
    kwriteconfig6 --file kglobalshortcutsrc --group "$e.desktop" --key _k_friendly_name --delete 2>/dev/null || true
done
rm -f "$APPS/wacom-center.desktop" "$HOME/.config/autostart/tablet-hover.desktop"
kbuildsycoca6 2>/dev/null || true

echo "== 4/4 What stays (yours to keep or delete)"
cat <<'EOF'

- ~/.config/tabprec.conf                    your settings; delete it to forget them
- the pad-key and ring entries in kcminputrc  what the pad keys send; clear them in
                                            Wacom Center before uninstalling, or in
                                            System Settings -> Drawing Tablet after
- /etc/udev/rules.d/70-tablet-access.rules  the permission rule (one sudo):

  sudo rm /etc/udev/rules.d/70-tablet-access.rules && sudo udevadm control --reload

Log out and back in once, so the shortcut daemon forgets the entries.
Done.
EOF
