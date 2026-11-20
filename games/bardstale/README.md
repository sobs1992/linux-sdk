# The Bard's Tale (ARPG: Remastered and Resnarkled)

inXile's 2018 edition of the 2004 action RPG, the GOG copy (32-bit, Direct3D
9, XInput, GOG Galaxy's Galaxy.dll, WMV videos), under Wine on the GO Ultra
(manifest `[bardstale]`, wine.ini in `overlay/`). 60 fps in the menus, the
videos and the first village at 1024x768 (the mode the game picks, shown
whole with bars at the sides).

## Russian

The game takes its language from GOG Galaxy's minimanifest,
`goggame-1207659164.info` (Galaxy.dll's GetCurrentGameLanguage reads its
"language"), as the installer wrote it for the language chosen there:
English. prepare.sh writes Russian there; the game's own Russian then comes
up (Levels/*/vat/Russian.lang, fontru.lmp): menus, dialogue text, subtitles,
hints. The voices stay English: the edition has English and German speech
only (Res/Sounds/*_en, *_ge); the German files and videos are left out.

## The gamepad

The game reads the pad by XInput (Wine 0026's pad: an Xbox 360 pad's ids,
`stick = pad` etc. in wine.ini, all of its buttons the pad's), but only with
its option "Use gamepad" on (Options > Controls), and that is off by
default: settings.bin (AppData\Local\inXile entertainment\The Bard's Tale),
byte 0xa4. wine.ini's `profile` puts a settings.bin with it on there on the
first start (the game's defaults otherwise). The game shows PlayStation
pictures for the buttons: its triangle is A (choose), the circle B (back).

The game saves its settings when it quits by its own menu (Exit game), not
when bare_app ends it.

Short presses (under ~150 ms, as ogu-ctl sends them) are often missed in the
menus, longer ones repeat; a hand's presses are longer. The same was seen
with NFSU and Shade's pad (bare_app_wine's pad path), not looked into yet.

## Notes

- Its videos (WMV through DirectShow) play by Wine's GStreamer.
- Saved games: AppData\Local\inXile entertainment\The Bard's Tale\Saved
  Games in the Wine prefix on /data.
