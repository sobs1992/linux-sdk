# The Book of Unwritten Tales

The Book of Unwritten Tales (2009, KING Art; Ogre 3D 1.7, Direct3D 9, Cg
shaders, Theora videos, OpenAL), the Russian edition of 1C-SoftClub
(1.0.2.0: Russian text and voices), under Wine on the GO Ultra (manifest
`[bout]`, wine.ini in `overlay/`).

- Runs on the GO Ultra (ogu2, 2026-11-21): menus, the prologue video and
  the first scenes of chapter 1 at a steady 30 fps (the frame limit), the
  game's own quality "high" (measured at 1024x576). The game ~650 MB, ~800 MB of the
  device's memory left. Sound and voices through OpenAL Soft.
- Display: Ogre's mode 854x480, the screen's own (wine.ini `mode`; 1024x576
  also offered for an older ogre.cfg); the game draws its scenes 16:10
  inside it, narrow bars at the sides. Text 1.3 times bigger: "Text size".
- WineD3D's video memory raised to 2048 MB (`VideoMemorySize` in
  WINE_D3D_CONFIG, wine.ini): WineD3D takes the GPU for a GeForce 6800
  with 128 MB, Ogre keeps all textures of a chapter, and the loading of
  chapter 1 stopped with "Out of video memory" (at 1024 the prologue hung).
- Memory: `WINE_D3D9_MANAGED_EVICT=1` (wine.ini `env`, wine-wow64 patch
  0033). Wine 11's d3d9 keeps a system memory copy of every managed
  texture next to the GPU one; the game held ~900 MB of RAM next to
  570-680 MB of GPU buffers, ~180 MB left, and after a long session a
  heavier scene load ended in the OOM killer (ogu2, 2026-11-22). With
  the variable the copies are freed once on the GPU: 551 MB instead of
  781 MB at ~400 MB of textures (chapter 2), 30 fps as before.
  Transparent huge pages were not the cause (`madvise` instead of
  `always`: the game's RSS unchanged).
- Memory over a long chapter (ogu2, 2026-11-23): Ogre keeps every texture
  of every scene visited until the chapter changes (CHAPTERDATA; no texture
  of the session was ever loaded twice, the memory flat between new
  scenes): after 1 h 48 min of chapter 2 the GPU buffers were 1.1 GB
  (101 layers of 1024x1024 RGBA with their mip levels, 5.9 MB each =
  592 MB), the game 703 MB, 67 MB of memory left. Not a leak of Wine or
  Mesa. Halving the scenes' texture files does NOT work: the game lays its
  2D layers out by the textures' size in pixels (the scene became small
  tiles in stretched edges).
  The game has one Ogre scene manager for all scenes and destroys a left
  scene's objects (its meshes load again on a return), but the scene's
  own object keeps its 2D layers' textures (backgrounds, layers, patches)
  until the chapter ends. `scenemem.py` (manifest `run`, through
  `prepare.sh`) adds two calls to the scene change of `bout.exe`: before
  the new scene loads, if Ogre counts more than 320 MB of textures (the
  first level of each: GPU buffers ~1.45 times that), every texture that
  can be loaded again is unloaded (the new scene loads its own, Ogre loads
  the others again where drawn); after it, what no object uses any more
  in CHAPTERDATA. A change that unloads takes 4-5 s (a first visit; a
  return to a loaded scene 0-2 s), about once in a few new scenes.
  Measured on ogu2 (2026-11-23, the hut of chapter 2 at the same save):
  236 MB of GPU buffers before, 143 MB with it (what the chapter's load
  had left unused); with the limit at 16 MB (unloading at every change)
  hut 71, swamp 112, hut again 73 (its backgrounds loaded again), street
  127 MB; scenes, inventory, recipe, map and labels drawn right. A long
  session with the 320 MB limit is not measured yet.
