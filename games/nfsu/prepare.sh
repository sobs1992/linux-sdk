#!/bin/sh
# Need for Speed: Underground for the GO Ultra, run by
# scripts/games-image.py once the game is copied to $GAME_DIR:
#   - the Russian edition's files over the game's: rus/ next to the game's
#     data in NFSU_Linux.tar.xz (lab/games/NFSU/rus: its Speed.exe, text,
#     language textures, speech and videos), without its Subtitles/ (two
#     .bat and .reg files of Windows that set the Language value, which
#     wine.ini sets)
#   - ThirteenAG's widescreen fix (scripts/NFSUnderground.WidescreenFix.ini,
#     loaded by the ASI loader dinput8.dll): the profiles and saved games
#     in the game's directory (save/, writable in wine.ini, a profile
#     "player" there to start with: the console cannot type a name), not
#     in C:\ProgramData; the intro videos skipped
set -e
: "${GAME_DIR:?}"
: "${SOURCE:?}"
rus=$SOURCE/../../rus
ini=$GAME_DIR/scripts/NFSUnderground.WidescreenFix.ini

[ -f "$rus/Speed.exe" ] || { echo "prepare.sh: no $rus/Speed.exe" >&2; exit 1; }
[ -f "$ini" ] || { echo "prepare.sh: no $ini" >&2; exit 1; }

(cd "$rus" && find . -path ./Subtitles -prune -o -type f -print) | while read -r f; do
	mkdir -p "$GAME_DIR/$(dirname "$f")"
	cp "$rus/$f" "$GAME_DIR/$f"
done

set_ini() {	# KEY VALUE: "KEY = VALUE" of the fix's ini, its comment kept
	grep -q "^$1 *=" "$ini" || { echo "prepare.sh: $ini has no $1" >&2; exit 1; }
	sed -i "s/^\($1 *= *\)[^ ;\r]*/\1$2/" "$ini"
}
set_ini CustomUserFilesDirectoryInGameDir save
set_ini SkipIntro 1
