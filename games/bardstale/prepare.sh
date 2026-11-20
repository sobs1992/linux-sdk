#!/bin/sh
# The Bard's Tale ARPG: Remastered and Resnarkled (GOG) for the GO Ultra,
# run by scripts/games-image.py once the game is copied to $GAME_DIR: the
# game in Russian. It takes its language from GOG Galaxy's minimanifest,
# goggame-1207659164.info ("language"; GetCurrentGameLanguage of
# Galaxy.dll), which the installer wrote for the language chosen there
# (English). Its Russian is in the game already (Levels/*/vat/Russian.lang,
# fontru.lmp): the menus, dialogue text and subtitles. Voices: English
# (the edition has none in Russian; German left out by the manifest).
set -e
: "${GAME_DIR:?}"
info=$GAME_DIR/goggame-1207659164.info
grep -q '"language": "English"' "$info" || grep -q '"language": "Russian"' "$info" ||
	{ echo "prepare.sh: $info: no language" >&2; exit 1; }
sed -i 's/"language": "English"/"language": "Russian"/; s/"en-US"$/"ru-RU"/' "$info"
