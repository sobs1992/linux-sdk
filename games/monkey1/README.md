# Tales of Monkey Island, chapters 1-5

Telltale's game (2009, Direct3D 9) under Wine on the GO Ultra: the GOG
edition, in Russian. Each chapter is its own program and its own entry in
games.manifest: monkey1 ... monkey5, each with its `overlay/wine.ini` (the
same settings; this directory's explains them).

| Entry | Chapter | Program |
|---|---|---|
| monkey1 | Launch of the Screaming Narwhal | MonkeyIsland101.exe |
| monkey2 | The Siege of Spinner Cay | MonkeyIsland102.exe |
| monkey3 | Lair of the Leviathan | MonkeyIsland103.exe |
| monkey4 | The Trial and Execution of Guybrush Threepwood | MonkeyIsland104.exe |
| monkey5 | Rise of the Pirate God | MonkeyIsland105.exe |

GOG's `Launcher.exe` (a page to pick a chapter) is not copied: each
chapter starts its own program. GOG's programs start the game itself,
without Telltale's HTML launcher, so Wine Gecko is not needed.

## Russian

The installation is GOG's with Buka's Russian files put in each chapter's
`Pack`: the voices (`<number>.aud`, Ogg Vorbis; chapter 1 also `.vox`),
the font, the textures with writing (chapter titles, signs) and a few
scenes. The Russian text is in GOG's archives already (`russian.langdb`
next to `english.langdb`).

Which text the engine shows it takes from the registry, what its
installer wrote: `HKLM\Software\Telltale Games\MonkeyIsland10N.exe`,
`Language` (GOG's installer: `english`). Each wine.ini sets it to
`russian` on each start (`reg` lines, bare_app_wine runs Wine's `reg`);
without it the menus and subtitles are English.

## Settings

Each chapter starts at 800x600 and quality 7: its wine.ini has
`profile = profile`, and bare_app_wine copies
`profile/Documents/Telltale Games/monkeyN/prefs.prop` (the game's own
settings file, as it wrote it on Quit after those were chosen in Settings >
Graphics, no saved game in it) into the Wine user's Documents when the
chapter has none there yet. The player's later changes stay: a file
already there is never replaced. Without it a new chapter starts at
1024x768 and quality 9 (all five, 2026-11-16): about a third slower, the
menus between black bars.

The game keeps its settings when it is left by its menu (Quit), not when
it is killed. They are in
`/data/wine/prefix/drive_c/users/root/Documents/Telltale Games/monkeyN/prefs.prop`
(the directory's name, as Wine has no `SaveGameFolderName` in the
registry), with the saved games; the file also names the last saved game,
so a copy from a played chapter does not belong in `profile/`. To make
one: move the chapter's directory there aside, start the chapter, choose
the settings, Apply, Quit, take its `prefs.prop`.

At 800x600 wine.ini shows the 16:9 picture on the whole screen; at
640x480 and 1024x768 it is shown whole, between black bars.

This edition shows a black world at quality 1-6 (it draws its scene into
a texture and never puts it on the screen); wine.ini's
`WINE_D3D9_SHOW_LOST_SCENE=1` (Wine patch 0022) shows that texture. 7 and
above draw the scene themselves, with more detail. In the first scene at
800x600 both ran at ~40 fps, with `NoMultisample=1` (Wine patch 0021): the
game takes a multisampled back buffer when offered one, and with it
quality 7 ran at 19 fps.

The text (Buka's font) is thin at 800x600: some strokes are lost, the
same at every quality.

## Speed

On the GO Ultra at 800x600 and quality 7 (bare_app's frame counter,
`BARE_APP_SYSMON=frames`, 2026-11-15/16):

| Chapter | Scene | fps |
|---|---|---|
| 1 | first scene (Continue from the prologue's autosave) | 37-39 |
| 2 | opening cutscene / sea battle | 60 / 46 |
| 3 | opening cutscene / first scene | 36-57 / 55 |
| 4 | opening cutscene / courtroom | 60 / 37-56 |
| 5 | opening cutscene / first scene (graveyard) | 46 / 57-59 |

A change of scene still hitches for ~0.4 s: the game's own code (x86
under Box64) after Wine patch 0023 took the directory reads of FAT out
(the kernel had 37 % of the main thread there, 2 % after).

The game's Quit ends it with exit code 1 (Pirates! too); bare_app_wine
takes any exit code as a normal end, so bare_app shows no error (only a
Wine killed by a signal counts as a failure).
