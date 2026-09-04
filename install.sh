#!/bin/bash
# install.sh - deploy plasma-wacom-center for the current user. No root needed
# for the deploy itself; one udev rule (printed at the end) needs sudo.
# Safe to re-run.
set -e
cd "$(dirname "$0")"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
KW=org.kde.kglobalaccel

echo "== 1/5 Deploying to $BIN"
mkdir -p "$BIN" "$APPS"
install -m 755 tablet-precision.sh tablet-precision-size.sh \
    tablet-pen-pos.py tablet-overlay.py tablet-size-preview.py \
    wacom_center.py "$BIN/"
install -m 644 tablet-overlay.qml tablet-size-preview.qml "$BIN/"

echo "== 2/5 Shortcut launcher entries (command-shortcut marker included)"
mkentry() {  # name, exec-args, description
    cat > "$APPS/net.local.$1.desktop" <<EOF
[Desktop Entry]
Exec=$BIN/$2
Name=$3
NoDisplay=true
StartupNotify=false
Type=Application
X-KDE-GlobalAccel-CommandShortcut=true
EOF
}
mkentry tabprec-toggle "tablet-precision.sh" "Precision mode toggle"
mkentry tabprec-bigger "tablet-precision-size.sh up" "Precision area bigger"
mkentry tabprec-smaller "tablet-precision-size.sh down" "Precision area smaller"
cat > "$APPS/wacom-center.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wacom Center
Comment=Tablet precision mode and express key settings
Exec=python3 $BIN/wacom_center.py
Icon=input-tablet
Terminal=false
Categories=Settings;HardwareSettings;
EOF
kbuildsycoca6 2>/dev/null || true

echo "== 3/5 Registering global shortcuts (F12 toggle, F10 bigger, F9 smaller)"
reg() {  # component, friendly, qt-keycode
    busctl --user call $KW /kglobalaccel org.kde.KGlobalAccel doRegister \
        as 4 "net.local.$1.desktop" "_launch" "$2" "$2"
    busctl --user call $KW /kglobalaccel org.kde.KGlobalAccel setForeignShortcut \
        asai 4 "net.local.$1.desktop" "_launch" "$2" "$2" 1 "$3"
}
reg tabprec-toggle  "Precision mode toggle"  318767163   # Meta+Shift+F12
reg tabprec-bigger  "Precision area bigger"  318767161   # Meta+Shift+F10
reg tabprec-smaller "Precision area smaller" 318767160   # Meta+Shift+F9

echo "== 4/5 Ring binding (optional)"
pad=""
for n in $(busctl --user get-property org.kde.KWin /org/kde/KWin/InputDevice \
           org.kde.KWin.InputDeviceManager devicesSysNames 2>/dev/null \
           | tr -d '"' | cut -d' ' -f3-); do
    p=$(busctl --user get-property org.kde.KWin "/org/kde/KWin/InputDevice/$n" \
        org.kde.KWin.InputDevice tabletPad 2>/dev/null)
    case "$p" in *true*)
        pad=$(busctl --user get-property org.kde.KWin "/org/kde/KWin/InputDevice/$n" \
              org.kde.KWin.InputDevice name | cut -d'"' -f2)
        break;;
    esac
done
if [ -n "$pad" ]; then
    printf 'Bind the touch ring of "%s" (mode 1) to the size control? [y/N] ' "$pad"
    read -r yn
    if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
        kwriteconfig6 --notify --file kcminputrc --group ButtonRebinds \
            --group TabletRing --group "$pad" --group 0 --key 0 \
            "AxisKey,Meta+Shift+F10,Meta+Shift+F9,360"
        echo "Ring bound: one step per ~15 degrees."
    fi
else
    echo "No tablet pad detected (tablet asleep?). Re-run later for the ring."
fi
qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure 2>/dev/null || true

echo "== 5/5 Manual steps that need you"
cat <<'EOF'

A. Pen position needs read access to the pen device (one sudo, once):

   echo 'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Pen*", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-tablet-pen-read.rules
   sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input

   Without it, precision mode centres on the mouse cursor instead of the pen.

B. Bind a pad button to the toggle: System Settings -> Drawing Tablet -> Pad,
   press the button, choose "Send keyboard key", press Meta+Shift+F12.
   Use only F-keys and modifiers in pad chords - letters silently fail
   under non-Latin keyboard layouts.

C. If the shortcuts do not fire yet, log out and back in once - the shortcut
   daemon then rebuilds every entry from its config file.

Done.
EOF
