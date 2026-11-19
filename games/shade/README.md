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
  `prepare.sh` also turns `InvertMouse` off (Kron4ek's copy had it on):
  the right stick pushed up looks up. bare_app_wine sends the stick's
  moves 250 times a second: at 60, against the game's own 60 frames,
  some frames got two moves and some none, and the camera jerked.
- **Saves.** `save/` and `settings.cfg` are writable copies under
  `/data/wine/games/shade`; its logs (`console.log` and the like) are
  written next to them.
- **Walking.** The pace is the left stick's tilt, as on a console: the
  stick is a gamepad's (`stick = pad`, Wine patch 0026) and `prepare.sh`
  turns the engine's joypad on (`Joypad 1`, also in its settings menu).
  The game's scripts (`player.h`, `DoControl`) take a light tilt as a
  walk, more as the run, all the way as the sprint. The keyboard's pace
  (the wheel, faster and slower) is not needed; the pad's right stick and
  triggers stay at rest, so the camera is the mouse's.
- **Controls.** The PC's keys (`Readme.txt`): right stick the camera (the
  mouse), A attack, R1 block (left and right button), B jump, X use (E),
  Y crouch, L1 the demon (R), L2 the first person view (left Shift), D-pad
  the weapons 1-4, F1 menu, F2 inventory (Q), F3 holster (V), F4 the claw
  (5). The menus take A only when it is held a little (a frame or two).
- **Kept out.** The uninstaller, `KillSave.exe`, the links and the logs of
  its last start on the PC.
