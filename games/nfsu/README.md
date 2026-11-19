# Need for Speed: Underground

EA Black Box's racing game (2003, Direct3D 9) 1.4 under Wine on the GO
Ultra, with ThirteenAG's widescreen fix (loaded by the ASI loader, the
game's `dinput8.dll`) and the Russian translation. The source is Kron4ek's
Linux packaging, `NFSU_Linux.tar.xz`: `game_info/data` is the game
(`lab/games/NFSU`), `rus/` the Russian edition's files, never its own x86
Wine. `[nfsu]` in `games/games.manifest`; `overlay/wine.ini` is the menu
entry.

- **Russian.** `prepare.sh` copies `rus/` over the game: its `Speed.exe`,
  `Languages/English.bin` and `LanguageTextures.bin` (the text, in the
  English slot), `Global/GLOBALA.BUN`, the speech and the videos. Its
  `Subtitles/` (`.bat` and `.reg` files setting `Language`) is left out:
  `wine.ini` sets `Language=English` (the voices with no subtitles).
- **Screen.** 854x480: the widescreen fix renders at the desktop's size
  and fixes the HUD and the field of view. ~43 fps in a race, 60 in the
  menus. `prepare.sh` sets `SkipIntro = 1` (the EA and THX logos).
- **Analog steering.** The left stick is a gamepad's: bare_app_wine's
  `stick = pad` and Wine's winebus patch 0026 make an Xbox 360-like HID
  pad, which the game sees by DirectInput (X axis steering, triggers on
  Z, buttons 0-9). Its buttons are laid out for the game's own joystick
  defaults (Settings > Controls > Joystick): Button 0 brake and reverse,
  1 gas, 2 look back, 3 camera, 4 nitrous, 5 handbrake, 6/7 gear
  down/up, 8 reset the car. So B and R2 are gas, A and L2 brake, X
  nitrous, R1 handbrake, L1 look back, Y camera, F2/F3 gears, F4 reset,
  F1 pause (Esc).
- **Menus.** They take the pad's Button 0 (A) as Enter and 1 (B) as back,
  but neither its D-pad nor its stick: `dpad = arrows` (the keyboard's
  arrows, which also steer in a race). A press shorter than about a
  game frame or two can go unseen.
- **Profile.** The console cannot type a name, so `overlay/save` holds a
  fresh profile "player" (made by the game). The widescreen fix's
  `CustomUserFilesDirectoryInGameDir = save` puts profiles and saved
  games in `save/NFS Underground` of the game's directory instead of
  `C:\ProgramData`; `save` is writable in `wine.ini`, copied to
  `/data/wine/games/nfsu` on the first start and kept.
- **Kept out.** EA's uninstaller and the US patch's installer.
