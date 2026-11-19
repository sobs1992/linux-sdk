#!/bin/sh
# Shade: Wrath of Angels for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR: settings.cfg (the engine's
# settings) at the device's own 854x480 (the copy came at 1280x1024) and
# the camera's up and down inverted (InvertMouse 1, the user's choice:
# the right stick pushed up takes the camera down behind the hero, pushed
# down raises it over him, the other way round than with InvertMouse 0).
# The game's own setting inverts the camera only (player.h, g_fMouseSpeedV
# negative), not the menus' pointer, which bare_app's inverted axis would
# turn too. The player's later changes are in its writable copy on /data.
set -e
: "${GAME_DIR:?}"
cfg=$GAME_DIR/settings.cfg
[ -f "$cfg" ] || { echo "prepare.sh: no $cfg" >&2; exit 1; }

set_cfg() {	# KEY VALUE: "KEY VALUE" where settings.cfg has KEY
	grep -q "^$1 " "$cfg" || { echo "prepare.sh: $cfg has no $1" >&2; exit 1; }
	sed -i "s/^$1 [^\r]*/$1 $2/" "$cfg"
}

# The menus' pointer (SCRIPTS/menu.h, UpdateMouse: the game's scripts are
# compiled at its start) at MENU_SPEED of the mouse's moves, the rest kept
# for the next frame: the right stick turns the camera fast enough
# (wine.ini cursor_speed 6.0), the same moves were too fast a pointer
# (0.4 = the speed of cursor_speed 2.4 was then too slow).
MENU_SPEED=0.6
menu=$GAME_DIR/SCRIPTS/menu.h
if ! grep -q MenuMoveX "$menu"; then
	awk -v f=$MENU_SPEED '
	/^void UpdateMouse\(\)\r?$/ { print "float MenuMoveX, MenuMoveY\r"; print; next }
	/^\tMouse[XY] = Mouse[XY] \+ MouseDelta[XY]\r?$/ {
		a = substr($1, 6, 1)
		print "\tMenuMove" a " = MenuMove" a " + MouseDelta" a " * " f "\r"
		print "\tMouse" a " = Mouse" a " + (int)MenuMove" a "\r"
		print "\tMenuMove" a " = MenuMove" a " - (int)MenuMove" a "\r"
		n++
		next
	}
	{ print }
	END { if (n != 2) exit 1 }' "$menu" > "$menu.new" ||
		{ echo "prepare.sh: $menu: no UpdateMouse moves" >&2; rm -f "$menu.new"; exit 1; }
	mv "$menu.new" "$menu"
fi

set_cfg ScreenWidth 854
set_cfg ScreenHeight 480
set_cfg InvertMouse 1
