#!/bin/sh
# Daemonica for the GO Ultra, run by scripts/games-image.py once the game is
# copied to $GAME_DIR from $SOURCE (a PC installation of the Russian edition):
#   - Data/daemonica.cfg: video_mode 7, the game's 800x600 (wine.ini's mode);
#     the UI needs 800x600 or more, the board shows it at 640x480
#   - daemonica.wrs: the dialogues laid out for the bigger text of
#     WINE_FONT_SCALE=1.25 (daemonica_dialog.py, from the original file)
set -e
here=$(cd "$(dirname "$0")" && pwd)
: "${GAME_DIR:?}" "${SOURCE:?}"
sed -i 's/^ video_mode: .*/ video_mode: 7/' "$GAME_DIR/Data/daemonica.cfg"
grep -q '^ video_mode: 7$' "$GAME_DIR/Data/daemonica.cfg"
python3 -B "$here/daemonica_dialog.py" "$SOURCE/daemonica.wrs" "$GAME_DIR/daemonica.wrs"