- OpenAL: OpenAL Soft 1.23.1 (`lab/redist/openal-soft-1.23.1`, its Win32
  `soft_oal.dll` as the game's `OpenAL32.dll`). With Creative's router and
  wrap_oal (as Daemonica) the game found a device but stayed silent: the
  sound card never opened.
- 1C's activation (`ActivationLib.dll`) passes with the repack's patched
  `bout.exe`; the installer's InstallFlag DWORDs are not needed, wine.ini
  sets its string values (`reg`).
- Settings (`config.xml`, `ogre.cfg`), saved games and logs (`bout.log`,
  Ogre's log) in My Documents\Book of Unwritten Tales in the Wine prefix:
  nothing written into the game's directory (`/games` stays read-only).
- Controls: the left stick is the cursor, the right stick and the D-pad a
  slower one (for a small hotspot), A the click, Y the right click, X or R1
  held marks the scene's hotspots (Space), F1 Esc (the menu). B does
  nothing (2026-11-22: as Esc next to A and Y it threw the player out of
  the scene into the menu by a slip of the thumb). Videos and
  dialogue lines are skipped by a click (Esc does not skip the prologue).
  The inventory opens with the cursor at the screen's bottom edge (the left
  stick pushed down all the way); the right click does not open it in this
  edition. An item is taken by a click and hangs on the cursor, used by a
  click on its target, put back by the right click.
- Cursor: the game draws its own. With the pointer in the top row or the
  left column (x or y 0) it calls ShowCursor(TRUE), as if the mouse had
  left its window, and each move there set the Windows arrow (the window's
  WM_SETCURSOR) before the game's SetCursor(NULL): bare_app_wine drew an
  arrow flickering over the game's cursor. `cursor = hidden` in wine.ini.
- Saving: F1, "Сохранение", the "пусто" line, the "Сохранение" button (no
  name needed: an empty one is saved as "new game"; Enter does not save).
  Loading: F1, "Загрузка", a line, "Загрузка". No quick save (F keys do
  nothing). Tester's review: docs/game-controls-audit-2026-11-20.md, 6.20.

## Patches of the game's files

`prepare.sh` (manifest `run`) runs `textsize.py` (below) and `scenemem.py`
(the memory over a chapter, above).

## Text size

The game sizes all its text as a share of the screen's height (Ogre
overlays in relative metrics, CEGUI auto-scaled, the menu book's
`fontsize` fractions in `kagedata/interface/original_Bookpages.kad`), so no
display mode makes it bigger on the 480-row screen: 854x480 (wine.ini
`mode`) only makes it sharp, one pixel a pixel. `textsize.py` (manifest
`run`) makes the subtitles, dialogue choices and the other in-game text
1.3 times bigger by three numbers of `bout.exe`, lets the game's settings
list 854x480 and makes the menu book darker and bigger:

| Where | Was | Is | What |
|---|---|---|---|
| float at 0x5bd9f4 | 0.0275 | 0.03575 | char_height of the FormalOutline text areas (LogIngame_msg, the centred one); its only 4 users |
| float at 0x5bddc8 | 0.03375 | 0.043875 | char_height of the Dauphin text (`_pups`); its only user |
| `fld` at 0x4dbeb5 | 0x5bd994 (0.0375) | 0x5bdd20 (0.048667) | the default char_height of the game's text class; 0.0375 is shared with unrelated code, so the load points to another existing constant |

| `cmp` at 0x4e55cb and 0x4f250b | 1024 | 854 | the settings' resolution list takes modes at least this wide (two functions fill it): 854x480 was left out and the line showed 1024x576 (OK there would have set it) |

Checked on the GO Ultra (2026-11-21): a guard's line in chapter 2 wraps to
three lines across the screen, the three dialogue choices fit the panel.
The menu book (`original_Bookpages.kad`, the only `.kad` with
`<mainmenu>`) is patched by `textsize.py` too:

- colours: the items' grey from 60% to 95% opacity, the greyed-out ones
  from 30% to 45%, the one under the cursor dark red (it was the 100% grey
  the others now nearly are);
