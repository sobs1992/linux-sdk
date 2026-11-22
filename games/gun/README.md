# GUN

Neversoft's western (2005, Direct3D 9) under Wine on the GO Ultra, the
Russian edition as installed on Windows (text and subtitles Russian),
with ThirteenAG's widescreen fix. `[gun]` in `games/games.manifest`;
`overlay/wine.ini` is the menu entry.

- **Widescreen fix.** The copy had it unpacked into `data/`: its ASI
  loader as `data/d3d9.dll`, `Gun.WidescreenFix.asi`/`.ini` and
  `modupdater.asi` in `data/scripts` (beside the game's own `.qb`
  scripts). `Gun.exe` loads `d3d9.dll` from its own directory or
  Windows', never from `data/`: the fix never ran and the game chose
  800x600 4:3. `prepare.sh` moves the loader beside the exe and the fix to
  `scripts/` there; `modupdater.asi` (it looks for updates on the
  internet) is left out. The game renders at 854x480 (`ResX = 0`: the
  desktop's size) with the HUD and field of view fixed.
- **Frame rate.** The engine holds 30 fps (the fix's `GameSpeed = 30`):
  30.0 in the forest of the first mission, in its videos and menus.
- **Controls.** The keyboard and mouse of the game's manual
  (`docs/RUS/manual.pdf`) laid out as the other shooters: the left stick
  W A S D, the right stick the mouse (camera, aim, the menus' pointer:
  the menus are clicked, R1). R1 draws and fires (left button), L1 melee
  and rears the horse (right button), A action/talk/mount (F), B jump
  (Space; also skips the videos), X crouch/roll/gallop (Shift), Y quick
  draw (C), L2/R2 the weapons (wheel), D-pad up scope (Z), down reload (R),
  left throw (V), right holster (T), F1 menu (Esc), F2 whiskey flask (G).
  L1 is melee, not reload as in the other shooters: melee is used far
  more (and on the horse). The game knows an Xbox 360 pad too, but its
  defaults for it (buttons 1-11, reload on a twelfth) do not fit the
  device, and the keyboard keeps every control on one device.
  Verified: walking, the camera, the menus by pointer and R1.
- **Settings.** In the registry (`HKCU\Software\Activision\Gun`); the
  game's own defaults are kept.
