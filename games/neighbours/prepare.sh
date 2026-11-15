#!/bin/sh
# Neighbours from Hell 1 and 2 for the GO Ultra, run by scripts/games-image.py
# once the game (bin/ and data/ of the GOG release's game_info/data) is
# copied to $GAME_DIR. The games know only 800x600; bare_app_wine shows
# the top 480 rows at 1:1 (wine.ini rows = 480), so their interface goes
# there:
#   - data/gamedata.bnd, gfxdata.bnd (zip files): the 600-high pictures
#     cut or squeezed to 480 rows, the dialogs' elements moved with them,
#     the bottom panel up 120 (layout.py of the game, relayout.py)
#   - bin/*.dll: the screen size their interface code asks for says 480
#     high, the places it draws at the old bottom move up (dllpatch.py)
#   - cover.png: from the main menu's picture
# game.exe stays as it is: its screen and buffers keep 600 rows, so what the
# game still draws below row 480 lands in them, unseen.
# Python 3 with Pillow needed. $NFH_GAME: 1 (default) or 2.
set -e
: "${GAME_DIR:?}"
tools=$(cd "$(dirname "$0")" && pwd)
case "${NFH_GAME:-1}" in
1) game=1; here=$tools ;;
2) game=2; here=$(cd "$tools/../neighbours2" && pwd) ;;
*) echo "prepare.sh: which game?" >&2; exit 1 ;;
esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 -I -B "$tools/relayout.py" "$here/layout.py" "$GAME_DIR" "$tmp"
python3 -I -B "$tools/dllpatch.py" "$game" "$GAME_DIR/bin" "$tmp/bin" 480
python3 -I -B "$tools/check.py" "$tmp" 480 > "$tmp/check.txt"
cp "$tmp"/data/*.bnd "$GAME_DIR/data/"
cp "$tmp"/bin/*.dll "$GAME_DIR/bin/"
python3 -I -B "$tools/cover.py" "$GAME_DIR/data/gfxdata.bnd" "$GAME_DIR/cover.png"
