# plasma-wacom-center

Precision mode for drawing tablets on KDE Plasma 6 (Wayland), like the one
in Wacom's own driver on Windows. It comes with a pie menu that opens under
the pen and a small settings window.

Wacom has no Linux driver. Plasma's Drawing Tablet page sets the mapping,
the pressure curve and the buttons, but it has no precision mode. This
project adds it with a few small scripts. There is nothing to compile.

Built and tested on Kubuntu 26.04 with Plasma 6.6 and a Wacom Intuos Pro M
over Bluetooth. Any tablet that Plasma's Drawing Tablet page recognizes
works. The touch preview and the area drag need a Wacom tablet with
touch-sensitive pad keys (Intuos Pro, Cintiq Pro, MobileStudio Pro).

## What it does

- **Precision mode.** Press a pad key. The pen now maps to a small area
  around the cursor, for detail work. Press the key again to get the full
  screen back. The cursor does not jump, and the screen outside the area
  dims. The area has the shape of your tablet, so your strokes keep their
  proportions.
- **Ring size control.** Turn the touch ring to make the area bigger or
  smaller. With precision mode off, a preview shows the new size. With it
  on, the area itself grows or shrinks in place.
- **Touch preview.** Rest a finger on the precision key. A ghost shows where
  the area will land, and it follows the pen.
- **Area drag.** With precision mode on, rest a finger on the precision key
  and move the pen. The area follows the pen. Press the key to put the area
  there. Keep the key pressed to leave precision mode.
- **Pie menu under the pen.** A pad key opens a [Kando](https://kando.menu)
  pie menu at the pen, not where the mouse was left.
- **Wacom Center.** A settings window for the area size, the dim strength,
  the hold and long-press times, the ring, and the pad keys.

Precision mode has a solid amber border. A preview has a dashed border that
moves.

## In pictures

https://github.com/user-attachments/assets/5c04b1b3-ea14-4669-b458-18271664d768

<p align="center"><img src="docs/screenshot-precision-mode.png" width="880" alt="Precision mode on: a reference photo in Gwenview on the left, Krita on the right, and a tablet-shaped area with an amber border over the Krita canvas"></p>

Precision mode on, with a reference photo in Gwenview and the drawing in
Krita. The pen maps to the area with the amber border. The rest of the
screen dims. The cursor did not move when the mode came on.

<p align="center"><img src="docs/screenshot-wacom-center-precision.png" width="400" alt="Wacom Center, Precision tab"> <img src="docs/screenshot-wacom-center-pad.png" width="400" alt="Wacom Center, Pad buttons tab"></p>

Wacom Center. Left, the Precision tab. Right, the Pad buttons tab.

## Requirements

- KDE Plasma 6.5 or newer, on Wayland. This project does not work on X11.
  On X11, use `xsetwacom` instead.
- Two Python packages. Everything else is part of a standard Plasma desktop.
- [Kando](https://kando.menu), if you want the pie menu.

```
sudo apt install python3-pyqt6 python3-pyqt6.qtquick
```

## Install

1. In a terminal, run:

   ```
   git clone https://github.com/lugi-ow/plasma-wacom-center
   cd plasma-wacom-center
   ./install.sh
   ```

   The installer copies the scripts to `~/.local/bin` and creates the
   shortcuts. It adds the touch preview to autostart and offers to bind
   the touch ring. At the end it prints the steps that need you.

2. Run the `sudo` command the installer prints. It adds one permission
   rule, so the scripts can read the pen position and the touch sense of
   the pad keys.

3. In System Settings, open Drawing Tablet, then the Pad tab.

4. Press the pad key you want as the precision key.

5. Choose "Send keyboard key".

6. Press `Meta+Shift+F12`.

7. For the pie menu, bind a second pad key to `Meta+Shift+F11` the same way.

8. Log out and log in again. This starts the touch preview and makes the
   shortcuts work.

Bind pad keys to F-keys and modifiers only. A letter does not work while a
non-Latin keyboard layout is active.

## The precision key

The precision key is the pad key bound to `Meta+Shift+F12`. On a Wacom
Intuos Pro (2017 or later) the pad keys sense a finger that rests on them,
before the press. Wacom calls these keys ExpressKeys. The touch preview and
the area drag use that sense.

There is nothing to set up. After the install, press the precision key
once. From then on the toolkit knows which key it is.

| Precision mode | What you do | What happens |
|---|---|---|
| off | press the key | precision mode comes on, around the cursor |
| off | rest a finger on the key | a ghost shows where the area will land, and follows the pen |
| on | press the key at once | precision mode goes off |
| on | rest a finger for the hold time, then press | the area moves to the pen |
| on | rest a finger, then lift it without a press | nothing changes |
| on | rest a finger, press, and keep the key down for the long-press time | the area moves, then precision mode goes off |

The hold time and the long-press time are the two time fields in Wacom
Center. With the hold time at 0, every press is a move, and the long press
is the way out of precision mode.

## Settings

Open Wacom Center from the application menu, in the Settings category.
The Precision tab has the area size (5 to 80 % of the screen width), the
dim strength, the hold time, the long-press time, the ring step, the tick
angle, and a switch for the ring direction. The Pad buttons tab sets the
key chord each pad key sends.

## Pie menu

Plasma has no pie menus. [Kando](https://kando.menu) adds them, and it
works on Plasma Wayland. `examples/kando-krita-menu.json` is a Kando menu
file with a Krita menu: brush, transform, selection tools, and a canvas
rotation reset. The pad key bound to `Meta+Shift+F11` opens the menu named
`Krita` under the pen. `TECHNICAL.md` says how to open a different menu.

## Known limitations

- One monitor. With two monitors the area lands in the wrong place.
- Display scale 100 % only. Nobody has tested other scales.
- Keep the tablet mapped to the full screen in System Settings. With a
  custom mapping, precision mode still turns off correctly, but the area
  can land away from the cursor.
- After a Bluetooth reconnect, hover the pen over the tablet once before
  you turn precision mode on. Otherwise the area lands in the top-left
  corner.
- The touch preview and the area drag need pad keys with a touch sensor
  (Wacom Intuos Pro, Cintiq Pro, MobileStudio Pro). On other tablets the
  toggle, the ring and the pie menu still work.
- A pen click does not move the focus to another window. This is a Plasma
  6.6 bug (KDE bug 498386), not something this project can fix.

## For contributors and AI agents

- `TECHNICAL.md` says how the toolkit works: the placement rule, the
  overlay, the ring, the touch preview, the settings and the tests.
- `PROJECT_MAP.md` lists every file, process and runtime file, and every
  chunk marker (`# ── chunk: <name>`), so you can grep instead of read.
- `KNOWLEDGE.md` holds the facts behind the design. Each one cost a
  debugging session.
- `tests/run_all.sh` runs every gate in about a minute, without a tablet.

## License

MIT. Built with Claude Code.
