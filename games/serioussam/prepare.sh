#!/bin/sh
# Serious Sam (The First and The Second Encounter) for bare_app, run by
# scripts/games-image.py once the game is copied to $GAME_DIR:
# - Controls/00-Default.ctl, the controls a new player gets, with the
#   gamepad and the sticks (controls.py);
# - the single player's options (Scripts/Menu/SPOptions.cfg: the game's
#   own two and "Aim assist", plr_iAimAssist of package serious-engine)
#   and their Russian (Data/Translations/sdk.txt, cp1251 as the game's
#   tables). Loose files: the game reads them before its .gro files
#   (The Second Encounter has its own loose Scripts/menu/SPOptions.cfg).
set -e
: "${GAME_DIR:?}"
here=$(dirname "$0")
python3 "$here/controls.py" "$GAME_DIR"

# DIR/NAME as it is there in any case (the game's own Scripts/menu: its
# loose SPOptions.cfg, which goes before the .gro files), else as given:
# one directory on the card's exFAT, which ignores case, and here
dir_ci() {
	found=$(find "$1" -mindepth 1 -maxdepth 1 -type d -iname "$2" | head -n 1)
	echo "${found:-$1/$2}"
}
menu=$(dir_ci "$GAME_DIR/Scripts" Menu)
tables=$(dir_ci "$(dir_ci "$GAME_DIR" Data)" Translations)
mkdir -p "$menu" "$tables"
sed 's/$/\r/' "$here/SPOptions.cfg" > "$menu/SPOptions.cfg"
# CP1251 with CRLF (python3: the board has no iconv)
python3 -c 'import sys; sys.stdout.buffer.write(open(sys.argv[1], encoding="utf-8").read().replace("\n", "\r\n").encode("cp1251"))' \
	"$here/translation.txt" > "$tables/sdk.txt"
