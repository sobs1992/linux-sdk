# Need for Speed: Most Wanted

EA Black Box's racing game (2005, Direct3D 9) 1.3 under Wine on the GO
Ultra, the Russian edition as installed on Windows, with ThirteenAG's
widescreen fix, the Extra Options and MWFixes (ASI plugins in `SCRIPTS/`,
loaded by the ASI loader, the game's `dinput8.dll`). `[nfsmw]` in
`games/games.manifest`; `overlay/wine.ini` is the menu entry.

- **Russian.** As installed: `Settings.ini` in `SAVES/NFS Most Wanted`
  (the fix's `WriteSettingsToFile`) says `Language=Russian`; text, voices
  and videos are the Russian ones.
- **Screen.** 854x480: the widescreen fix renders at the desktop's size
  and fixes the HUD and the field of view. `prepare.sh` sets
  `SkipIntro = 1` and `ImproveGamepadSupport = 1` (Xbox button icons, the
  pad's actions in the menus), the dynamic shadows back to the original
  1024 without the fix's extras, and the lowest graphics in `Settings.ini`
  (what the options screen writes).
- **Frame rate.** Menus 130-150 fps; a race 30-35, both busy threads (the
  game's ~57 %, WineD3D's ~75 %) as in NFSU. `fps_limit = 30` holds it
  even. The heaviest scenes (the career's opening drive, measured over
  50 s of it with `BARE_APP_FRAME_STATS=1`, the same each run) were
  21 fps with the slowest frames at ~127 ms: no thread at 100 %, the GPU
  busy 45-77 %, its governor (simple_ondemand) going down to 125-400 MHz
  in the gaps so that the next frame came late. `gpu = top` (bare_app
  holds the GPU at its top clock while the game is in front, `gpu-freq
  hold`) and `PAN_MMAP_WINDOW` (buffers mapped below 4 GiB, no WoW64
  copies; speed.exe is not large-address-aware): 27.6 fps there, the
  slowest frames ~60 ms. `BOX64_DYNAREC_SAFEFLAGS=0` crashed the game.
- **Movies.** This edition's `MOVIES/*.vp6` (story, Blacklist, tutorials,
  the attract movie: 32 files, 2.2 GB) are 1920x1088 VP6 at ~12 Mbit/s;
  the game decodes them in its own x86 code (Box64), one thread at 100 %,
  and showed ~13 of their 30 frames a second. `prepare.sh` makes them
  again at 848x480 with `scripts/ea-vp6-shrink.py` (crop to the
  1920x1080 picture between 4 black rows, lanczos, `scripts/vp6enc.c`:
  VP6.0 key frames at quantiser 52, PSNR 40-42 dB; the audio chunks as
  they were, byte for byte, checked): 1.6 GB, 30 fps steady, still 30
  with the big cores capped at 1 GHz. The first run takes ~4 minutes
  (16 threads), later ones copy from `lab/images/cache/ea-vp6`.
- **Profile.** The game asks for a profile's name at the first start (the
  console cannot type one): `overlay/SAVES/NFS Most Wanted/player/player`
  is a profile "player" made on the device. `writable = SAVES`: it lives
  in `/data/wine/games/nfsmw/SAVES` with the saved career.
- **Controls.** The game sees bare_app_wine's pad as "Controller (XBOX 360
  For Windows)" (`stick = pad`, `dpad = pad`, Wine patch 0026). Its own
  pad layout has gas on A, brake on X, handbrake on B; the profile has
  two changes, made in Options > Controls, so that B is the brake (and
  back in the menus) as in NFSU: brake on B, handbrake on X. The device:
  A and R1 gas, B and L1 brake and reverse, L2 handbrake (the game's X),
  R2 look back (its LB), X nitrous (its Back), Y speedbreaker, F1 pause
  (Start), F4 reset the car (its RB), the D-pad the game's (events,
  blacklist, map, SMS). The left stick steers and moves in the menus.
  Verified: gas, brake, the menus by D-pad and A/B.
