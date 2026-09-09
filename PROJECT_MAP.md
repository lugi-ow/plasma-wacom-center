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
| `tablet-hover.py` | the autostart entry (install.sh) | always | every Wacom hidraw node, the pen's evdev node, the toggle (`where`, `suspend`, `resume`, `toggle` on a long press), the overlay pipe, the conf + the `hover.ctl` reload pipe, one virtual device on `/dev/uinput` (the mouse onto the pen, then a key's press or touch chord) |
| `tablet-precision-size.sh` | the ring's two chords | one run per tick | the conf (SCALE, RING_STEP), the relocate marker, the toggle (`resize`, mode on) or the size preview (mode off) |
| `tablet-size-preview.py` (+ `tablet-overlay.qml`) | the ring script, mode off, when none is running | until 1.2 s after the last conf change, or at once when the mode comes on | the conf (mtime), the state file |
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
| `$RD/area` | `apply_area` (ON, resize, move) | `resize` (its centre), the daemon's drag and its warp (the fractions), `resume` | `X Y W H DIM SW SH FX FY FW FH` of the current area |
| `$RD/overlay.pid` | `apply_area` | `apply_area` (alive?), toggle OFF (kill) | pid of the precision overlay |
| `$RD/overlay.fifo` | created by the overlay (`--fifo`, held O_RDWR); written by `apply_area` and the daemon | the overlay | lines `X Y W H [DIM]` (move), `waiting` / `solid` (the border); applied in order, under PIPE_BUF |
| `$RD/relocate` | the daemon: touched at the hold, then at 30 Hz while dragging; removed on a cancel | the toggle: younger than 3 s = MOVE instead of OFF; the ring script: younger than 3 s = the tick does nothing | its mtime is the message; never deleted on a press |
| `$RD/lock` | every run of the toggle script (`flock`) | — | one run at a time; the spawned overlay closes the descriptor (`9>&-`) |
| `$RD/pen` | the toggle, after a walk over KWin's device list | the toggle (every run that needs the pen) | the pen's KWin sysname; one `name` call confirms it, a stale one triggers a new walk |
| `$RD/preview.pid`, `overlay.log`, `preview.log`, `probe.js` | the ring script / the toggle | the ring script / nobody | housekeeping |
| conf `SCALE` | Wacom Center, the ring script | the toggle (every run), the size preview | 0.05–0.80 of the screen width; default 0.36 |
| conf `DIM` | Wacom Center | the toggle, the size preview | 0–0.8; default 0.10 |
| conf `HOLD` | Wacom Center | the daemon (re-read within 2 s) | seconds a resting finger waits before a drag; no floor (0 = at once), default 0.15 |
| conf `LONG` | Wacom Center | the daemon (re-read within 2 s) | seconds a press that confirmed a drag stays down to leave the mode; 0 = never, default 0.7 |
| conf `RING_STEP` | Wacom Center | the ring script | percentage points of screen width per ring tick; default 0.5 |
| `kcminputrc` `[ButtonRebinds][TabletRing][<pad>][<mode 0–3>]` `0=AxisKey,<up>,<down>,<threshold>` | Wacom Center (Pad tab: any mode's chords; Precision tab: angle and direction, on the size pair's mode), install.sh (600) | KWin | threshold = degrees per tick × 120; the ring reports 5° steps, so ≤ 600 = every step (72 ticks a turn) |
| conf `WARP` | you | the daemon (re-read within 2 s) | `0` = no mouse warp on a touch or press; anything else or absent = warp (default) |
| conf `CHORD_<n>` | you | the daemon (re-read within 2 s) | chord (F-keys + modifiers) the daemon presses on its virtual device when pad key n goes down, released with it; key n = press-byte bit n-1, and the key stays UNBOUND in kcminputrc |
| conf `HOVER_MASK` | Wacom Center (the Precision column) | the daemon | the precision key's bit; absent = the ghost and the drag are off |
| conf `TOUCH_CHORD_<n>` | Wacom Center (the Touch box) | the daemon (on a poke) | chord held while a finger rests on key n (engages after its register, mirror release); bare modifiers allowed, never on the mask key |
| conf `TOUCH_HOLD_<n>` | Wacom Center (the Touch register column) | the daemon (on a poke) | key n's touch register in seconds; absent = `HOLD`, the default register |
| `$RD/hover.ctl` | Wacom Center (Apply, the delay row), a hand `echo reload` | the daemon (in its select loop) | any line = re-read the conf; deferred while a rectangle follows the pen |
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
`LONG`, a touch chord engages after its key's register, pen poll 30 Hz, node rescan 2 s
(hardware only; the conf reloads on a `hover.ctl` poke), marker freshness
3 s, pipe write timeout 1 s, lock wait 5 s, size preview hold 1.2 s and
fade 0.45 s, dash flow 0.3 s per period.

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
Plain, evdev is stretched over the whole screen — the space the
cursor-stationary math wants; `--mapped` puts it through the pen's live
outputArea instead, for a caller that needs the pixel the cursor is on.
- **chunk: `trace`** — stderr tracing under DEBUG=1.
- **chunk: `screen_size`** — the X screen size (physical pixels) and the display handle.
- **chunk: `evdev_pen_norm`** — normalized pen position from EVIOCGABS on the pen node.
- **chunk: `XIAnyClassInfo`** / **`XIValuatorClassInfo`** / **`XIDeviceInfo`** — ctypes mirrors of the XInput2 structs.
- **chunk: `xwayland_stylus_norm`** — normalized position of the first enabled stylus device, via XIQueryDevice.
- **chunk: `output_area`** — the pen's live outputArea from KWin (the precision rectangle) for `--mapped`; sysname from the toggle's cache, no cache or no answer = the whole screen.
- **chunk: `main-flow`** — evdev, then XWayland, then exit 1; `--mapped` puts an evdev position through the area; prints pixels.

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

