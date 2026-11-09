#!/bin/sh
# Heroes III: Horn of the Abyss for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR: the HD mod's settings
# (_HD3_Data/Settings/hota.ini, made from its defaults when missing) get
#   - Graphics.Resolution 854x600: wine.ini's mode, the screen's width
#   - Graphics.Rendering.Mode 5: 32-bit GDI, drawn without OpenGL
set -e
: "${GAME_DIR:?}"
s="$GAME_DIR/_HD3_Data/Settings"
[ -f "$s/hota.ini" ] || cp "$s/#default#hota.ini" "$s/hota.ini"
# the file has CRLF line ends: only the values are replaced
sed -i -e 's/^<Graphics\.Resolution> = [0-9x]*/<Graphics.Resolution> = 854x600/' \
	-e 's/^<Graphics\.Rendering\.Mode> = -\?[0-9]*/<Graphics.Rendering.Mode> = 5/' "$s/hota.ini"
grep -q '^<Graphics\.Resolution> = 854x600' "$s/hota.ini"
grep -q '^<Graphics\.Rendering\.Mode> = 5' "$s/hota.ini"
