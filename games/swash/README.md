# Swashbucklers: Blue vs. Grey

Akella's pirate game (2007, Direct3D 9) under Wine on the GO Ultra, 1C's
Russian edition «Головорезы: Корсары XIX века» as installed on Windows.
`[swash]` in `games/games.manifest`; `overlay/wine.ini` is the menu entry.

- **Box64.** Without `BOX64_DYNAREC_SAFEFLAGS=2` the game never reaches
  its menu: reading `XRes/ships/ships.csv` its CSV reader (GameSystem.dll,
  one recursion per line) never sees `clx::rstream::eof()` and recurses
  until the stack overflows (in clx.dll). With Box64's safe handling of
  the x86 flags the end is found (which flag its default handling gets
  wrong was not looked for; the cost is small: 120 fps in the tavern).
  The game's own MSVC 7.1 runtime is used (`dlls`), as Pirates! does.
- **Screen.** The game's settings file, `Documents/My Games/Swashbucklers/
  settings` in the Wine user's profile: `overlay/profile` puts one there
  with 854x480 (16:9, in the game's own list) and the post effects off.
- **Frame rate.** 120 fps in the first tavern, 40-47 at its logos.
- **Controls.** The game's keys (its Settings > Controls): W A S D walk
  and steer the ship (left stick), the mouse attacks and aims (right
  stick the pointer; dialogs and menus are clicked by R1). R1 attack, fire
  (left button), L1 shooting mode, low blow (right button), A action,
  talk, block, also the next line of a dialogue (Space), B and F1 the menu
  (Esc), X switch cannon (Tab), Y steam engine (Left Shift), L2/R2 the
  perks Q/E (aim farther/closer at sea, super blows boxing), D-pad up/down
  sails up/down (R/F), left/right the perks Ctrl/Alt, F4 the character
  (I). Verified: menus, dialogues by A, the first fight's start.
