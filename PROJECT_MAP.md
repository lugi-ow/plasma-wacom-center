# plasma-wacom-center — Project Map

Where things are, for a reader (human or model) who has not seen the code.
Files are listed in reading order. Each entry says what the file is FOR, what
it talks to, and lists its chunks: the `# ── chunk: <name>` markers
(`// ── chunk:` in QML) above every top-level def, class, bash function and
script mode, plus a few block markers in the script-style files. Grep a chunk
name to jump to it; line numbers are never used here because they drift and
markers do not. `tests/check_map.py` keeps this file and the markers in step;
`tests/run_all.sh` runs every gate.

## Processes

| Process | Started by | Lives | Talks to |
|---|---|---|---|
| `tablet-precision.sh` | the pad key's chord (a KWin global shortcut), the ring script, the hover daemon, Wacom Center | one run per call, ~150 ms | KWin D-Bus (`outputArea`), the runtime files, the overlay's pipe |
| `tablet-overlay.py` + `.qml` | the toggle (the precision overlay, `--fifo`), the daemon (the ghost, `--waiting --follow`) | precision: ON to OFF; ghost: touch to lift | its pipe or its stdin |
| `tablet-hover.py` | the autostart entry (install.sh) | always | every Wacom hidraw node, the pen's evdev node, the toggle (`where`, `suspend`, `resume`, `toggle` on a long press), the overlay pipe, the conf |
| `tablet-precision-size.sh` | the ring's two chords | one run per tick | the conf (SCALE, RING_STEP), the relocate marker, the toggle (`resize`, mode on) or the size preview (mode off) |
| `tablet-size-preview.py` (+ `tablet-overlay.qml`) | the ring script, mode off, when none is running | until 1.2 s after the last conf change, or at once when the mode comes on | the conf (mtime), the state file |
| `tablet-pie.sh` → `tablet-pointer-warp.py` → `kando` | a pad key's chord | one run | `/dev/uinput`, KWin's device list |
| `wacom_center.py` | the launcher entry | a window | the conf, `kcminputrc`, the toggle |
| `tablet-pad-probe.py` | you, in a terminal | until Ctrl+C | hidraw |

Who ends what: the toggle kills the precision overlay through `overlay.pid`;
the daemon terminates its own ghost; the size preview quits by itself; nothing
else is killed by anything.

## Contracts

Runtime files live in `$XDG_RUNTIME_DIR/tabprec/` (`$RD` below). The conf is
`~/.config/tabprec.conf`; every writer keeps the lines it does not own.

