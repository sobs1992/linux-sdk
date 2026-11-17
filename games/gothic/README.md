# Gothic II and Archolos

**Unfinished, not on the console.** This work lives on branch `gothic`
only (not merged into `master`): the city of Archolos runs at 14 fps at
night and 17 at dusk, Gothic II's Khorinis at ~21 fps, short of what the
console's games should do. What was tried and what is left: "Unfinished
work" below.

Piranha Bytes' Gothic II: Night of the Raven (2.6, Steam's "Gold Classic",
Russian) and The Chronicles of Myrtana: Archolos (Steam, Russian text and
voices), a game of its own on the same `Gothic2.exe`, under Wine on the
GO Ultra: `[gothic2]` and `[archolos]` in `games/games.manifest`. This
directory holds what both share; `../gothic2` and `../archolos` hold each
one's `wine.ini` (`overlay/`) and `prepare.sh`, which runs this one's.

## What changes in the game

- **No GD3D11.** Both Steam installs carry GD3D11 (`system/ddraw.dll` and
  `system/GD3D11/`), a Direct3D 11 renderer: the manifest leaves it out,
  and the game draws through Wine's DirectDraw 7 (WineD3D, panfrost's GL).
- **g2fast** (`g2fast/g2fast.c`), installed as `system/BugslayerUtil.dll`
  (the game's own one, its crash reports, renamed `BugslayerUtil_orig.dll`
  and still used through forwarded exports). It replaces
  `zCWayNet::GetNearestWaypoint`, which walks every waypoint of the world,
  by a lookup in a grid of cells over x and z that gives the same waypoint
  (the engine's distance, its float rounding, its choice among equals).
  Archolos' world has 15919 waypoints and its scripts ask ~120 times a
  second: the walk was a quarter of the main thread. The grid is made
  again when the list may change (`Unarchive`, the destructor,
  `InsertWaypoint`, `DeleteWaypoint` are wrapped) and checked against the
  list every 256th lookup. Nothing is patched unless the code at those
  addresses is 2.6's. `G2FAST=0` in `wine.ini`'s env turns it off,
  `G2FAST_CHECK=1` also runs the engine's walk and counts differing
  answers (0 in 8000 lookups in Archolos' city), `G2FAST_STATS=1` writes
  counts to `C:\g2fast.log` every 10 seconds.
- **Gothic.ini** (`gothic_ini.py`): display mode 1066x600 (16:9, shown at
  854x480), no logo videos, the left and right arrows also turning the
  hero (the left stick), Archolos' textures at most 256 pixels (Steam's
  file had 128). The game's video menu lists only modes of 600 rows and
  more and writes the first of its list back over one it does not list:
  854x480 became 800x600 16-bit once a saved game loaded.
- **SystemPack.ini**: `VerticalFOV=50.625`, the 16:9 picture as wide as
  the 4:3 one (90 degrees across), less above and below.
- **MSSSOFT.M3D.** On each start the game copies `Miles/MssSoft.m3d` into
  `system/` and stops with "could not copy file ... into the system
  directory" when it cannot. Steam's installs carry that copy; the
  manifest leaves it out, and `wine.ini` lists it in `writable`, so the
  copy on `/data` is the game's own even on a card that has one (a link
  to read-only `/games` otherwise).

## Speed

The game runs its own x86 code under Box64 on one A73 core; its main thread
is the limit. Measured in Archolos' city (Silbach's market at night, many
torches) and in a dungeon of Gothic II's Khorinis:

| | Archolos, city | Gothic II, dungeon |
|---|---|---|
| Wine and Mesa as they were, 800x600 | 2.8 fps | 4.7 fps |
| + `PAN_MMAP_WINDOW` (Mesa 0005) | | 12.8 fps |
| + `WINE_WOW64_GL_BUFFER_STORAGE=1` (Wine 0026) | 12.3 fps | 26 fps |
| + g2fast | 14.0 fps | |

- Vertex buffers. The game locks ~2000 dynamic vertex buffers a second
  (DirectDraw 7, `DDLOCK_NOOVERWRITE`). Wine's WoW64 opengl32 gives a
  32-bit program a GL mapping above 4 GiB as a copy (written back on the
  unmap), and without `GL_ARB_buffer_storage`, which it hides from WoW64
  programs, WineD3D waits for its command thread to drain on each lock and
  each unlock. Mesa's `PAN_MMAP_WINDOW` maps the GPU's buffers below 4 GiB
  (`Gothic2.exe` is `/LARGEADDRESSAWARE`: its own memory goes around them),
  and Wine's patch 0026 then keeps the extension: WineD3D maps its buffers
  once and the game writes straight into them.
- View distance (the game's own setting, `sightValue` in Gothic.ini, kept
  as the player had it: Gothic II 6, Archolos 4) costs the most: Archolos'
  city 13.2 fps at 4, 14.4 at 2, 19.1 at 0 (houses vanish in fog ten metres
  away). `zVobFarClipZScale`, 512-pixel textures and Box64's options
  (`SAFEFLAGS`, `FORWARD`, `CALLRET=2`, `WEAKBARRIER`, `FASTROUND=2`)
  changed nothing measurable; `BOX64_DYNAREC_DF=0` breaks the game's
  script parser.
