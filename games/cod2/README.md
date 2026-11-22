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
  main/players`: the profile lives in `/data/wine/games/cod2`.
- **The safe-mode question.** While it runs the game keeps its process id
  in `__CoD2SP_s` and deletes the file at a clean exit; at the start it
  compares the file's with its own and, the same, asks whether to start in
  the safe mode. Under Wine the first process of a prefix is always 0x20,
  so after every quit by F6 the box came up. `prepare.sh` makes the `jne`
  after the file's read a `jmp` (file offset 0x4f79d), past the box.
- **Frame rate.** DirectX 9 renderer: 24-28 fps at the start of the first
  mission (Moscow), 245-275 in the menus.
- **Mouse.** The game reads it by DirectInput: `mouse = relative`. The
  right stick looks around and moves the menus' pointer (the menus are
  mouse-only), R1 clicks.
- **Controls.** The profile's default keys laid out as the other
  shooters: left stick W A S D, right stick look, R1 fire, L2 aim down the
  sights (right button), L1 reload (R), A use (F), B jump (Space), X
  crouch (C), Y grenade (G), R2 the other weapon (1), D-pad up smoke (4),
  down prone (Ctrl), left/right lean (Q/E), F1 menu (Esc), F2 melee and
  hold breath (Shift), F3 binoculars (B), F4 objectives (Tab, held).
  L2 aims, not "previous weapon" as in the other shooters: CoD2 carries
  two weapons and aims down the sights all the time.
  Verified: look, walk, the menus by pointer and R1.
