# Fallout and Fallout 2 (Fixed Edition)

Interplay's Fallout (1997) and Fallout 2 (1998) under Wine on the GO
Ultra, in the Russian "Fixed Edition" (FE) builds: the original programs
with sfall (Fallout 1: sfall 1.8 by Crafty; Fallout 2: sfall 5.0.5.4 with
the Restoration Project and the Unofficial Patch), Mash's hi-res patch and
FE's fixes and translation. The source is Kron4ek's Linux packaging of
them, `FalloutFE.tar.xz` and `Fallout2FE.tar.xz`: only `game_info/data`
is used (`lab/games/FalloutFE`, `lab/games/Fallout2FE`), never its own
x86 Wine. `[fallout]` and `[fallout2]` in `games/games.manifest`;
`fallout/overlay/wine.ini` and `fallout2/overlay/wine.ini` are the menu
entries, `fallout/prepare.sh` serves both.

- **Screen.** 854x480, the device's own size, a game pixel a device pixel:
  `prepare.sh` sets the hi-res patch (`f1_res.ini`, `f2_res.ini`) and, for
  Fallout 2, sfall's own size in `ddraw.ini` (`Mode=4`, DirectX 9). The
  interface bar is 800 wide in the middle. 45-60 fps on the map.
- **Starting at all (wowbox64 patch 0004).** `Falloutw.exe` is built by
  Watcom, whose runtime loads FS again (`push fs` / `pop fs`). The WoW64
  build of Box64 gave every loaded selector base 0, so the next
  `fs:[0x18]` (the TEB) read address 0x18: the game died in kernelbase at
  its start. The thread's FS selector is now its 32-bit TEB again.
- **Videos (`BOX64_DYNAREC_BIGBLOCK=0`).** Interplay's MVE decoder writes
  the registers of each 8x8 block into the ModRM bytes of its own code
  (`mov al,bl` and so on, `0x4dac99` in Fallout 1) and jumps there, in the
  same 4 KiB page. Box64's big blocks kept the stale code running and the
  videos fell apart into blocks; one block per jump fixes them and costs
  the 2D game nothing visible. Found by interpreting halves of the code
  (`BOX64_NODYNAREC=start-end`) until the videos came out clean.
- **Mouse.** Fallout 1 takes the cursor's place; Fallout 2 (sfall 5) reads
  the mouse by DirectInput and moves its pointer by moves only:
  `mouse = relative` there.
- **Saves.** `data/savegame`, and `data/maps`, `data/proto`,
  `data/scripts` (the places visited, which a save takes along; empty on
  the card), and `fallout.cfg` / `fallout2.cfg` are writable copies under
  `/data/wine/games/<game>`. Without the maps a save fails ("Ошибка при
  сохранении игры").
- **Controls.** Left stick the cursor, D-pad the cursor slowly, right
  stick scrolls the map (the arrow keys), A click, B right click (the
  cursor's mode), X inventory, Y end the turn (Space), L1 the other hand,
  R1 combat, L2 the map (Tab), R2 the character, F1 menu (Esc), F2
  Pip-Boy, F3 save (F4), F4 load (F5). Fallout 2 FE ignores F6, its quick
  save, so both games use the save and load screens.
- **Kept out.** The uninstaller, DirectX's installer, the manuals and FE's
  documents (`!docs`), sfall's log.
