# plasma-wacom-center: technical notes

How the toolkit works, for a reader who wants to change it or port it. The
README says what it does. `PROJECT_MAP.md` lists every file, process,
runtime file and chunk marker. `KNOWLEDGE.md` holds the facts that each
cost a debugging session. Written for plasma-wacom-center v2 on Plasma 6.6,
September 2026.

## The pieces

| File | Role |
|---|---|
| `tablet-precision.sh` | the toggle, and the only writer of the pen mapping. Modes: `toggle`, `resize`, `where`, `suspend`, `resume` |
| `tablet-pen-pos.py` | the pen position on the screen, in pixels |
| `tablet-overlay.py` + `tablet-overlay.qml` | the dim overlay. One drawing for every rectangle the toolkit shows |
| `tablet-hover.py` | the ExpressKey daemon: the touch preview, the key learning, the area drag, the long press |
| `tablet-precision-size.sh` | one ring tick |
| `tablet-size-preview.py` | the size preview, with precision mode off |
| `tablet-pie.sh` + `tablet-pointer-warp.py` | the pie menu under the pen |
| `wacom_center.py` | the settings window |
| `tablet-pad-probe.py` | prints the touch and press bytes of an unknown tablet |
| `install.sh` | the deploy: scripts, shortcuts, autostart, the ring binding |

No compiled code, no kernel module. One daemon (`tablet-hover.py`), started
by an autostart entry. Everything else is one process per key press.

## Precision mode

KWin owns the tablet mapping. Each input device is a D-Bus object under
`org.kde.KWin /org/kde/KWin/InputDevice/eventN`. Its `outputArea` property
holds the mapped screen rectangle as fractions. Event numbers change on
every Bluetooth reconnect. So the toggle finds the pen by its `tabletTool`
property, caches the sysname in the runtime directory and confirms it with
one call per run.

A run reads the pen position, computes the area, writes `outputArea`, then
spawns or moves the overlay. About 150 ms. Toggle OFF restores the mapping
saved at ON, not blindly the full screen.

### The placement rule

<p align="center"><img src="docs/placement.svg" width="880" alt="The placement rule in three cases: pen at the centre, off-centre, and in a corner"></p>

The placement keeps the cursor where it is:

    w = sw * SCALE
    h = w / aspect
    x = cx / sw * (sw - w)
    y = cy / sh * (sh - h)

`sw, sh` is the screen size, `cx, cy` is the pen position in screen pixels,
`SCALE` is the conf value (0.05 to 0.80 of the screen width) and `aspect`
is the tablet's own width / height, read from the device's `size` property.
Wacom's Windows driver uses the same rule. Near a screen border the area
drifts slower than the cursor, and it never leaves the screen.

A resize (the ring, mode on) keeps the area's own centre:
`x = clamp(cx - w/2, 0, sw - w)`, with `cx, cy` the centre on record. The
size preview (the ring, mode off) sits at the centre of the screen.

### The pen position

`tablet-pen-pos.py` tries three sources, best first:

1. The kernel's evdev state of the pen node (`EVIOCGABS`). Fresh whenever
   the pen is in proximity. Needs the udev `uaccess` rule from the install.
2. XWayland's stylus device (XInput2 valuators). Fresh only while the pen
   hovers an X11 window.
3. The mouse, through a one-shot KWin script. The last fallback.

Right after a Bluetooth reconnect, evdev reports 0,0 until the pen first
hovers the tablet.

## The overlay

`tablet-overlay.qml` is one drawing: four dim bands around the clear area
and a 2 px amber border inside it. It is a full-screen layer-shell window
on the overlay layer, transparent for input, so it never eats a click.
Precision mode has the solid border. Every preview has the waiting look:
the same bands, with the border as 5 px dashes that flow clockwise, one
period per 0.3 s. The previews are the ghost (a finger on the key, mode
off), the size preview (a ring tick, mode off) and the dragged area (mode
on).

The toggle spawns the overlay once per ON with
`--fifo $XDG_RUNTIME_DIR/tabprec/overlay.fifo` and then moves it through
that named pipe. The line `X Y W H [DIM]` moves it. The lines `waiting` and
`solid` switch the border. A resize or a move never respawns it. The overlay
opens the pipe `O_RDWR`, so writers come and go without an EOF.

