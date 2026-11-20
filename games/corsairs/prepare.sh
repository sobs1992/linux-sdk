#!/bin/sh
# Pirates of the Caribbean ("Корсары: Пираты Карибского моря", 2003,
# Akella, Storm engine), run by scripts/games-image.py once the game is
# copied to $GAME_DIR: the Russian voices, loading screens, world map
# pictures and videos over the English ones, as the edition's
# sound_video_on.bat does on Windows (it was never run on this copy:
# Sounds/VOICE held only its RUSSIAN directory).
set -e
: "${GAME_DIR:?}"
r=$GAME_DIR/RESOURCE
for d in Sounds/VOICE/RUSSIAN Textures/Loading/Russian Textures/WorldMap/reload/Russian VIDEOS/Russian; do
	[ -d "$r/$d" ] || { echo "prepare.sh: no $r/$d" >&2; exit 1; }
	cp -p "$r/$d"/* "$r/${d%/*}/"
done

# The full sea: the Intel Fix added a second Radeon8500Sea technique
# (MODULES/Techniques/Weather/RadeonSea.sha, the GeForce 3 pixel shader in
# place of the ATI one: "duplicate technique name" in system.log) for
# Intel GPUs that could not run the ATI one. WineD3D can: the sea gets its
# reflections back, at the same frame rate on the GO Ultra (the game's
# main thread is the limit, ~50 fps, not the sea's drawing)
rm -f "$GAME_DIR/MODULES/Techniques/Weather/RadeonSea.sha"

# The controls for bare_app's gamepad (wine.ini [keys]), in the game's own
# settings file (options, written by the game: the player's later changes
# are kept in its copy on /data). The edition's options had the PC
# player's mouse walking (forward on the left button, back on the right);
# here the left stick is W A S D: walking on land and in a fight, the
# sails and the helm at sea (as the game's own defaults have it there and
# on the world map), the right stick the mouse (the camera), A Space (act,
# strike, fire a broadside).
opt=$GAME_DIR/options
set_opt() {	# KEY VALUE: "controls.KEY=VALUE", the line there already
	grep -q "^controls\.$1=" "$opt" || { echo "prepare.sh: $opt has no controls.$1" >&2; exit 1; }
	sed -i "s/^controls\.$1=[^\r]*/controls.$1=$2/" "$opt"
}
for m in primaryland fightmodecontrols; do
	set_opt $m.chrforward key_w
	set_opt $m.chrbackward key_s
	set_opt $m.chrrun vk_shift
	set_opt $m.chrfightmode key_e
	set_opt $m.licommandsactivate vk_return
	set_opt $m.bifastcommand vk_f3
done
set_opt primaryland.chraction vk_space
set_opt primaryland.chrcamcameraswitch vk_tab
set_opt fightmodecontrols.chrattack vk_space
set_opt fightmodecontrols.chrblock vk_control
set_opt fightmodecontrols.chrfire key_q
set_opt fightmodecontrols.chrrecoil key_z
for m in sailing3pers sailing1pers; do
	set_opt $m.ship_turnleft key_a
	set_opt $m.ship_turnright key_d
	set_opt $m.ship_sailup key_w
	set_opt $m.ship_saildown key_s
	set_opt $m.ship_fire vk_space
	set_opt $m.sea_cameraswitch vk_tab
	set_opt $m.bicommandsactivate vk_return
	set_opt $m.bifastcommand vk_f3
done
