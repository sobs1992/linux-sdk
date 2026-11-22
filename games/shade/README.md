# Shade: Wrath of Angels

Black Element's third-person action game (2004, Direct3D 9, DirectInput
8) under Wine on the GO Ultra, 1C's Russian edition 1.2 ("Гнев ангелов").
The source is Kron4ek's Linux packaging, `Shade Wrath of Angels.zip`: only
`game_info/data` is used (`lab/games/Shade Wrath of Angels`), never its
own x86 Wine. `[shade]` in `games/games.manifest`; `overlay/wine.ini` is
the menu entry.

- **Screen.** `settings.cfg` at 854x480 (`prepare.sh`), the device's own
  size. 60-70 fps in the first levels, 90+ in the menus.
- **Mouse.** The engine reads it by DirectInput: `mouse = relative`. Its
  menus take the mouse as if the screen were 800x600, so the pointer moves
  a little faster across than down; the right stick is the pointer there.
  The camera's up and down are inverted (`InvertMouse 1` in `prepare.sh`,
  the user's choice: the right stick pushed up takes the camera down
  behind the hero, pushed down raises it over him). The game's
  setting turns the camera only; inverting the axis in bare_app's controls
  would turn the menus' pointer upside down as well. bare_app_wine sends the stick's
  moves 250 times a second: at 60, against the game's own 60 frames,
  some frames got two moves and some none, and the camera jerked.
- **Camera speed.** The scripts (`player.h`) turn the camera by the
  mouse's counts times `MouseSpeedH` (70: 0.1 degree a count; up and
  down `MouseSpeedV`, 40: 0.04). `cursor_speed = 6.0` turns it round in
  2.4 s with the right stick all the way out, about 150 degrees a
  second; at 2.4 it took 6 s. The game's own slider (100 at most) adds
  little. The menus' pointer is the scripts' own (`SCRIPTS/menu.h`,
  `UpdateMouse`, compiled at the game's start): `prepare.sh` moves it by
  0.6 of the mouse's moves (a USB mouse's too).
- **Saves.** `save/` and `settings.cfg` are writable copies under
  `/data/wine/games/shade`; its logs (`console.log` and the like) are
  written next to them.
- **Controls.** The PC's keys (`Readme.txt`), laid out as the SDK's
  shooters (`overlay/wine.ini`): left stick W A S D, right stick the camera
  (the mouse) and the menus' pointer, R1 and A attack (the left button; A
  also clicks in the menus), L1 block (the right button), B jump (Space),
  X use (E), Y the demon (R), L2/R2 slower and faster (the wheel: walk,
  run, sprint), D-pad the weapons 1-4 (up fist, right sword, down pistol,
  left crossbow; their spells in the demon), F1 menu (Esc), F2 crouch (C),
  F3 the claw, the skull of death (5), F4 inventory (Q). Holster (V) has
  no button: a rare action. The menus take A only when it is held a
  little (a frame or two). Esc in the main menu quits the game at once:
  `esc_delay = 30` holds the gamepad's Esc back for the first 30 s, over
  the videos (A skips them). The game's joystick setting
  (`Joypad` in `settings.cfg`: the pace by the left stick's tilt, a
  gamepad's through Wine patch 0026) was tried and left off, the user
  preferring the keys.
- **Kept out.** The uninstaller, `KillSave.exe`, the links and the logs of
  its last start on the PC.