### `tablet-hover.py` — the ExpressKey daemon: ghost, chords, the drag
Reads the pad's raw hidraw reports (the kernel drops the touch sense).
Precision OFF: a finger resting on the precision key shows the ghost (the
look of the mode in the waiting style), which follows the pen. Precision ON:
a finger held for `HOLD` seconds starts a drag of the real overlay, waiting
border on, with the pen mapped to the whole screen; a press moves the area
there, a lift puts everything back. The precision key = conf `HOVER_MASK`,
written by Wacom Center's Precision column (none = ghost and drag off).
Report layouts per product id, conf keys override. A finger landing on any
key warps the mouse onto the pen (one virtual device kept for life; the
press repeats it); a key with conf `CHORD_<n>` — Disabled in kcminputrc —
gets its chord pressed by the daemon right after the warp on the same
device (KWin processes the motion first, so a pie opens under the pen),
and conf `TOUCH_CHORD_<n>` is held from the key's touch register
(`TOUCH_HOLD_<n>`, `HOLD` the default) to the lift. The conf reloads on
a `hover.ctl` poke, not by polling.
- **chunk: `log`** — stderr line with the `tablet-hover:` prefix (the journal under autostart).
- **chunk: `read_conf`** — the conf as a dict, comments stripped.
- **chunk: `as_int`** — int() that accepts 0x.. and returns a default.
- **chunk: `touch_delay`** / **`hold_delay`** — key n's touch register (`TOUCH_HOLD_<n>`, `HOLD` the default) before a chord or the drag; the ghost keeps its 0.06 s debounce.
- **chunk: `long_delay`** — conf LONG: how long a press that confirmed a drag stays down before the mode goes off; 0 = never.
- **chunk: `FAMILIES`** / **`MODELS`** — built-in report layouts per family and bus; product id → family.
- **chunk: `layout_for`** — one node's layout: conf overrides over built-ins; mask None = no precision key.
- **chunk: `wacom_nodes`** — every Wacom hidraw node with its bus and product id, from sysfs.
- **chunk: `pen_open`** / **`pen_norm`** — the pen's evdev fd; its normalized position from EVIOCGABS.
- **chunk: `toggle`** — runs `tablet-precision.sh MODE` (suspend / resume / toggle) and reports success.
- **chunk: `Follower`** — the rectangle that follows the pen: `show` (ghost), `move` (drag, sends `waiting`), `follow` (tick), `hide` (cancel or confirm, sends `solid`).
- **chunk: `Warper`** — the mouse onto the pen and the chords: `ensure` (one device, retried), `warp(mapped, why)`, `chord_down`/`chord_up` (press/touch tags, after the warp), `release_all`, `close`.
- **chunk: `mask_text`** — "none" or the hex mask, for the log.
- **chunk: `watch`** — the loop: reports → warp, then `CHORD_<n>` / `TOUCH_CHORD_<n>` (the mask key exempt); the hold, touch and long-press timers; the control-pipe reload; node rescans.
- **chunk: `main`** — `--simulate`, or watch forever with one `Warper` (sleeping while no tablet is connected).

### `tablet-precision-size.sh` — one ring tick: SCALE ± RING_STEP points
- **chunk: `drag-guard`** — a relocate marker under 3 s old (the area is being dragged): exit, nothing changes.
- **chunk: `step`** — SCALE ± RING_STEP/100 (conf, default 0.5 points; junk = 0.5), clamped to 0.05–0.80.
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

