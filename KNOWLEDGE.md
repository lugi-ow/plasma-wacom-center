# The knowledge (why these scripts look the way they do)

Companion to the plasma-wacom-center README.

Hard-won facts, each of which cost a debugging session. If you build your own
tablet tooling on Plasma Wayland, read this first.

**KWin owns the tablet mapping.** Each input device is a D-Bus object under
`org.kde.KWin /org/kde/KWin/InputDevice/eventN` with writable properties -
`outputArea` (the mapped screen rectangle, as fractions) is all precision
mode needs. Event numbers change on every Bluetooth reconnect: never cache
them, find the device by its `tabletTool` / `tabletPad` property each run.

**Letter chords die under non-Latin layouts.** KWin's button-rebind injector
resolves a chord's letter through the *currently active* keyboard layout
(`keycodeFromKeysym` searches only that layout). With a Cyrillic layout
active there is no key producing a Latin `p`, so `Meta+Shift+P` sends
nothing - silently, except for a `kwin_buttonrebinds` line in the journal.
F-keys and bare modifiers exist in every layout. Bind pads and rings to
F-key chords only.

**Command shortcuts need three things.** A `.desktop` file that the shortcut
daemon will execute must carry `X-KDE-GlobalAccel-CommandShortcut=true`, must
be in the service cache (`kbuildsycoca6` after creating it), and must be
registered with the daemon (`doRegister` + `setForeignShortcut` on
`org.kde.kglobalaccel`). Miss any of the three and the chord does nothing.
After a relogin the daemon rebuilds everything from `kglobalshortcutsrc`.

**Ring bindings** live in `kcminputrc` as
`[ButtonRebinds][TabletRing][<pad device name>][<mode>]` with
`0=AxisKey,<up chord>,<down chord>,<threshold>` - threshold 120 fires every
~5 degrees of ring travel, 360 every ~15.

**The pen's screen position is not exposed to scripts.** KWin's scripting
`workspace.cursorPos` is hardwired to the mouse. Two usable sources instead,
best first: the kernel's evdev state (`EVIOCGABS`, always fresh while the
pen is in proximity - needs the udev `uaccess` rule), and XWayland's stylus
device (XInput2 valuators in desktop coordinates - fresh only while the pen
hovers an X11 window).

**The mouse pointer and the pen cursor are two different things.** KWin
keeps a pointer position for the mouse and a separate cursor for the
tablet. Everything that asks the compositor for "the pointer" gets the
mouse: `workspace.cursorPos` in KWin scripts, and Kando's KWin backend,
which uses that same call. A pie opened from a pad button lands where the
mouse was last left. The fix is to move the mouse onto the pen first. The
logged-in user may write `/dev/uinput` on Kubuntu (udev tags it `uaccess`),
so `tablet-pointer-warp.py` creates a virtual absolute mouse, sends one
motion, and removes it again, all in about 150 ms - no root, no portal
dialog. libinput maps the motion as a fraction of the axis range, so the
pointer lands on the same physical spot at any display scale.

**A sleeping monitor removes the output.** When a DisplayPort monitor goes
to standby, the link drops, KWin removes the output and runs a
`Placeholder-1` screen of 1920x1080. `workspace.virtualScreenSize` and
`cursorPos` then refer to that placeholder, Qt clients report "There are no
outputs", screenshots come back empty, and Xwayland keeps the old screen
size. Positions read while the monitor sleeps live in a space that does not
exist. (Plasma 6.6, September 2026.)

**The kernel does not expose the ExpressKey touch sense.** The Intuos Pro's
keys report a resting finger before the press - Wacom's "Express View".
The kernel's Bluetooth pad parser (`wacom_intuos_pro2_bt_pad`) reads only
bytes 281, 282 and 285 of report 0x80 (keys, centre button, ring), and the
`EXPRESSKEYCAP` HID usage has no mapping. The only way to get it is to read
the raw reports from `/dev/hidraw*` next to the kernel driver
(`tablet-pad-probe.py`, `tablet-hover.py`).

**Overlays that must not eat input**: a Qt window with
`Qt.WindowTransparentForInput` on the layer-shell overlay layer
(`org.kde.layershell` QML module) covers the screen, stays click-through,
and survives everything except its own process exit.

**One-shot KWin scripts** are the escape hatch for anything only the
compositor knows: load JS via `org.kde.kwin.Scripting`, `print()` the
answer, read it back from `journalctl --user -u plasma-kwin_wayland`.
