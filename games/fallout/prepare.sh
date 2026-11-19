#!/bin/sh
# Fallout and Fallout 2 (Fixed Edition) for the GO Ultra, run by
# scripts/games-image.py once the game is copied to $GAME_DIR: the
# screen of the game at the device's own 854x480, a game pixel a device
# pixel (the editions come at 1280x720). Fallout's hi-res patch
# (f1_res.ini, Fallout 2's f2_res.ini) draws the map that big and the
# interface (800 wide) in its middle; sfall's ddraw.ini (Fallout 2) keeps
# its own size of the screen, set the same.
#
# Another device: FALLOUT_SCREEN=WxH (the GO Advance's manifest: 720x480,
# two thirds of it its 480x320) and FALLOUT_BAR, the interface's width
# (640: the original; the editions' 800 is wider than 720).
set -e
: "${GAME_DIR:?}"

W=${FALLOUT_SCREEN%x*}
H=${FALLOUT_SCREEN#*x}
[ -n "$FALLOUT_SCREEN" ] || { W=854; H=480; }

set_ini() {	# FILE KEY VALUE: KEY=VALUE where the file has KEY= (CRLF kept)
	[ -f "$1" ] || return 0
	grep -q "^$2=" "$1" || { echo "prepare.sh: $1 has no $2" >&2; exit 1; }
	sed -i "s/^$2=[^\r]*/$2=$3/" "$1"
}

found=
for res in f1_res.ini f2_res.ini; do
	[ -f "$GAME_DIR/$res" ] || continue
	found=1
	set_ini "$GAME_DIR/$res" SCR_WIDTH $W
	set_ini "$GAME_DIR/$res" SCR_HEIGHT $H
	[ -z "$FALLOUT_BAR" ] || set_ini "$GAME_DIR/$res" IFACE_BAR_WIDTH "$FALLOUT_BAR"
done
[ -n "$found" ] || { echo "prepare.sh: no f1_res.ini or f2_res.ini in $GAME_DIR" >&2; exit 1; }
# sfall drawing the screen itself (Mode not 0: Fallout 2's 4, DirectX 9)
if grep -q "^Mode=[1-9]" "$GAME_DIR/ddraw.ini" 2>/dev/null; then
	set_ini "$GAME_DIR/ddraw.ini" GraphicsWidth $W
	set_ini "$GAME_DIR/ddraw.ini" GraphicsHeight $H
fi
# Fallout 2 FE's inventory filter (mods/InventoryFilter.dat) wants a screen
# at least 740 wide; narrower, it only says so on every map: off
if [ "$W" -lt 740 ] && grep -q "^InventoryFilter.dat=1" "$GAME_DIR/mods/mods_order.ini" 2>/dev/null; then
	sed -i "s/^InventoryFilter.dat=1/InventoryFilter.dat=0/" "$GAME_DIR/mods/mods_order.ini"
fi