## The ring

`install.sh` binds the ring in `kcminputrc`:

    [ButtonRebinds][TabletRing][<pad name>][0]
    0=AxisKey,Meta+Shift+F10,Meta+Shift+F9,600

The threshold is not in degrees. KWin multiplies the degrees travelled since
the last tick by 120 and fires one chord when the product reaches the
threshold. The Intuos Pro ring reports 5-degree steps, so a threshold up to
600 fires on every step (72 ticks per turn) and 1800 fires every 15
degrees. Wacom Center shows the threshold as degrees and rewrites the
binding.

Each tick runs `tablet-precision-size.sh up` or `down` once. The script adds
or removes `RING_STEP` percentage points (conf, default 0.5), clamps
`SCALE` to 0.05 to 0.80 and rewrites the conf in place. With the mode on it
calls `tablet-precision.sh resize`. With the mode off it starts the size
preview, one per spin. A tick while the area is dragged (a relocate marker
under 3 s old) does nothing.

A fast swipe puts a dozen ticks in flight, one process each. Two rules make
the queue collapse. The toggle reads the conf after it takes the lock, so a
queued run applies the newest `SCALE`. A resize whose width is already on
screen exits at once. libinput counts ring degrees counter-clockwise. The
"Swap the ring direction" box in Wacom Center exchanges the two chords.

## The pie menu

Kando asks KWin for the pointer and gets the mouse. KWin keeps a separate
cursor for the pen. So a pie opened from a pad key lands where the mouse
was last left. `tablet-pie.sh` reads the pen position, moves the mouse
there with `tablet-pointer-warp.py`, then runs `kando --menu "<name>"`.
Without a pen position (tablet asleep, no udev rule) it runs `kando --menu`
at the mouse.

`tablet-pointer-warp.py` creates a short-lived virtual absolute mouse on
`/dev/uinput`, sends one motion as a fraction of the axis range, holds
50 ms and removes it. About 150 ms, no root, no portal dialog. It needs
write access to `/dev/uinput`. Kubuntu tags the node `uaccess` for the
logged-in user. Elsewhere, add a udev rule:

    KERNEL=="uinput", TAG+="uaccess"

The menu name is the first argument. `install.sh` writes
`tablet-pie.sh Krita` into
`~/.local/share/applications/net.local.tabpie.desktop`. Edit the `Exec`
line of that file to open another menu. `examples/kando-krita-menu.json` is
a Kando menu file with a Krita menu.

## The ExpressKey touch preview and the area drag

The Intuos Pro's pad keys report a resting finger before the press. The
kernel does not expose it: the Bluetooth pad parser reads only the key,
centre-button and ring bytes, and the `EXPRESSKEYCAP` HID usage has no
mapping. `tablet-hover.py` reads the raw HID reports from every Wacom
`/dev/hidraw*` node, next to the kernel driver. The udev rule from the
install tags the nodes `uaccess` (USB `0003:056A:*`, Bluetooth
`0005:056A:*`).

### Report layouts

Built into `tablet-hover.py` (the `MODELS` and `FAMILIES` tables). Key N is
bit N-1, so key 8 is `0x80`.

| Model | Product id | Bus | Report | Touch byte | Press byte |
|---|---|---|---|---|---|
| Intuos Pro S (PTH-460) | 0392 | USB | 0x11 | 2 | 1 |
| Intuos Pro S | 0393 | Bluetooth | 0x80 | 283 | 282 |
| Intuos Pro M (PTH-660) | 0357 | USB | 0x11 | 2 | 1 |
| Intuos Pro M | 0360 | Bluetooth | 0x80 | 283 | 282 |
| Intuos Pro L (PTH-860) | 0358 | USB | 0x11 | 2 | 1 |
| Intuos Pro L | 0361 | Bluetooth | 0x80 | 283 | 282 |

The M size is the one measured. S and L share the family, so the daemon
uses the same layout for them.

For a Wacom model the daemon does not know, run `tablet-pad-probe.py` once
per connection type. It prints each byte that changes, with the node, the
bus and the report id. Put the values into `~/.config/tabprec.conf` as
`HOVER_REPORT_USB`, `HOVER_BYTE_USB` and `PRESS_BYTE_USB`, and the same
with `_BT`. `HOVER_MASK_USB` and `PRESS_MASK_USB` (and `_BT`) override the
learned key. Only keys with a touch sensor can do this (Intuos Pro, Cintiq
Pro, MobileStudio Pro). On other tablets the daemon idles.