| Thing | Written by | Read by | Content / meaning |
|---|---|---|---|
| `$RD/saved-area` | toggle ON | toggle OFF, `suspend`; the daemon, the ring script, the size preview (exists = precision ON) | the base mapping `FX FY FW FH` |
| `$RD/area` | `apply_area` (ON, resize, move) | `resize` (its centre), the daemon's drag, `resume` | `X Y W H DIM SW SH FX FY FW FH` of the current area |
| `$RD/overlay.pid` | `apply_area` | `apply_area` (alive?), toggle OFF (kill) | pid of the precision overlay |
| `$RD/overlay.fifo` | created by the overlay (`--fifo`, held O_RDWR); written by `apply_area` and the daemon | the overlay | lines `X Y W H [DIM]` (move), `waiting` / `solid` (the border); applied in order, under PIPE_BUF |
| `$RD/relocate` | the daemon: touched at the hold, then at 30 Hz while dragging; removed on a cancel | the toggle: younger than 3 s = MOVE instead of OFF; the ring script: younger than 3 s = the tick does nothing | its mtime is the message; never deleted on a press |
| `$RD/lock` | every run of the toggle script (`flock`) | — | one run at a time; the spawned overlay closes the descriptor (`9>&-`) |
| `$RD/pen` | the toggle, after a walk over KWin's device list | the toggle (every run that needs the pen) | the pen's KWin sysname; one `name` call confirms it, a stale one triggers a new walk |
| `$RD/preview.pid`, `overlay.log`, `preview.log`, `probe.js` | the ring script / the toggle | the ring script / nobody | housekeeping |
| conf `SCALE` | Wacom Center, the ring script | the toggle (every run), the size preview | 0.05–0.80 of the screen width |
| conf `DIM` | Wacom Center | the toggle, the size preview | 0–0.8 |
| conf `HOLD` | Wacom Center | the daemon (re-read within 2 s) | seconds a resting finger waits before a drag; no floor (0 = at once), default 0.6 |
| conf `LONG` | Wacom Center | the daemon (re-read within 2 s) | seconds a press that confirmed a drag stays down to leave the mode; 0 = never, default 1.0 |
| conf `RING_STEP` | Wacom Center | the ring script | percentage points of screen width per ring tick; default 2 |
| `kcminputrc` `[ButtonRebinds][TabletRing][<pad>][0]` `0=AxisKey,<up>,<down>,<threshold>` | Wacom Center (tick angle, direction), install.sh (600) | KWin | threshold = degrees per tick × 120; the ring reports 5° steps, so ≤ 600 = every step (72 ticks a turn) |
| conf `HOVER_MASK` | the daemon (learned) | the daemon | the precision key's bit |
| conf `HOVER_REPORT`, `HOVER_BYTE`, `PRESS_BYTE`, `PRESS_MASK` (+ `_USB` / `_BT`) | you, for an unknown model (from the probe) | the daemon | report layout overrides |
| KWin `outputArea` | the toggle only | — | the pen's mapping; the device's `size` gives the tablet's aspect |

Placement, shared by the toggle, the ghost and the drag: `w = sw · SCALE`,
`h = w / aspect`, `x = cx/sw · (sw − w)`, `y = cy/sh · (sh − h)`, with the pen
at `cx, cy` in full-screen pixels. The cursor never moves on a toggle. A
resize (the ring, mode on) keeps the area's own centre instead:
`x = clamp(cx − w/2, 0, sw − w)` with `cx, cy` the centre on record; the
size preview (the ring, mode off) is centred on the screen.

One drawing, `tablet-overlay.qml`, for every rectangle the toolkit shows: dim
bands around the clear area and a 2 px amber border inside it. Precision mode
itself has the solid border. Every preview has the WAITING look - the same
bands, the border as 5 px dashes flowing clockwise, one period per 0.3 s:
the preview ghost (a finger resting on the key, mode off), the size preview
(a ring tick, mode off) and the PrM ghost (the real overlay while it is
dragged, mode on), which turns solid again on the press or the lift.

Timings: ghost debounce 0.06 s, drag hold `HOLD` (no floor), long press
`LONG`, pen poll 30 Hz, node and conf rescan 2 s, key-learn window 2 s,
marker freshness 3 s, pipe write timeout 1 s, lock wait 5 s, size preview
hold 1.2 s and fade 0.45 s, dash flow 0.3 s per period.

The long press: KWin fires the toggle on the key-down, so a press during a
drag always lands the area (MOVE); if the key then stays down for `LONG`,
the daemon runs the toggle again (OFF). The lock makes the two land in a
row whatever their timing.

## Files

