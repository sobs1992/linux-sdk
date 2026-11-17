# Prince of Persia: The Sands of Time

Ubisoft Montreal's game (2003, Jade engine, Direct3D 9) under Wine on the
GO Ultra, the GOG edition ("181 GOG v2", English only) with the Russian edition's
text, voices and videos. The installed game
(`[pop]` in `games/games.manifest`), without the uninstaller, the manual,
GOG's leftovers and the logs and profile of a first start on Windows.
`prepare.sh` adds `poplaunch.exe` and the Russian files; `overlay/` adds
`wine.ini` (the game's entry of bare_app) and a profile.

- **Russian.** The game's text, voices and the six videos with speech
  (`Video/cine_*.int`) of the Russian edition (2003), from
  `pop1_rus_full.exe` (`POP_RUS`, the manifest's `env`; a RAR SFX of
  xdelta3 deltas of the game's files, `Sound/soundlocal.big`/`.fat` whole
  and `rus.bat`). `prepare.sh` unpacks it (unrar) and applies the deltas
  with `vcdiff.py` (a decoder for them: no xdelta3 needed), each window
  checked against its Adler-32: they fit GOG v2's `prince.bf` and videos.
  Its delta of `POPData.BF` was made from another build (a source of
  5.2 MB, GOG v2's is 3.9 MB, 3 MB of the result copied from it), so the
  PC menus (`POPData.BF`: main, profile, pause, save and load menus, their
  fonts, `pop4pclocal.dat`) stay English.
- **Start.** `POP.EXE` runs only under its launcher (`PrinceOfPersia.EXE`,
  a settings window with a Play button): it creates the mutex
  `POP_Launcher` and quits with "You must start the game with
  PrinceOfPersia.EXE" unless that existed already. `poplaunch.exe`
  (`poplaunch.c`) holds the mutex and starts `POP.EXE`. GOG's own
  `gpp.exe` (`POP.EXE` importing GOG's `dx.dll` and `di.dll` instead of
  `d3d9.dll` and `dinput8.dll`) stops at its start under Wine: an
  assertion in its overlay's font atlas (Nuklear).
- **Safe mode question.** The game creates an empty `PrinceSM` at its start
  and deletes it when it quits through its menu; found at the next start
  it asks in a Windows message box whether to use safe mode settings, and
  after that box its window no longer had the keyboard. `poplaunch.exe`
  deletes `PrinceSM` first: quitting with F6 or bare_app's quit is normal
  here.
- **Profile.** At its first start the game asks for a profile's name,
  typed on a keyboard. `overlay/Profiles/prince/Profile.DAT` is a profile
  "prince" the game made (800x600, its default keys, no saved game);
  bare_app_wine copies `Profiles` (`writable`) to
  `/data/wine/games/pop/Profiles` on the first start. Saved games go there
  too.
- **Menus.** They take the mouse only: the dagger is the pointer, the keys
  do nothing (Enter only ends a new profile's name). The right stick moves
  it, A clicks. The dagger's point must be on the word.
- **Mouse.** The game reads the mouse by DirectInput (raw input) while Wine
  holds the Windows cursor in one place, so every place bare_app_wine sent
  was a move from there, again with every later move and with a click: the
  dagger crept or jumped off the button clicked. `mouse = relative`
  (bare_app_wine, Wine patch 0025 in `winebare.drv`) sends moves instead.
- **Speed.** ~30 fps in the first courtyard and 33 on the profile screen
  (800x600), with WineD3D's `HeapMaps`, `SysmemMaps`, `GLStateCache` and
  `WINE_FAST_MUTEX` (29.5 without them); the limit is WineD3D's command
  stream thread at 100% of a core (the game's own thread ~50%). Bink videos
  run as fast as they can draw (~230 fps).
- **Controls.** The PC keys (manual: W A S D, Space, mouse buttons, E, R,
  C, F, Q, Left Shift) laid out as the console pad: left stick run, right
  stick camera and menu pointer, A sword and menu choice, B jump, X dagger,
  Y drop, R1 wall run/roll/block, L1 rewind (with R1 fast forward), L2
  walk, R2 look, F1 menu (Esc), F2 the other view, F3 Enter.