### Learning the precision key

The daemon learns which key is the precision key. It watches for a single
key press followed within 2 s by a toggle of precision mode. The pressed
key is the precision key. The daemon saves its bit to the conf as
`HOVER_MASK`.

### The ghost and the drag

With precision mode off, a finger on the precision key shows the ghost.
`tablet-precision.sh where` prints the area a toggle would map now, and a
`tablet-overlay.py --waiting --follow` draws it and follows the pen at
30 Hz.

With precision mode on, a finger held for `HOLD` seconds starts a drag:

1. The daemon runs `tablet-precision.sh suspend`. The base mapping comes
   back and the cursor roams the whole screen.
2. The daemon sends `waiting` to the overlay's pipe and moves the real
   overlay after the pen with the placement rule.
3. The daemon touches the marker file `$XDG_RUNTIME_DIR/tabprec/relocate`
   and refreshes it at 30 Hz.
4. On a press, KWin runs the toggle. A marker younger than 3 s means MOVE,
   not OFF. The toggle maps the area at the pen. The daemon sends `solid`.
5. On a lift without a press, the daemon removes the marker, sends `solid`
   and runs `tablet-precision.sh resume`. The old area comes back.

The daemon never deletes the marker on the press. Its hidraw report reaches
it about 100 ms before KWin's shortcut starts the toggle, so a deleted
marker would turn the move into an OFF. It stops refreshing the marker
instead, and the toggle accepts only a marker under 3 s old.

### The long press

`HOLD` has no floor. At 0 s every touch starts a drag at once and every
press is a move. The way out is the long press. Keep the key pressed for
`LONG` seconds after a press that confirmed a drag, and the daemon runs
`tablet-precision.sh toggle` again, which is OFF. `LONG` 0 disables the
long press.

The area lands at the press first, because KWin fires the toggle on the
key-down. The toggle script serializes its runs with `flock` on
`$XDG_RUNTIME_DIR/tabprec/lock`, so the two runs land in a row whatever
their timing.

| Precision mode | On the precision key | Result |
|---|---|---|
| off | press | the mode comes on, the area around the cursor |
| off | rest a finger | the ghost shows where the area would go, following the pen |
| on | press before `HOLD` has passed | the mode goes off |
| on | rest for `HOLD`, then press | the area moves to the pen |
| on | rest for `HOLD`, lift without pressing | nothing changes |
| on | rest for `HOLD`, press and keep the key down for `LONG` | the area moves, then the mode goes off |

### Timings

| What | Value |
|---|---|
| ghost debounce | 0.06 s |
| drag hold | `HOLD`, no floor, default 0.15 s |
| long press | `LONG`, default 0.7 s, 0 = never |
| pen poll while following | 30 Hz |
| conf and hidraw node rescan | 2 s |
| key-learn window | 2 s |
| marker freshness | 3 s |
| pipe write timeout | 1 s |
| lock wait | 5 s |
| size preview hold, then fade | 1.2 s, then 0.45 s |
| dash flow | 0.3 s per period |

## Settings reference

The conf is `~/.config/tabprec.conf`. Every writer keeps the lines it does
not own. The daemon re-reads it within 2 s. The toggle reads it on every
run.

| Key | Meaning | Default | Written by |
|---|---|---|---|
| `SCALE` | area width as a fraction of the screen width, 0.05 to 0.80 | 0.36 | Wacom Center, the ring |
| `DIM` | dim strength outside the area, 0 to 0.8 | 0.10 | Wacom Center |
| `HOLD` | seconds a resting finger waits before a drag, 0 = at once | 0.15 | Wacom Center |
| `LONG` | seconds a press that confirmed a drag stays down to leave the mode, 0 = never | 0.7 | Wacom Center |
| `RING_STEP` | percentage points of screen width per ring tick | 0.5 | Wacom Center |
| `HOVER_MASK` | the precision key's bit | learned | the daemon |
| `HOVER_REPORT_<BUS>`, `HOVER_BYTE_<BUS>`, `PRESS_BYTE_<BUS>`, `HOVER_MASK_<BUS>`, `PRESS_MASK_<BUS>` | report layout overrides for an unknown model, `<BUS>` = `USB` or `BT` | none | you, from the probe |

