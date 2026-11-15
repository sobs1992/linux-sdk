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

Choose 800x600 in each chapter's Settings > Graphics (the game offers
640x480, 800x600, 1024x768; chapter 1 starts at 640x480, chapter 2 at
1024x768): wine.ini shows 800x600's 16:9 picture on the whole screen; at
the other two the picture is shown whole, between black bars. Press
Apply, then leave by the game's menu (Quit): the game keeps its settings
then, not when it is killed. They are in
`/data/wine/prefix/drive_c/users/root/Documents/Telltale Games/monkeyN/prefs.prop`
(the directory's name, as Wine has no `SaveGameFolderName` in the
registry), with the saved games.

A new chapter starts at quality 1. This edition shows a black world at
quality 1-6 (it draws its scene into a texture and never puts it on the
screen); wine.ini's `WINE_D3D9_SHOW_LOST_SCENE=1` (Wine patch 0022)
shows that texture. 7 and above draw the scene themselves, with more
detail. In the first scene at 800x600 both ran at ~40 fps, with
`NoMultisample=1` (Wine patch 0021): the game takes a multisampled back
buffer when offered one, and with it quality 7 ran at 19 fps.

The text (Buka's font) is thin at 800x600: some strokes are lost, the
same at every quality.
