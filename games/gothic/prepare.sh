#!/bin/sh
# Gothic II (2.6, Steam's "Gold Classic") and mods made as games of their own
# on it (Archolos) for the GO Ultra, run by scripts/games-image.py once the
# game is copied to $GAME_DIR (see README.md here):
#   - system/BugslayerUtil.dll: g2fast (g2fast/g2fast.c), a faster lookup of
#     the nearest waypoint; the game's own DLL becomes BugslayerUtil_orig.dll
#   - system/Gothic.ini: a 16:9 display mode of 600 rows (1066x600, shown
#     at 854x480; the game's video menu lists only modes of 600 rows and
#     more, and rewrites one it does not list), no logo videos, the left
#     and right arrows also turning (the left stick), $G2_INI more values
#   - system/SystemPack.ini: a vertical field of view of 50.625 degrees, so
#     the 16:9 picture shows what a 4:3 one does across (90 degrees) and
#     less above and below: the engine draws less (the city of Archolos at
#     night 11.5 -> 14.4 fps with the wider view of 67.5 degrees)
#   - $G2_SAVES: the saved games' directory, empty (wine.ini's writable)
# The game must be copied without GD3D11 (system/ddraw.dll and its files:
# games.manifest's exclude lines): DirectDraw is Wine's.
# Needs the GO Ultra firmware's llvm-mingw (output/ogu/buildroot/host).
set -e
: "${GAME_DIR:?}"
here=$(cd "$(dirname "$0")" && pwd)
sdk=${SDK_DIR:-$(cd "$here/../.." && pwd)}
cc=$sdk/output/ogu/buildroot/host/llvm-mingw/bin/i686-w64-mingw32-clang
sys=$GAME_DIR/system

[ -x "$cc" ] || { echo "prepare.sh: no $cc (make FW=ogu first)" >&2; exit 1; }
[ -f "$sys/Gothic2.exe" ] || { echo "prepare.sh: no $sys/Gothic2.exe" >&2; exit 1; }

# g2fast as BugslayerUtil.dll, the game's one kept for its crash reports
if [ ! -f "$sys/BugslayerUtil_orig.dll" ]; then
	mv "$sys/BugslayerUtil.dll" "$sys/BugslayerUtil_orig.dll"
fi
"$cc" -O2 -march=pentium4 -mfpmath=sse -Wall -shared -s \
	-Wl,--image-base,0x10000000 \
	-o "$sys/BugslayerUtil.dll" "$here/g2fast/g2fast.c" "$here/g2fast/g2fast.def"

# shellcheck disable=SC2086
python3 -I -B "$here/gothic_ini.py" "$sys/Gothic.ini" \
	VIDEO.zVidResFullscreenX=1066 VIDEO.zVidResFullscreenY=600 \
	VIDEO.zVidResFullscreenBPP=32 VIDEO.zStartupWindowed=0 \
	GAME.playLogoVideos=0 \
	KEYS.keyLeft=cb001e00 KEYS.keyRight=cd002000 \
	${G2_INI:-}
python3 -I -B "$here/gothic_ini.py" "$sys/SystemPack.ini" PARAMETERS.VerticalFOV=50.625

[ -z "${G2_SAVES:-}" ] || mkdir -p "$GAME_DIR/$G2_SAVES"