### `tablet-precision.sh` — the toggle, and the only writer of the pen mapping
Modes `toggle` (default), `resize`, `where`, `suspend`, `resume`. Finds the pen
in KWin's device list (cached sysname, one call to confirm), reads the pen
position from `tablet-pen-pos.py` (the mouse as fallback, through a one-shot
KWin script), computes the area, sets `outputArea`, then moves or spawns the
overlay. One run at a time; a run reads the conf after taking the lock.
- **chunk: `config-and-paths`** — the D-Bus names, the runtime dir and its file names, the run lock (`flock`, 5 s wait), then the conf with defaults.
- **chunk: `note`** — notify-send wrapper; only errors notify.
- **chunk: `kload`** / **`kunload`** — load and unload the one-shot KWin script of the mouse fallback.
- **chunk: `find_pen`** — the pen's KWin sysname: the cached one (`$RD/pen`, one call confirms it) or a walk over every device; notifies and exits when there is none.
- **chunk: `area_math`** — W H from SCALE and the tablet aspect, then X Y and the fractions: `pen` = the cursor-stationary placement, `centre` = centred and clamped to the screen.
- **chunk: `compute_area`** — pen position (evdev, XWayland, then the mouse), then `area_math pen`; used by ON, a move and `where`.
- **chunk: `apply_area`** — sets the mapping computed before it, writes the area file, moves the live overlay through its pipe or (re)spawns it.
- **chunk: `resize`** — while ON: `area_math centre` on the recorded centre, then `apply_area` (the ring calls it); nothing when the width is already on screen; the pen only without a record.
- **chunk: `where`** — prints the area a toggle ON would map now, nothing changed (the ghost).
- **chunk: `suspend`** / **`resume`** — while ON: the base mapping back / the recorded area again (the daemon brackets a drag with them); `resume` computes the fractions of a 7-field area file.
- **chunk: `toggle`** — OFF→ON saves the base mapping; ON with a fresh marker = move; ON otherwise = restore, clean up, kill the overlay.

### `tablet-pen-pos.py` — "X Y SW SH" of the pen, in physical pixels
Best source first: the kernel's evdev state of the pen node (needs the udev
uaccess rule), then XWayland's stylus valuators (fresh only over X11 windows).
Exit 1 when neither works; callers fall back to the mouse. `DEBUG=1` traces.
- **chunk: `trace`** — stderr tracing under DEBUG=1.
- **chunk: `screen_size`** — the X screen size (physical pixels) and the display handle.
- **chunk: `evdev_pen_norm`** — normalized pen position from EVIOCGABS on the pen node.
- **chunk: `XIAnyClassInfo`** / **`XIValuatorClassInfo`** / **`XIDeviceInfo`** — ctypes mirrors of the XInput2 structs.
- **chunk: `xwayland_stylus_norm`** — normalized position of the first enabled stylus device, via XIQueryDevice.
- **chunk: `main-flow`** — evdev, then XWayland, then exit 1; prints pixels.

### `tablet-overlay.py` — the dim-around overlay
One process per overlay. Args `X Y W H [DIM]`; `--waiting` starts it in the
waiting look (the ghost). `--follow` moves it from stdin lines and quits on
EOF; `--fifo PATH` moves it from a named pipe any process may write, and never
quits on its own. The lines `waiting` and `solid` switch the border.
- **chunk: `args`** — argument parsing; `--fifo PATH`, `--follow` and `--waiting` are pulled out first.
- **chunk: `window`** — the Qt app, the QML engine, the root window of `tablet-overlay.qml`.
- **chunk: `place`** — sets px py pw ph (and dimval) on the root; the first placement comes from the args.
- **chunk: `input-source`** — the pipe (created here, opened O_RDWR so writers may come and go) or non-blocking stdin.
- **chunk: `on_input`** — applies `X Y W H [DIM]` and `waiting` / `solid` lines in order; EOF on stdin quits.

### `tablet-overlay.qml` — the one drawing
Root properties, set from Python: `px py pw ph` (the clear rectangle),
`dimval`, `waiting` (the flowing dashed border), `shown` (false = fade out),
`phase` (the dash offset the animation drives).
- **chunk: `overlay-window`** — full-screen layer-shell window on the overlay layer, transparent for input; the properties.
- **chunk: `fading-item`** — everything drawn sits in it; its opacity follows `shown` with a 450 ms animation.
- **chunk: `dim-bands`** — four rectangles around the clear area at `dimval` alpha.
- **chunk: `solid-border`** — the 2 px inset amber border of precision mode; hidden while waiting.
- **chunk: `waiting-border`** — the same border as a dashed `Shape` path, 5 px on / 5 px off, `dashOffset` bound to `phase`; the path runs clockwise.
- **chunk: `flow-animation`** — `phase` from 5 to 0 (one period) every 300 ms while waiting: a shrinking offset moves the dashes forward, clockwise.