The ring binding lives in `kcminputrc`, not in the conf (see "The ring").

`install.sh` registers four global shortcuts and creates the launcher
entries in `~/.local/share/applications/`:

| Shortcut | Entry | Runs |
|---|---|---|
| `Meta+Shift+F12` | `net.local.tabprec-toggle.desktop` | `tablet-precision.sh` |
| `Meta+Shift+F11` | `net.local.tabpie.desktop` | `tablet-pie.sh Krita` |
| `Meta+Shift+F10` | `net.local.tabprec-bigger.desktop` | `tablet-precision-size.sh up` |
| `Meta+Shift+F9` | `net.local.tabprec-smaller.desktop` | `tablet-precision-size.sh down` |

A command shortcut needs all three: `X-KDE-GlobalAccel-CommandShortcut=true`
in the entry, `kbuildsycoca6`, and `doRegister` + `setForeignShortcut` on
the shortcut daemon. `install.sh` does all three. After a relogin the
daemon rebuilds them from `kglobalshortcutsrc`.

Pad and ring chords: F-keys and modifiers only. KWin resolves a letter
through the active keyboard layout, so `Meta+Shift+P` sends nothing under a
Cyrillic layout.

The udev rule `install.sh` prints (`/etc/udev/rules.d/70-tablet-access.rules`):

    SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="*Pen*", TAG+="uaccess"
    KERNEL=="hidraw*", KERNELS=="0003:056A:*|0005:056A:*", TAG+="uaccess"

The first line gives the pen position (evdev). The second gives the touch
sense (hidraw). Without the rule, precision mode centres on the mouse and
the daemon idles.

Runtime files live in `$XDG_RUNTIME_DIR/tabprec/`. `PROJECT_MAP.md` lists
them with their writers and readers.

## Limitations, in detail

- Single monitor. The placement math uses the virtual screen, and
  `outputArea` fractions are per mapped output. With two outputs the area
  lands wrong. A fix computes in the mapped output's space.
- Display scale. The overlay takes pixel positions from the X screen and
  draws in Qt's logical pixels. At 100 % both are the same space. Nobody
  has tested other scales.
- Base mapping. The placement assumes the default full-tablet stretch.
  Toggle-off restores a letterboxed mapping from the Display page
  correctly, but the cursor-stationary placement drifts.
- Bluetooth reconnect. Before the pen first hovers, evdev reports 0,0 and a
  toggle lands the area top-left.
- Stylus click-to-focus between windows does not work in Plasma 6.6 (KDE
  bug 498386 and friends). The bug is upstream.
- A sleeping DisplayPort monitor removes the output. KWin runs a 1920x1080
  placeholder, and every position read then is invalid. See `KNOWLEDGE.md`.
- This project does not support X11 sessions. `xsetwacom` covers the
  mapping there.

## Tests

`tests/run_all.sh` runs every gate in about a minute. It needs Python 3 and
bash only: no Qt, no tablet, no KWin. Exit 0 = all green.

| Gate | What it checks |
|---|---|
| `py_compile`, `bash -n` | every Python file compiles, every shell script parses |
| `tests/check_map.py` | every chunk marker has a bullet in `PROJECT_MAP.md`, and every bullet names a marker |
| `tests/test_script.sh` (36 checks) | the toggle: on, move, resize around the centre with the clamp, suspend, resume, off, the run lock. A stubbed `busctl`, a fake pen reader, a fake overlay |
| `tests/test_size.sh` (19 checks) | the ring script: the step and its clamps, `RING_STEP` from the conf, resize only with the mode on, the preview only with it off, nothing while the marker is fresh |
| `tests/test_hover.py` (36 checks) | the daemon: a named pipe plays the pad, a fake pen, fake overlays, a fake toggle. The ghost, the drag, `waiting` and `solid`, a conf edit mid-rest, `HOLD` 0, the long press and what must not arm it |

Not part of the gate: `tests/smoke_center.py` builds the Precision tab
offscreen and prints the fields and the conf write (needs PyQt6).
`tests/add_markers.py` puts a chunk marker above every new def, function or
mode (idempotent).
