# Call of Duty 2

Infinity Ward's shooter (2005, Direct3D 9) under Wine on the GO Ultra,
1C's Russian edition as installed on Windows, single player only.
`[cod2]` in `games/games.manifest`; `overlay/wine.ini` is the menu entry,
`prepare.sh` patches the exe.

- **Profile.** CoD2 keeps its settings, keys and saved games in a profile
  (`main/players/<name>`, `active.txt` names it) and asks for a name
  without one. The copy's own profile (of the PC it was installed on) is
  left out; `overlay/main/players` gives "player", its `config.cfg` as the
  game wrote it on the device: 854x480 "wide 16:9", the intro videos
  played once, the textures the game chose (`r_picmip 2`), and
  `sys_gpu`/`sys_cpuGHz` as Wine shows them. With another computer's
  there the game asked at the start, in a Windows message box, whether to
  set "optimal" settings for the changed hardware. `writable =
  main/players, main/save, main/hunkusage.dat`: what the game writes lives
  in `/data/wine/games/cod2`: the profile, `save/` (the temporary save of a
  level's start) and `hunkusage.dat` (rewritten at every level load). On the
  read-only card each stopped the first level's load with an error.
- **The safe-mode question.** While it runs the game keeps its process id
  in `__CoD2SP_s` and deletes the file at a clean exit; at the start it
  compares the file's with its own and, the same, asks whether to start in
  the safe mode. Under Wine the first process of a prefix is always 0x20,
  so after every quit by F6 the box came up. `prepare.sh` makes the `jne`
  after the file's read a `jmp` (file offset 0x4f79d), past the box.
- **Frame rate.** DirectX 9 renderer: 24-28 fps at the start of the first
  mission (Moscow), 245-275 in the menus.
- **Video memory.** WineD3D takes the GPU for a GeForce 6800 with 128 MB:
  the second mission (Stalingrad, `demolition`) did not load ("Create2DTexture
  (snow_sheet...) failed: Out of video memory", back in the menu).
  `VideoMemorySize=2048` in `WINE_D3D_CONFIG` (only WineD3D's count, as for
  The Book of Unwritten Tales); the profile's `r_picmip_manual 1` keeps the
  textures the game chose at 128 MB (`r_picmip 2`), which the bigger count
  would otherwise raise. The game does not ask about changed hardware for it.
- **Mouse.** The game reads it by DirectInput: `mouse = relative`. The
  right stick looks around and moves the menus' pointer, R1 clicks. The
  stick sends 615 moves a second at full deflection (`cursor_speed 2.4`):
  the menus' pointer takes a move as a pixel of their 640x480, about a
  second over the screen; with the profile's `sensitivity 18` and
  `m_pitch 0.0128` the view turns 240 degrees a second around and 140 up
  and down, as DOOM 3's stick. Before (`cursor_speed` 0.8, sensitivity 5)
  the pointer took four seconds over the screen and the view turned 22
  degrees a second.
- **Menus by keys.** The arrows choose a menu's item (left and right change
  a setting), Enter takes it, Esc goes back; none of them is bound in the
  game, so the D-pad sends its key and an arrow and A use (F) and Enter.
  "Click to start the mission" after a level's load takes only a click
  (R1). Enter on a row of the controls' screens waits for a key to bind,
  as a click there does.
- **Controls.** The profile's default keys laid out as the other
  shooters: left stick W A S D, right stick look, R1 fire, L2 aim down the
  sights while held (right button, bound to `+speed`, the game's "aim down
  the sight" mode; the default `toggleads` switched it on and off), L1
  reload (R), A use (F), B jump (Space), X crouch (C), Y grenade (G), R2
  the other weapon (1), D-pad up smoke (4), down prone (Ctrl), left/right
  lean (Q/E), F1 menu and back (Esc), F2 melee and hold breath (Shift), F3
  binoculars (B), F4 objectives (Tab, held).
  L2 aims, not "previous weapon" as in the other shooters: CoD2 carries
  two weapons and aims down the sights all the time.
  Verified 2026-11-22 on the device: the menus by pointer, D-pad and A,
  F1 back; Moscow's training (walk, look, crouch, prone, stand, objectives,
  the pause menu) and Stalingrad (L2 held aims, fire, reload, grenade,
  smoke, melee, binoculars, lean, the other weapon).
