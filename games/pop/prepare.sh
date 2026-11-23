#!/bin/sh
# Prince of Persia: The Sands of Time for the GO Ultra, run by
# scripts/games-image.py once the game is copied to $GAME_DIR:
#   - poplaunch.exe (poplaunch.c): POP.EXE started without GOG's launcher
#     and without GOG's gpp.exe (POP.EXE with its Direct3D 9 and
#     DirectInput 8 through GOG's dx.dll and di.dll, whose overlay stops
#     at its start under Wine: an assertion in Nuklear's font atlas)
#   - with $POP_RUS (games.manifest's env), pop1_rus_full.exe: the Russian
#     edition's text and data (prince.bf), its six videos with speech
#     (Video/cine_*.int) and voices (Sound/soundlocal.*). A RAR archive of
#     xdelta3 deltas of the game's files (rus.bat applies them on Windows),
#     applied by vcdiff.py; unrar unpacks it. Its delta of POPData.BF (the
#     PC menus) was made from another build of the game, not GOG's: the
#     menus stay English. A file already in Russian is left as it is.
# Needs the GO Ultra firmware's llvm-mingw (output/ogu/buildroot/host).
set -e
: "${GAME_DIR:?}"
here=$(cd "$(dirname "$0")" && pwd)
sdk=${SDK_DIR:-$(cd "$here/../.." && pwd)}
cc=$sdk/output/ogu/buildroot/host/llvm-mingw/bin/i686-w64-mingw32-clang

[ -f "$GAME_DIR/POP.EXE" ] || { echo "prepare.sh: no $GAME_DIR/POP.EXE" >&2; exit 1; }
if [ -f "$here/poplaunch.exe" ]; then
	# the board's recipes: built with the firmware (board/ogu/buildroot/post-build.sh)
	cp "$here/poplaunch.exe" "$GAME_DIR/poplaunch.exe"
else
	[ -x "$cc" ] || { echo "prepare.sh: no $cc (make FW=ogu first)" >&2; exit 1; }
	"$cc" -O2 -Wall -mwindows -s -o "$GAME_DIR/poplaunch.exe" "$here/poplaunch.c"
fi

[ -n "${POP_RUS:-}" ] || exit 0
[ -f "$POP_RUS" ] || { echo "prepare.sh: no $POP_RUS" >&2; exit 1; }
command -v unrar >/dev/null || { echo "prepare.sh: no unrar (apt install unrar)" >&2; exit 1; }

# unpacked next to the game (the same disk: the files are moved in)
tmp=$(mktemp -d "$(dirname "$GAME_DIR")/.pop-rus.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
unrar x -idq -o+ "$POP_RUS" "$tmp/"

for f in prince.bf Video/cine_010.int Video/cine_110.int Video/cine_730.int \
	 Video/cine_750.int Video/cine_820.int Video/cine_830.int; do
	delta=$tmp/$f.delta
	[ -f "$delta" ] || { echo "prepare.sh: $POP_RUS has no $f.delta" >&2; exit 1; }
	if [ "$(stat -c %s "$GAME_DIR/$f")" = "$(python3 -I -B "$here/vcdiff.py" --size "$delta")" ]; then
		echo "prepare.sh: $f: in Russian already"
		continue
	fi
	python3 -I -B "$here/vcdiff.py" "$GAME_DIR/$f" "$delta" "$tmp/out"
	# the English file's time: the same file each time, rsync copies it
	# onto the card once
	touch -r "$GAME_DIR/$f" "$tmp/out"
	mv "$tmp/out" "$GAME_DIR/$f"
done
mv "$tmp/Sound/soundlocal.big" "$tmp/Sound/soundlocal.fat" "$GAME_DIR/Sound/"
