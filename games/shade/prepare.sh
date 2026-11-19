#!/bin/sh
# Shade: Wrath of Angels for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR: settings.cfg (the engine's
# settings) at the device's own 854x480 (the copy came at 1280x1024), and
# the mouse's up and down not inverted (the copy's InvertMouse 1): the
# right stick pushed up looks up. The player's later changes are in its
# writable copy on /data.
set -e
: "${GAME_DIR:?}"
cfg=$GAME_DIR/settings.cfg
[ -f "$cfg" ] || { echo "prepare.sh: no $cfg" >&2; exit 1; }

set_cfg() {	# KEY VALUE: "KEY VALUE" where settings.cfg has KEY
	grep -q "^$1 " "$cfg" || { echo "prepare.sh: $cfg has no $1" >&2; exit 1; }
	sed -i "s/^$1 [^\r]*/$1 $2/" "$cfg"
}

set_cfg ScreenWidth 854
set_cfg ScreenHeight 480
set_cfg InvertMouse 0