- its italic 1.2 times bigger (every `fontsize` but the chapter's title over
  a saved game: "Глава 5 - Возвращение в Дикие земли..." fills the left
  page at its own size); the two-line labels of the settings and the hint
  on their left page get their line pitch ×1.2; the menus' items 0.09
  apart (were 0.08), the settings' rows from "Качество" down 0.02-0.035
  lower, a saved game's name 0.01 lower (`BOOK_TOPS`);
- a comment in `<mainmenu>` marks the file as patched.

Checked on the GO Ultra: the settings show 854 x 480 and OK keeps it in
`ogre.cfg`; main menu, in-game menu, settings, save and load pages: no
text runs into another or off its page. The lists of saved games and of
chapters are drawn by the game's code (unchanged). The patcher checks the bytes first and leaves an
already patched file as it is.

The recipe of chapter 2 (the alchemy: the potion, its ingredients and
their ticks) has its text in its picture (`rezept_background.dds`,
1024x1024), drawn as a square panel `<size>` x the screen's height high
(`kagedata/chapter2/common/MGRezept.kad`: 0.6, 288 rows, the text about
3.6 times smaller than painted), 0.05 from the left, centred, its scroll
ending just above the inventory bar, which is shown with it.
`textsize.py` makes it 0.82 high (394 rows: the text 1.37 times bigger)
and moves it up so that it still ends above the bar: the panel's top is
`c - c * height` in the recipe's overlay set-up (cl_MGRecipe), with c the
qword 0.5 at 0x5bd670 (shared with other code); the `fld` at 0x5186b3
loads the qword 0.05 at 0x5bd6f0 instead: top at 0.009 (4 rows), the
scroll from row 8 to 390. Its ticks are placed in shares of the panel
but sized in shares of the screen: 0.0375 x 0.82/0.6 = 0.05125.
Checked on the GO Ultra (ogu2, 2026-11-23): opened from the inventory
(a click on it), the ticks on their boxes, the scroll inside the screen
and above the inventory's items, closed by a click.

The other pictures of the game's minigames have no small text: the city
map of chapter 2 and the orcs' camp map (drawings with big titles), the
stone tablet (symbols), the rain dance (arrows); the wall map of the world
(chapter 2, the mage's tower, Russian names in `kagedata/lang/ru`) is
shown nearly 1:1 (each 1024 tile 2.0 screen heights = 960 rows) and
scrolled, so it is as big as it can be sharp.

## Source

`lab/games/BookOfUnwrittenTales`: the game's directory taken from the
Linux repack `TheBookOfUnwrittenTales_RUS.tar.xz` (Kron4ek's Wine wrapper,
x86_64 Wine 7.0: not used here; the archive is kept on the T7 disk,
`Games/!Installs`), plus `cover-art.jpg` (the game's key art, 1280x720,
given by the user: the cover is a square of its left part, Nate and
Critter). What else was in the repack:

- `lab/redist/SysWOW64/d3dx9_42.dll`: the D3DX that Ogre's Direct3D 9
  render system imports (Microsoft's, from the repack's `game_info/dlls`).
  Its other DLLs (DXVK's d3d9, every other d3dx9_*/d3dcompiler_*) are not
  needed.
- `lab/wip/bout-repack/`: its start.sh, game_info.txt and registry files
  (regs/), for reference.

6.1 GB: `kagedata/lang/ru` 2.9 GB (voices), `common` 1.1 GB, `video`
416 MB (`*.ogm`, Theora: decoded by the game itself, no GStreamer). Not
copied: the uninstaller, `support/` (Windows redistributables).

## Not checked yet

- Chapters 3 and 4 (chapter 2: 760 MB; chapter 5: 594 MB, 30 fps), hibernation.
- The game's log has errors of its own data (old `.material` syntax,
  `kAGE_phong.cgfx` without a supported technique); what they change on
  the screen, if anything, is not known.