### `tablet-hover.py` — the ExpressKey daemon: ghost, key learning, the drag
Reads the pad's raw hidraw reports (the kernel drops the touch sense).
Precision OFF: a finger resting on the precision key shows the ghost (the
look of the mode in the waiting style), which follows the pen. Precision ON:
a finger held for `HOLD` seconds starts a drag of the real overlay, waiting
border on, with the pen mapped to the whole screen; a press moves the area
there, a lift puts everything back. Learns the precision key from a single
press followed by a toggle. Report layouts per product id, conf keys override.
- **chunk: `log`** — stderr line with the `tablet-hover:` prefix (the journal under autostart).
- **chunk: `read_conf`** / **`conf_stamp`** / **`save_conf_key`** — the conf as a dict; its mtime; set one key keeping the rest.
- **chunk: `as_int`** — int() that accepts 0x.. and returns a default.
- **chunk: `hold_delay`** — the wait before anything moves: 0.06 s ghost debounce, or conf HOLD (no floor) with precision ON.
- **chunk: `long_delay`** — conf LONG: how long a press that confirmed a drag stays down before the mode goes off; 0 = never.
- **chunk: `FAMILIES`** / **`MODELS`** — built-in report layouts per family and bus; product id → family.
- **chunk: `layout_for`** — one node's layout: conf overrides over built-ins; mask None until learned.
- **chunk: `wacom_nodes`** — every Wacom hidraw node with its bus and product id, from sysfs.
- **chunk: `pen_open`** / **`pen_norm`** — the pen's evdev fd; its normalized position from EVIOCGABS.
- **chunk: `toggle`** — runs `tablet-precision.sh MODE` (suspend / resume / toggle) and reports success.
- **chunk: `Follower`** — the rectangle that follows the pen: `show` (ghost), `move` (drag, sends `waiting`), `follow` (tick), `hide` (cancel or confirm, sends `solid`).
- **chunk: `mask_text`** — "not learned yet" or the hex mask, for the log.
- **chunk: `watch`** — the loop: hidraw reports → touch, press, lift; the hold timer; the long-press timer (OFF through the toggle); learning; rescans; a conf edit is reloaded in place.
- **chunk: `main`** — `--simulate`, or watch forever (sleeping while no tablet is connected).

### `tablet-precision-size.sh` — one ring tick: SCALE ± RING_STEP points
- **chunk: `drag-guard`** — a relocate marker under 3 s old (the area is being dragged): exit, nothing changes.
- **chunk: `step`** — SCALE ± RING_STEP/100 (conf, default 2 points; junk = 2), clamped to 0.05–0.80.
- **chunk: `conf-write`** — rewrites SCALE and DIM in place, keeping every other line.
- **chunk: `resize-or-preview`** — mode on: `tablet-precision.sh resize` (the area itself, around its centre); off: the size preview unless one is running.

### `tablet-size-preview.py` — the centred fading size preview
Draws with `tablet-overlay.qml` in the waiting look, so it is precision mode's
own picture centred on the screen. Watches the conf's mtime at 10 Hz, redraws
on a change, fades 1.2 s after the last change and exits; fades at once when
precision mode comes on.
- **chunk: `read_conf`** — SCALE and DIM from the conf, clamped.
- **chunk: `tablet_aspect`** — width / height of the pen tablet from KWin's device list, 1.6 fallback. *(public copy only)*
- **chunk: `window`** — the Qt app, the QML engine, the root window; `waiting` set once.
- **chunk: `apply_scale`** — pixel size from SCALE and the aspect, centred; pushes px py pw ph dimval and shows.
- **chunk: `tick`** — 100 ms poll: the state file fades the preview out; a conf change cancels a pending exit and restarts the hold.
- **chunk: `start_fade`** — hides (QML fades) and arms the quit timer.
- **chunk: `timers`** — the quit, hold and poll timers.
- **chunk: `first-show`** — the initial mtime, the first draw, the first hold.

