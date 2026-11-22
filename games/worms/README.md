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
- **Controls.** The game's keyboard and mouse: left stick and D-pad the
  arrows (walk, aim), right stick the pointer, A Space (fire, held for
  power), B Enter (jump), X Backspace (back flip, twice a high jump), Y the
  right button (weapons panel), R1 the left button (choose a weapon or a
  target, the menus' clicks), L1 Tab (next worm), F1 Esc (menu). The game
  also takes an XInput pad (`stick = pad` moves the menus' selection), but
  shows no layout for it; the keys are the ones its manual lists.
  Verified: walking, aiming, the weapons panel, choosing the bazooka by
  pointer and R1, firing; the other keys by bare_app_wine's trace.
- **Debugging notes.** w2.exe reports each step of its renderer with
  OutputDebugString (`WINEDEBUG=+debugstr`); a test copy of w2.exe whose
  Restore passes its return address to that call (`push [esp+4]` at
  0x5f5451, `writable = w2.exe` so bare_app_wine keeps the copy) showed
  the caller under `+relay` with `RelayInclude` limited to it.
