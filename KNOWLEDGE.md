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
`0=AxisKey,<up chord>,<down chord>,<threshold>`. The threshold is NOT in
degrees: KWin takes the degrees travelled since the last tick, multiplies
them by 120 (the mouse-wheel notch convention) and fires one chord when
that reaches the threshold, then restarts from the current position. The
Intuos Pro ring reports 5-degree steps, so any threshold up to 600 fires on
every step (72 ticks per turn) and 1800 fires every 15 degrees. An earlier
version of this note said 120 was 5 degrees and 360 was 15; it was wrong.

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

**A warp racing KWin's own chord loses; a chord sent after the warp on the
same device cannot.** A pad key bound in `kcminputrc` fires its chord
INSIDE KWin's handling of the pad button, in the same pass of the event
loop: `busctl monitor` shows KWin's `globalShortcutPressed` signal, then
Kando's `loadScript` 0.6 ms later and `run` (the `workspace.cursorPos`
read) 1.2 to 2.2 ms after the signal. A warp started from the same HID
report needs a userspace round trip (select wake, evdev reads, uinput
writes, libinput, back into KWin) and landed 1 to 4 ms after that read -
the pie opened one press behind, every press (2026-09-09). The touch sense
cannot close the race either: over Bluetooth it led only 3 presses of 7,
and the pen kept moving after the finger landed, so the early warp was
itself stale. The fix is structural, not temporal: conf `CHORD_<n>` sets
the pad key to `Disabled` in kcminputrc and the daemon presses the chord
itself right after the warp on the SAME virtual device - the kernel,
libinput and KWin process one device's events in write order, so the
motion is in place before the chord triggers anything. `Disabled`, not a
deleted entry: KWin hands an unbound pad button to a tablet-aware app over
the tablet-pad protocol. The daemon keeps that one device for its whole
life: creating one per press would spend milliseconds on KWin's device
enumeration, and the chord's keys must already be registered.

**The kernel drops an unchanged ABS value.** `input_handle_abs_event`
ignores an `ABS_X` whose value equals the axis's current one. A long-lived
virtual mouse that warps to the spot of its previous warp sends a frame
with no events, and the pointer stays wherever the real mouse moved it
since. Send a first frame one unit away, then the real one.

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

**Moving a running overlay from other processes**: give it a named pipe
and open the pipe `O_RDWR | O_NONBLOCK` on the reading side. A read-only
open hits EOF, and a spinning read notifier, as soon as the last writer
closes; with the reader also holding a write end, writers come and go
(`echo "X Y W H" > pipe` from the shell, `os.write` from the daemon), and
lines under `PIPE_BUF` stay whole. Wrap the shell write in `timeout` for
the case of a reader that died.

**Two processes see one button press, at different times.** The pad's raw
hidraw report reaches the hover daemon milliseconds before KWin's shortcut
even starts the toggle script, so the daemon must not delete its "this
press is a move" marker on the press. It stops refreshing the marker
instead, and the script accepts only a marker younger than 3 s. A stale
marker is then harmless by construction.

**One-shot KWin scripts** are the escape hatch for anything only the
compositor knows: load JS via `org.kde.kwin.Scripting`, `print()` the
answer, read it back from `journalctl --user -u plasma-kwin_wayland`.

**A dashed border that flows** is a `QtQuick.Shapes` path with
`strokeStyle: ShapePath.DashLine` and an animated `dashOffset` (a
`Rectangle` border cannot be dashed at all). Two facts the docs leave you
to find: the dash pattern and the offset are in units of the pen WIDTH, not
pixels (`[2.5, 2.5]` at width 2 is 5 px on, 5 px off), and a GROWING
offset moves the dashes BACKWARD along the path - to flow clockwise around
a rectangle drawn clockwise, animate the offset from one period down to 0.
Use `capStyle: ShapePath.FlatCap`, or the default square caps stretch every
dash by a pen width at each end. `qml6-module-qtquick-shapes` is a
dependency of plasma-desktop, so it is on every Plasma 6 system.

**Two runs of the same script can overlap.** A long press on the pad key
means KWin's shortcut runs the toggle on the key-down and the daemon runs
it again later; with a short long-press time they overlap, and two
interleaved runs leave the mapping set by one and the state files removed
by the other. `flock` on a runtime file at the top of the script
(`exec 9>lock; flock -w 5 9`) serializes them, with one trap: the overlay
the script spawns with `nohup … &` inherits descriptor 9 and would hold
the lock for as long as it lives. Close it on the spawn (`9>&-`).

**A shortcut-driven ring tick is a process, and processes queue.** KWin
fires the chord on every 5-degree step, the shortcut daemon launches the
script for each one, and a quick swipe puts a dozen in flight while each
needs about 100 ms of D-Bus work; serialized by a lock they run one after
another and the area keeps stepping after the finger has stopped. Two
rules make the queue collapse: read the setting AFTER taking the lock, so
a queued run applies the newest value, and do nothing when what is on
screen already matches, so the rest of the queue drains in milliseconds.
Cache the device lookup as well: asking KWin for the name of each of a
dozen devices costs more than the resize itself.

**Rendering a layer-shell QML file without a display** works for tests:
`QT_QPA_PLATFORM=offscreen`, load it, `grabWindow()` on the root
(LayerShellQt only warns "not a wayland window"). In PyQt6 the root comes
back as a plain `QWindow` without `grabWindow` unless `PyQt6.QtQuick` is
imported somewhere first.