### `tablet-pointer-warp.py` — move the mouse to X Y without root
A virtual absolute mouse on `/dev/uinput`: waits until KWin lists it, sends
one motion, holds 50 ms, removes it (the CLI, for one-shot debugging).
Fractions of the axis range, so it lands on the same physical spot on a
scaled display. The daemon imports it and keeps one device for life
(`create` / `warp` / `destroy`); that device also carries the chord
alphabet (modifiers + F-keys), pressed after a warp so KWin orders the
motion before the chord (`parse_chord` / `chord`).
- **chunk: `chord-keys`** — the chord alphabet: kcminputrc key names → kernel codes, modifiers and F1–F24 only; `MODIFIER_ORDER` = KWin's emission order; `CHORD_KEYS` = what `create` registers.
- **chunk: `parse_chord`** — chord text → codes: the modifiers in KWin's order, then the ONE non-modifier key; None on junk, modifier-only, or two keys.
- **chunk: `chord`** — press or release the parsed codes, one frame per key, releases reversed; written after the warp's frames, so KWin processes the motion first.
- **chunk: `create`** — the virtual mouse (`keys` adds the chord alphabet), returned once KWin lists its node: `(fd, event node)`; OSError = no `/dev/uinput`, RuntimeError = KWin never listed it.
- **chunk: `destroy`** — removes the device and closes the fd.
- **chunk: `warp`** — the pointer to a screen fraction: two frames, the first one unit off, since the kernel drops an ABS value equal to the current one.
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
- **chunk: `paths`** — the conf and control-pipe paths, the launcher table (personal copy) or the KWin names (public copy), the amber and red constants, the STE column tooltips.
- **chunk: `busget`** / **`detect_devices`** — KWin property reads; the pad name and the tablet aspect by capability. *(public copy only)*
- **chunk: `read_conf`** / **`write_conf`** — the numeric conf keys with defaults; write SCALE, DIM, LONG, RING_STEP keeping every other line (HOLD is the Pad tab's).
- **chunk: `save_conf_key`** / **`drop_conf_key`** / **`conf_value`** — one conf line set, removed, or read raw (`CHORD_<n>`); the rest kept.
- **chunk: `poke_daemon`** — one `reload` line into `hover.ctl`: the daemon re-reads the conf at once; no pipe = nothing to do.
- **chunk: `toggle_chord`** — the precision toggle's global shortcut from kglobalshortcutsrc; the documented default when missing.
- **chunk: `chord_rules`** — `parse_chord` imported from the warp module beside this file; None = the pie validation is off.
- **chunk: `kread`** / **`kwrite`** — a pad key's chord in `kcminputrc [ButtonRebinds]`; the literal `Disabled` swallows the key (what a conf `CHORD_<n>` key needs).
- **chunk: `ring_read`** / **`ring_write`** — one ring mode's binding (groups 0–3): two chords + tick angle; both empty = unbound; threshold = degrees × 120.
- **chunk: `precision_ring_mode`** — which ring mode carries the precision-size pair; (0, defaults) when none does.
- **chunk: `set_launcher_shortcut`** — keeps the shortcut daemon in step with the two launcher keys. *(personal copy only)*
- **chunk: `PrecisionTab`** — the size and dim sliders, the long-press field, the ring step, tick angle and direction swap, the toggle button; ring writes go to the size pair's mode.
- **chunk: `pad_icon`** / **`ring_icon`** — the key and ring pictures: the box with its dot/dash mark, the doughnut with mode n's light (7:30, clockwise).
- **chunk: `draw_ants`** / **`AntsLineEdit`** / **`AntsCheckBox`** / **`AntsRadio`** — the flowing dashed outline: amber = a pie side's box, red = a field precision mode consumes.
- **chunk: `PadTab`** — the pad table: key pictures, Touch + Press boxes, the per-key register (`TOUCH_HOLD_<n>`), the rings, two pie ticks per key, the round Precision tick, apply + poke.
- **chunk: `main`** — the window, the tabs (`pad` on the command line opens the second), the two launcher buttons.

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
inside it).

### `uninstall.sh` — the reverse of the installer *(public copy only)*
Stops the daemon, removes the scripts, the launcher entries and their
shortcut config; settings, the pad-key bindings and the udev rule stay,
with the paths and the one sudo line printed. Safe to re-run. No chunk
markers: the numbered steps it echoes are the map.

### `install.sh` — the installer *(public copy only)*
Five steps: the scripts into `~/.local/bin`, the `.desktop` launcher entries
with the command-shortcut marker, the four chords registered with
kglobalaccel, the optional ring binding, and the manual steps it prints (the
udev rule that needs one sudo, the pad buttons, the relogin). It also writes
the daemon's autostart entry, and is safe to re-run. No chunk markers: the
numbered steps it echoes are the map. The personal copy installs by hand.