### `tablet-pie.sh` — a Kando pie under the pen
- **chunk: `warp-then-open`** — pen position → mouse warp → `kando --menu`; no position = the menu at the mouse.

### `tablet-pointer-warp.py` — move the mouse to X Y without root
A short-lived virtual absolute mouse on `/dev/uinput`: waits until KWin lists
it, sends one motion, holds 50 ms, removes it. Fractions of the axis range, so
it lands on the same physical spot on a scaled display.
- **chunk: `trace`** — stderr tracing under DEBUG=1.
- **chunk: `_IO`** / **`_IOW`** / **`_IOR`** — ioctl number encoding.
- **chunk: `uinput-constants`** — the uinput ioctls, event types and the axis range.
- **chunk: `screen_size`** — the X screen size (physical pixels) when SW SH are not given.
- **chunk: `kwin_sees`** — polls KWin's device list until the virtual node shows up.
- **chunk: `emit`** — one input_event write.
- **chunk: `main`** — create the device, wait for KWin, move, hold, destroy.

### `tablet-pad-probe.py` — find the touch and press bytes on an unknown tablet
- **chunk: `quiet-reports`** — the pen-noise regions and report ids hidden unless `--all`.
- **chunk: `wacom_nodes`** — every Wacom hidraw node with its bus and name.
- **chunk: `fmt`** — a byte as hex and binary.
- **chunk: `main`** — reads every node, prints each changed byte with node, bus and report id.

### `wacom_center.py` — the settings window
- **chunk: `paths`** — the conf path, the toggle path, and the launcher table (personal copy) or the KWin names (public copy).
- **chunk: `busget`** / **`detect_devices`** — KWin property reads; the pad name and the tablet aspect by capability. *(public copy only)*
- **chunk: `read_conf`** / **`write_conf`** — SCALE, DIM, HOLD, LONG, RING_STEP with defaults; write them keeping every other line.
- **chunk: `kread`** / **`kwrite`** — a pad key's chord in `kcminputrc [ButtonRebinds]`.
- **chunk: `ring_read`** / **`ring_write`** — the ring binding (mode 1): the two chords and the tick angle; KWin's threshold = degrees × 120; reconfigures KWin.
- **chunk: `set_launcher_shortcut`** — keeps the shortcut daemon in step with the two launcher keys. *(personal copy only)*
- **chunk: `PrecisionTab`** — the size and dim sliders, the hold and long-press fields (seconds, from 0), the ring step, tick angle and direction swap, the toggle button; saves on change.
- **chunk: `PadTab`** — one chord field per key, validation, the layout warning, apply.
- **chunk: `main`** — the window, the tabs, the two launcher buttons.

### `tests/` — the gates
`run_all.sh` runs everything (~60 s; no Qt, no tablet, no KWin): `py_compile`,
`bash -n`, `check_map.py`, then `test_script.sh` (the toggle through on, move,
resize around the centre with the clamp, suspend, resume and off, the run
lock, with a stubbed `busctl` and a fake overlay), `test_size.sh` (the ring
script: the step and its clamps, RING_STEP from the conf, the resize only
with the mode on, the preview only with it off, nothing while the marker is
fresh; a stub toggle and a fake preview) and `test_hover.py` (the daemon with a named pipe as the
pad, a fake pen, fake overlays and a fake toggle that logs its modes; the
`waiting` / `solid` lines; a conf edit mid-rest; HOLD 0; the long press and
what must not arm it). Every rig takes
`<scratch dir> <script path>`. `add_markers.py <dir> [out dir]` puts a marker
above every new def, function or mode (idempotent; block markers are listed
inside it). `smoke_center.py <wacom_center.py> <scratch dir>` builds the
Precision tab headless and checks the hold field and the conf write (needs
PyQt6).