- What is left, Archolos' city: the static world drawn and lit on the CPU
  (`zCRenderManager::PackVB` 9%, `zCPolygon::LightClippedPoly` with its
  per-light polygon map 13%, `RenderPoly` 5%), the Daedalus script VM
  (~5%), WineD3D's and DirectDraw's own code (~10%).
- Memory: Archolos' city takes ~1.0 GB, ~330 MB of the 2 GB stay free;
  there is no swap.

## The VDFS init tool and Wine

After an unclean exit (bare_app ending the game counts as one) `Gothic2.exe`
starts `Vdfs32g.exe` and waits for it. Under Wine about one start in two hung
there: the tool's main thread ended its other thread while that held a lock
of the CPU emulator. Wine's patch 0025 lets a WoW64 thread killed while it
holds such a lock run until it lets go of it.

## Controls

The keys of the player's Gothic.ini from Steam (action Space, weapon Ctrl,
turns A/D, sidesteps Q/E), the arrows added to the turns:

- left stick: walk, turn; menus, dialogue choices, the inventory;
- right stick: sidesteps (Q/E), look around (R), first-person look (F;
  Archolos: the torch, T);
- A: action (attack, talk, take, use, choose a reply), B: draw/put away
  the weapon, X: Enter (menus), Y: inventory;
- L1: parry, R1: jump, L2: sneak, R2: walk slowly;
- D-pad: quick slots 1-4;
- F1: menu (Esc), F2: character, F3: log, F4: map.

Menus want Enter (X): the action key does nothing there, and both on one
button would use an item twice in the inventory.

## Testing tools

- Waypoint names for the console's `goto waypoint` (marvin mode: type
  MARVIN on the character screen, F2 opens the console) are in the world
  archive: `grep -a -o 'wpName=string:[A-Za-z0-9_]*' Data/KM_Worlds.mod`.
  Archolos' Gothic.ini has the German keyboard layout: Y and Z swap, `_` is
  Shift+/ (US). The console completes a word from its first letter.
- `Gothic2.exe` carries its public symbols (CodeView NB11, 25288 names):
  they name the functions of a profile.

## Unfinished work

State of 2026-11-17, measured on the GO Ultra at 1066x600:

| | fps |
|---|---|
| Archolos, Silbach's market at night, view distance 2 | 13.9 |
| Archolos, the same at dusk | 17.0 |
| Gothic II, Khorinis' market by day, view distance 6 (a crowd fighting the hero) | ~21 |
| Gothic II, a crypt of Khorinis | 24 |

Archolos' `prepare.sh` sets the view distance to 2 (`sightValue`, Steam's
4): night 11.8 -> 14.0 fps, dusk 15.7 -> 16.9.

**Native world render** (`g2fast/g2light.c`, `g2light.h`; off unless
`G2FAST_WORLD=1`). g2fast hands each BSP leaf the engine renders outdoors
(`zCBspBase::RenderNodeOutdoor`, the call at 0x52f693) to `g2light.so`, a
Unix library next to the DLL, through Wine's `unixbridge` (Wine patch
0027): backface test, `zCPolygon::LightClippedPoly` (its x87 arithmetic
as Box64 runs it; `G2FAST_CHECK=1` relights each polygon with the
engine's code: 0.1% of the polygons differ, by 1 of 255 at most) and the
polygons' way to their materials' lists. Portals, occluders, water and
growing lists stay the engine's. Build it with the firmware's
`aarch64-linux-gcc -O2 -fPIC -shared -ffp-contract=off -fno-strict-aliasing`
into `system/g2light.so`. Result: night 13.9 -> 14.4 fps, dusk 17.0 ->
16.7; with the lighting removed altogether the night was 15.6, so the
lighting alone cannot give much more. Started, not measured: the colours
computed by worker threads (`G2FAST_WORKERS`, joined before
`zCRenderManager::Flush`).

- Pitfall: Box64 keeps a guest page read-only while it holds code it
  translated from it (the patches of Archolos' DLLs put code in the
  game's heap). A write by the game is caught and let through; one from
  native code inside a Wine Unix call makes the call return
  `STATUS_ACCESS_VIOLATION` instead. g2light tries a polygon's pages
  before it changes anything and g2fast gives that polygon to the engine.
- The main thread, Archolos at night with the native render (profile):
  game code 66% (`PackVB` 9%, NPC rays and collisions ~10%, the Daedalus
  VM ~5%, particles ~4%, BSP and vob walks ~4%), g2light 10%, WineD3D
  10%. Other cores idle but WineD3D's thread (~47% of one).
- Left, in the order of what each would give: lighting in worker threads
  (~+8%), `PackVB` native (~+8%), a native Direct3D 7 layer in place of
  WineD3D and DirectDraw's x86 code (~+15%), NPC rays (~+8%). With all of
  them about 20 fps in Archolos' city at night, likely ~30 in Khorinis.
  A static recompilation of `Gothic2.exe` would add 15-25% more at a cost
  of months. OpenGothic (native) ran at 7 fps on the G52 (Vulkan, memory).

Testing: a Gothic II save in the city is reached with `args = -devmode` in
`wine.ini` (marvin mode; typing "marvin" fails, M, N and R are bound) and
the console (F2): `goto waypoint NW_CITY_MERCHANT_PATH_14`.

