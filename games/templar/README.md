# Knights of the Temple: Infernal Crusade

Starbreeze's game (2004, Direct3D 8) under Wine on the GO Ultra, 1C's
Russian edition ("Тамплиеры: Крестовый поход"). The installed game as it
is (`[templar]` in `games/games.manifest`), without the manual, the
uninstaller, `KillSave.exe` and StarForce's `protect.dll`: its
`Templar.exe` loads none of it. `overlay/wine.ini` is the game's entry of
bare_app.

- **Renderer.** `Environment.cfg` must keep `VID_RENDER=Direct3D8`.
  `RndrGL.dll` (`OpenGL`) is written for NVIDIA's GL extensions (register
  combiners, VAR) and crashes under Mesa.
- **Speed.** 58-60 fps in play (the screen's 60 Hz), with Mesa's patch
  0005 and `PAN_MMAP_WINDOW` in `wine.ini`. The game draws ~47 times a
  frame and before each draw maps the rest of a 2 MiB vertex buffer and of
  a 1 MiB index buffer (NOOVERWRITE) to write a few KiB. Wine's WoW64
  opengl32 gives a 32-bit program a GL mapping above 4 GiB as a copy, made
  on the map and written back on the unmap: ~280 MB a frame, 6 fps. With
  the GPU's buffers mapped at 0x80000000-0xffffffff (above the 2 GiB of a
  program without `/LARGEADDRESSAWARE`) Wine hands them over as they are.
- **Brightness.** The game sets a brighter gamma ramp for its menus and
  videos only, the identity in play, and greys out its own brightness
  setting. Wine's `winebare.drv` (patch 0020) passes the ramp on, and
  `gamma = 1.6` in `wine.ini` lifts the dungeons on the small screen.
- **Saves.** Settings (`Environment.cfg`, `Options.cfg`, `Sbz1/User.cfg`)
  and profiles with their saved games (`Sbz1/Save`) are writable copies
  under `/data/wine/games/templar`. The game writes a new profile at its
  first checkpoint, not when it is made.
- **Controls.** The keys of the PC version laid out as the console pad:
  - left stick: walk and menus;
  - D-pad: sword, axe, mace, bow;
  - right stick: free camera;
  - R1: attack, L1: block, A: use and Enter, Y: strong attack (as the
    SDK's other action games, DOOM 3's layout);
  - X/B: target to the left/right, L2: combo, R2: divine power;
  - F1: pause (Esc), F2: status, F3: no target.

  The D-pad does not move through the menus: the game reads it as weapon
  keys there too.
