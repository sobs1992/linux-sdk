#!/bin/sh
# GUN (the Russian edition) for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR (games/gun/README.md). The copy has
# ThirteenAG's widescreen fix unpacked into data/: its ASI loader as
# data/d3d9.dll, Gun.WidescreenFix.asi/.ini and modupdater.asi in
# data/scripts (beside the game's own .qb scripts). Gun.exe takes d3d9.dll
# from its own directory (or Windows'), never from data/: the fix never
# loaded and the game ran at 800x600 4:3. This
#  - moves the loader to the game's directory, the fix to scripts/ there
#    (the loader looks in scripts/ beside the exe): the game renders at the
#    desktop's 854x480 with the HUD and field of view fixed (ResX = 0)
#  - leaves out modupdater.asi, which looks for updates on the internet
set -e
: "${GAME_DIR:?}"
cd "$GAME_DIR"

if [ -f data/d3d9.dll ]; then
	mv data/d3d9.dll d3d9.dll
fi
mkdir -p scripts
for f in Gun.WidescreenFix.asi Gun.WidescreenFix.ini; do
	[ -f "data/scripts/$f" ] && mv "data/scripts/$f" scripts/
done
rm -f data/scripts/modupdater.asi
for f in d3d9.dll scripts/Gun.WidescreenFix.asi scripts/Gun.WidescreenFix.ini; do
	[ -f "$f" ] || { echo "prepare.sh: no $f" >&2; exit 1; }
done
