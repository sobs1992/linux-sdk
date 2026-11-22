# Worms World Party Remastered

Team17's remaster (2015) of the 2001 game under Wine on the GO Ultra,
GOG's edition as installed on Windows (English: the edition has no
Russian). `[worms]` in `games/games.manifest`; `overlay/wine.ini` is the
menu entry.

- **D3DX.** The frontend's renderer (w2.exe 0x5f4d00 and on) builds
  `data/Gfx/Fade.fx` by `D3DXCreateEffectFromFile` ("Set Fade Effect").
  Wine's D3DX compiles effects with vkd3d-shader, which cannot write this
  one ("Writing fx_2_0 sampler objects initializers is not implemented",
  "Write pass assignments"; ps_2_0 in place of ps_1_1 changes nothing).
  Without the effect its pointer stays NULL; the renderer's present
  (0x5f5270) then calls its Restore for every frame instead of drawing:
  the device's resources made again ~35 times a minute (each loading
  textures through D3DX), never a frame shown, and after ~2 minutes the
  1280x960 software buffer it frees when a Restore fails is drawn into
  (a NULL read at 0x5f01f5). Microsoft's `D3DX9_43.dll` and
  `D3DCompiler_43.dll` (Windows' SysWOW64, in `lab/redist/SysWOW64`; the
  manifest's `file` lines put them beside w2.exe, `dlls` prefers them)
  compile it: the title in ~10 s, the menus ~45 fps.
- **land.dat.** For a match the frontend writes the landscape it makes
  to `data/land.dat` and the game reads it back; on the read-only card
  the write failed and the match waited for it forever. `writable` has
  it (with `save/` and `user/`, which the game makes from `defaultSave`).
- **Frame rate.** A match 85-90 fps; `fps_limit = 60`. Loading a match
  takes ~2 minutes the first time.
- **Screen 640x480.** The game takes the mouse in 640x480 wherever it
  draws (`x / 640` of the picture's width at 0x5f4290, the clicks the
  same): at 854x480 its pointer was drawn a third further right than the
  Windows cursor and went off the screen past x=640. `mode = 640x480`
  shows it 1:1 between black bars; pointer and clicks agree.
- **Pointer hidden by keys.** Any key puts the game into its keyboard
  mode (0x46cd80 sets 0xa44f5f; the cursor type 4 = none), and only
  eight mouse moves in a row bring the pointer back: after B, X, the
  arrows... move the right stick a little to see it again.
- **Controls.** The menus take the mouse only (no key moves or chooses
  there): right stick the pointer (`cursor_speed = 3.5`: 670 px a second
  at full deflection, the other mouse games' left-stick speed; 2.0 was
  "too slow", 1.7 s across the menus and ~10 s at half deflection; in a
  match the same stick moves the camera), A the left
  button (choose a menu item, a weapon in the panel, a target). In a
  match: left stick and D-pad the arrows (walk, aim), R1 Space (fire,
  held for power), B Enter (jump), X Backspace (back flip, twice a high
  jump), Y the right button (weapons panel), L1 Tab (next worm), F1 Esc
  (the match's menu: Force Sudden Death, Quit The Game; a click on the
  item under the pointer). The grenade's fuse and bounce have no
  stepping key (the keyboard's 1..5, - and +), so L2/R2 and F2/F3 are
  buttons of the game's own Xbox pad, which it reads next to the keyboard
  and the mouse: LB/RB fuse down/up (also turn a girder or an air
  strike), LT/RT bounce min/max (its layout is in `language/*.txt`,
  IDS_OPT_CONT_DESC01..13: Thumb L, Thumb R, A, B, X, Y, LB, RB, LT, RT,
  Menu, the thumbs' presses, the order of the pictures named in w2.exe).
  Checked in a match: "Grenade, 4 Sec, MAX Bounce" and back. A pad
  button closes an open weapons panel, as the game's B would.
- **Options screen.** The main menu's fourth tile (Options) shows a
  white page with only its edit fields drawn (an MFC dialog, `+dialog`
  lists its owner-drawn buttons); F6 (hold) is the way out. Not solved.
  Verified 2026-11-22 on unit 1 from the buttons alone: title, single
  player, quick game, firing with power, weapons panel, Quit The Game ->
  Yes back to the menus. A match takes 30-90 s to load (the cake).
- **Debugging notes.** w2.exe reports each step of its renderer with
  OutputDebugString (`WINEDEBUG=+debugstr`); a test copy of w2.exe whose
  Restore passes its return address to that call (`push [esp+4]` at
  0x5f5451, `writable = w2.exe` so bare_app_wine keeps the copy) showed
  the caller under `+relay` with `RelayInclude` limited to it.
