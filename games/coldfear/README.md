# Cold Fear

Darkworks' survival horror (2005, Direct3D 9, DirectInput 8) under Wine on
the GO Ultra, GOG's edition 1.0 v3 (2025: widescreen, modern pads, every
language). `[coldfear]` in `games/games.manifest`; `overlay/wine.ini` is
the menu entry, `prepare.sh` patches the copy.

## Source

GOG's offline installer (`setup_cold_fear_1.0_gog_v3_(86830).exe` and its
`-1.bin`), unpacked on the PC into `lab/games/Cold Fear` with innoextract
1.9:

```sh
innoextract --gog --language en-US -d "lab/games/Cold Fear" setup_cold_fear_1.0_gog_v3_\(86830\).exe
```

GOG tags every file of the game `en-US`: the other languages' files are
the same set, and `--language ru-RU` would leave the game out. The
language is chosen by `lng.bin` (below). The manifest leaves out DirectX's
redistributables (`__redist`), the installer's temporaries, GOG's
metadata and the manual.

## What prepare.sh does

All four patches check the bytes they replace and stop on another exe.

- **Russian.** `lng.bin` is one ASCII digit read at the start: 0 English,
  1 French, 2 Italian, 3 German, 4 Spanish, 5 Russian (the exe's table at
  0x404fa0). GOG's installer writes the one chosen; prepare.sh writes 5.
  Text, subtitles and voices are Russian.
- **The title page's copyright.** The menu takes `MENU_COPYRIGHT_<lang>`
  from its bank and GOG's data has no `_RU` one: in Russian the game
  crashed on the title page (a read at 0x2c, 0x43a8f2). Russian's entry of
  that jump table (file offset 0x85b0) is made English's.
- **854x480.** `res.bin` is the display mode, an index 0..4 into GOG's
  list 1280x720 .. 3840x2160. Index 0 is made the device's own 854x480
  (`mov esi,1280 / mov edi,720` at file offset 0x23e5) and `res.bin` is 0.
  The graphics options' Accept writes `res.bin` again (0x4092b0: fopen
  "wb", unchecked; on the read-only card it crashed, so wine.ini makes it
  writable) as the index of the mode's width, or the width itself for one
  not in the list, which the next start takes for 1024x768: its `cmp
  eax,1280` (file offset 0x94bf) is made 854. The options show the mode as
  "854x0" (the height comes from GOG's list): cosmetic.
- **Shadows low.** `saves/COLDFEAR.DAT` (1024 bytes, the last 4 the
  inverted CRC-32 of the rest; GOG's installer copies it from
  `__support/saves`) holds the graphics levels as int32: shadows 0x300,
  surfaces 0x304, lighting 0x308, 16 "very high" (GOG's default) .. 2
  "low". prepare.sh sets the shadows low (see Speed).

The game's interface scales with the mode: a smaller mode does not make
its text bigger (640x360 tried: the same text, softer, +1-2 fps).

## Speed

On ogu2 (GPU at 800 MHz), the stormy deck at the start of a new game:

| Setting | fps |
|---|---|
| everything "very high" | 22.8 |
| shadows "low", the rest "very high" (default here) | 32.7 |
| everything "low" | 33 |
| shadows at 4 or 8 (the levels between) | 23 |
| without `HeapMaps=1` | 24.4 |
| `PAN_MMAP_WINDOW` | 33.0 |

The main thread spends ~30% of its time in the game's own code and ~35%
waiting for wined3d's render thread (wined3d_pause: `Sleep(0)`, i.e.
getrusage and sched_yield); the render thread is ~85% busy (emulated
wined3d 38%, Mesa 28%, the kernel 11%, memcpy 8%). The GPU is not the
limit. `BOX64_DYNAREC_SAFEFLAGS=0` breaks the game: a new game falls back
to the main menu. `fps_limit = 30` (the game's own limit is 120); menus
run at 80-120. Unit 1 (GPU at 666 MHz) holds the 30 on the same deck.
Later, heavier scenes are not measured yet.

## Controls

The game plays by the gamepad through GOG's layer (`dinput8.dll` +
`goginput.ini`, which takes the pad by VID/PID); bare_app_wine's pad is an
Xbox 360 one (045E:028E, Wine's winebus patch). The game's own layout is
kept (as with NFSU and The Bard's Tale): button 0 runs and chooses in the
menus, so the device's buttons are the pad's where an Xbox 360 pad has
them. The game's bindings are in Settings > Controls > Keys, second
column (DEV0):

| Device | Pad | Game |
|---|---|---|
| left stick | left stick | walk |
| right stick | right stick | camera, aim |
| A (hold) | 0 | run (stamina), choice in the menus |
| B | 1 | use |
| X | 2 | reload |
| Y | 3 | grab a ledge |
| L1 (hold) | 4 | aim over the shoulder |
| R1 | 5 | fire |
| L2 / R2 | 6 / 7 (Z axis) | previous / next weapon |
| F1 | 8 (Back) | menu: mission, documents, Exit, Continue |
| F2 | 9 (Start) | pause |
| F3 | 10 (left stick's button) | crouch (on and off) |
| F4 | 11 (right stick's button) | third-person aim view |
| D-pad | hat | moves in the menus (held 0.2 s at least) |

F1 opens the game's menu, as in every game; F5 minimises, F6 (held)
quits. Checked on ogu2: aim, fire, reload, crouch, run, F1, F2, the
menus by D-pad and A. Not checked: the weapons (only the pistol at the
start), grab, use.

## Saves

The game saves at points it offers while playing (no quick save) into
`SAVES`, with the options file `COLDFEAR.DAT`: `writable = saves,
res.bin` keeps both under `/data/wine/games/coldfear`. Not checked yet at
a real save point; the options file is written there.

## Notes

- The intro video and the in-engine scene after it take ~2.5 minutes from
  "New game"; A does not skip the video, Start pauses the scene.
- The title page says "press a mouse button": A works.
- 344 MB RSS in play.
