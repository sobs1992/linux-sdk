# Serious Sam: The First and The Second Encounter

Serious Sam Classic's two games on the GO Ultra, by Serious Engine 1.10
(Croteam's GPL release as tx00100xt's SeriousSamClassic port): package
`serious-engine`, `APPS_CONFIG += bare-app.SERIOUSSAM=y`. Native aarch64
programs, OpenGL drawn by the GPU through SDL's bareapp driver; about 60 fps
at 854x480.

Games on the card (`games/games.manifest`): `ssam1` (The First Encounter,
the Russian edition patched to 1.05) and `ssam2` (The Second Encounter,
1.07). The Russian text and voices are in the games' own .gro files
(`Data/Translations`); the engine adds its `SE1_10b.gro` from
`/usr/lib/serious-engine/<game>`.

## What the engine's patches do (package serious-engine)

- `SE1_DATA_DIR`, `SE1_LIB_DIR`: the data on the read-only card, the
  program and libraries in the image; the player's files (settings,
  players, controls, saved games) in SDL's pref path, the game's data
  directory on `/data` (`.local/share/Serious-Engine/<game>`).
- `SE1_SCREEN_WIDTH`, `SE1_SCREEN_HEIGHT`: always the screen's size.
- A desktop OpenGL context from an SDL built for GLES (Mesa 3.1 compat).
- The gamepad in the menus, NETRICSA and the demos: D-pad or left stick,
  A Enter, B Escape. In this port `WM_NULL` is `WM_CLOSE`: a message set
  to it quits the game.
- aarch64 converts an infinite float to INT_MAX, x86 to INT_MIN: the
  collision grid then spanned 32000x32000 cells and the first level hung
  (the 32-bit ARM code, which checks for infinity, is taken for aarch64).
- SIGTERM quits as the menu's Quit (bare_app's quit saves the settings);
  a normal end is exit status 0.
- Aim assist as in RTCW and DOOM 3 BFG (`plr_iAimAssist`, on by default;
  the single player's "Game options", "Aim assist").

## prepare.sh (games-image.py runs it after the copy)

- `controls.py`: `Controls/00-Default.ctl`, the controls a new player gets:
  the gamepad as each action's second key, the sticks as the axes, the
  mouse (and the motion sensor) on the view axes, which aim assist leaves
  alone. L2 and R2 are buttons paddle3 and paddle2 (game.ini `gamepad`):
  the engine reads triggers only as axes. The layout is DOOM 3 BFG's (as
  the SDK's other shooters): A use, B jump, X crouch, L1 reload, R1 fire,
  L2/R2 previous/next weapon, the D-pad walks, F4 (Back) NETRICSA, Y the
  Serious Bomb (Flip Weapon in The First Encounter); the GO Advance's one
  stick looks. A player made before a layout
  change keeps the old one (Controls/ControlsN.ctl in the data directory):
  copy the new 00-Default.ctl over those.
- The sticks turn at a rate (engine patch 0009; the engine turned by an
  angle a frame, slower the lower the frame rate): sensitivity s gives
  60 * 2^((s - 50) / 5) degrees a second at full deflection, the reading
  squared; "turn l/r" 60 (240 degrees a second) and "look u/d" 56 (138), as
  DOOM 3 BFG's joy_yawSpeed and joy_pitchSpeed.
- `SPOptions.cfg` and `translation.txt`: the "Aim assist" option and its
  Russian, as loose files (they go before the .gro files; The Second
  Encounter has its own loose `Scripts/menu`, used in whatever case it is).

The font has no "ё".
