# plasma-wacom-center

Wacom-style **precision mode** for drawing tablets on KDE Plasma 6 (Wayland),
plus a small settings window. Wacom ships no Linux driver, and Plasma's
Drawing Tablet page covers mapping, pressure, and buttons - but not precision
mode. This project fills that gap with plain scripts on top of KWin's own
D-Bus interfaces. No daemons, no compiled code, no kernel modules.

Built and tested on Kubuntu 26.04, Plasma 6.6, with a Bluetooth Wacom Intuos
Pro M. Any tablet that Plasma's Drawing Tablet page recognizes should work -
devices are found by capability, not by model name.

## What it does

- **Precision mode toggle** (a pad button, or Meta+Shift+F12): the pen maps
  to a small rectangle around the cursor instead of the whole screen, for
  detail work. Press again to go back.
- **The cursor does not move on toggle.** The rectangle is placed with the
  rule Wacom's Windows driver uses: `rect = norm * (screen - rect)`, where
  `norm` is the pen's normalized tablet position. Near a screen border the
  area drifts slower than the cursor and can never leave the screen.
- **No stretch inside the area.** The rectangle keeps the tablet's own
  aspect ratio (read from the hardware), so your input is not distorted.
- **Dim overlay.** Everything outside the mapped area dims; the work area
  stays clear with a thin border. Click-through, on the compositor overlay
  layer. Can be adjusted in settings.
- **Ring size control.** The tablet's touch ring resizes the area in 2%
  steps (5-80% of screen width), with a centred fading preview showing the
  prospective size. Works live while precision mode is on.
- **Wacom Center**, a PyQt window: size and dim sliders, express-key chord
  editor, buttons to the pie-menu editor and the system tablet page.

## Requirements

Everything below ships with a stock Kubuntu / KDE Plasma 6.5+ install except
PyQt6:

- Plasma 6.5 or newer on Wayland (6.6 tested). X11 sessions: use `xsetwacom`
  instead, this project is Wayland-only.
- `python3-pyqt6` and `python3-pyqt6.qtquick` (overlay and settings window)
- `qml6-module-org-kde-layershell` (usually present on Plasma)

```
sudo apt install python3-pyqt6 python3-pyqt6.qtquick
```

## Install

```
git clone https://github.com/lugi-ow/plasma-wacom-center
cd plasma-wacom-center
./install.sh
```

The installer copies the scripts to `~/.local/bin`, creates and registers
three global shortcuts (Meta+Shift+F12 toggle, F10/F9 size), and offers to
bind your tablet's ring. It then prints two manual steps:

1. A one-time sudo udev rule so the scripts can read the pen's position.
   Without it, precision mode centres on the mouse cursor instead of the pen.
2. Binding a pad button to Meta+Shift+F12 in System Settings -> Drawing
   Tablet.

If the shortcuts do not fire immediately, log out and back in once.

## The knowledge (why these scripts look the way they do)

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

**Overlays that must not eat input**: a Qt window with
`Qt.WindowTransparentForInput` on the layer-shell overlay layer
(`org.kde.layershell` QML module) covers the screen, stays click-through,
and survives everything except its own process exit.

**One-shot KWin scripts** are the escape hatch for anything only the
compositor knows: load JS via `org.kde.kwin.Scripting`, `print()` the
answer, read it back from `journalctl --user -u plasma-kwin_wayland`.

## Known limitations

- Single monitor. The placement math uses the virtual screen; with two
  outputs it will misplace the area. Patches welcome.
- The base mapping is assumed to be the default full-tablet stretch. A
  letterboxed mapping set on the Display page is restored correctly on
  toggle-off, but the cursor-stationary placement will drift.
- Right after a Bluetooth reconnect, before the pen first touches the
  tablet, the kernel reports position 0,0 and a toggle lands the area
  top-left. Hover the pen once first.
- Stylus click-to-focus between windows is broken upstream in Plasma 6.6
  (KDE bug 498386 and friends) - not something this project can fix.

## Pie menus

Plasma has no on-screen pie menus; [Kando](https://kando.menu) fills that
role well on Plasma Wayland and sends physical key codes (layout-proof).
`examples/kando-krita-menu.json` is a working Krita pie: selection tools,
transform, brush, canvas rotation reset. Trigger it from a pad button via a
command shortcut running `kando --menu "Krita"`.

## License

MIT. Built with Claude Code.
