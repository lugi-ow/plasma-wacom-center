#!/bin/bash
# install.sh - deploy plasma-wacom-center for the current user. No root needed
# for the deploy itself; one udev rule (printed at the end) needs sudo - it
# covers the pen position and the express keys' touch sense.
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
    tablet-pointer-warp.py tablet-pie.sh tablet-hover.py tablet-pad-probe.py \
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
mkentry tabpie "tablet-pie.sh Krita" "Pie menu under the pen"
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
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/tablet-hover.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tablet hover preview
Comment=Ghost of the precision area while a finger rests on the precision key (idle until a supported tablet appears)
Exec=python3 $BIN/tablet-hover.py
NoDisplay=true
EOF
kbuildsycoca6 2>/dev/null || true

echo "== 3/5 Registering global shortcuts (F12 toggle, F11 pie, F10 bigger, F9 smaller)"
reg() {  # component, friendly, qt-keycode
    busctl --user call $KW /kglobalaccel org.kde.KGlobalAccel doRegister \
        as 4 "net.local.$1.desktop" "_launch" "$2" "$2"
    busctl --user call $KW /kglobalaccel org.kde.KGlobalAccel setForeignShortcut \
        asai 4 "net.local.$1.desktop" "_launch" "$2" "$2" 1 "$3"
}
reg tabprec-toggle  "Precision mode toggle"  318767163   # Meta+Shift+F12
reg tabpie          "Pie menu under the pen" 318767162   # Meta+Shift+F11
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

A. One permission rule (one sudo, once). It lets the scripts read the pen's
   position and, on Wacom tablets, the express keys' touch sense:

   printf '%s\n' 'SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Pen*", TAG+="uaccess"' 'KERNEL=="hidraw*", KERNELS=="0003:056A:*|0005:056A:*", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-tablet-access.rules && sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input --subsystem-match=hidraw

   Without it, precision mode centres on the mouse cursor instead of the
   pen, and the touch preview stays off.

B. Bind a pad button to the toggle: System Settings -> Drawing Tablet -> Pad,
   press the button, choose "Send keyboard key", press Meta+Shift+F12.
   Another button on Meta+Shift+F11 opens the Kando pie under the pen
   (needs Kando; the menu name is the argument in net.local.tabpie.desktop).
   Use only F-keys and modifiers in pad chords - letters silently fail
   under non-Latin keyboard layouts.

C. If the shortcuts do not fire yet, log out and back in once - the shortcut
   daemon then rebuilds every entry from its config file.

D. ExpressKey touch preview - a ghost of the precision area while a finger
   RESTS on the precision key, before the press. Wacom Intuos Pro (2017 or
   later): nothing to set up. After step A and a relogin, press the
   precision key once; the daemon learns which key it is and from then on
   a resting finger shows the ghost. Other tablets: only keys with a touch
   sensor can do this (Intuos Pro, Cintiq Pro, MobileStudio Pro). For a
   Wacom model the daemon does not know, run
   ~/.local/bin/tablet-pad-probe.py once per connection type (USB and
   Bluetooth differ) and put the bytes it shows into ~/.config/tabprec.conf
   as HOVER_REPORT_USB, HOVER_BYTE_USB, PRESS_BYTE_USB (and the same with
   _BT). Reference, Intuos Pro M: USB report 0x11, touch byte 2, press
   byte 1; Bluetooth report 0x80, touch byte 283, press byte 282.

Done.
EOF
