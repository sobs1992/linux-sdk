#!/bin/sh
# The Book of Unwritten Tales for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR (games/bout/README.md):
#   - textsize.py: in-game text x1.3, the settings' 854x480, the menu book
#     darker and x1.2, the recipe x1.37 ("Text size")
#   - scenemem.py: the textures of the scenes left behind let go of once
#     they take too much memory ("Memory")
set -e
: "${GAME_DIR:?}"
here=$(cd "$(dirname "$0")" && pwd)
"$here/textsize.py" "$GAME_DIR"
"$here/scenemem.py" "$GAME_DIR"
