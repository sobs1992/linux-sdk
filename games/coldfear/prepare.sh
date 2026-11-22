#!/bin/sh
# Cold Fear (GOG) for the GO Ultra, run by scripts/games-image.py once the
# game is copied to $GAME_DIR (games/coldfear/README.md):
#  - lng.bin: the language, one ASCII digit read at the start (0 English,
#    1 French, 2 Italian, 3 German, 4 Spanish, 5 Russian: the exe's table
#    at 0x404fa0); GOG's installer writes the one chosen, innoextract
#    leaves its English 0. Russian text and voices.
#  - res.bin: the display mode, a 32-bit index (0 1280x720 ... 4
#    3840x2160, GOG's widescreen list). Index 0 is made the device's own
#    854x480 in ColdFear_retail.exe (mov esi,1280 / mov edi,720 at file
#    offset 0x23e5, the only such pair). The graphics options' Accept
#    writes res.bin again (0x4092b0: fopen "wb", unchecked: wine.ini makes
#    it writable) as the index of the mode's width, or the width itself
#    for one not in the list, which the next start then takes for
#    1024x768: its "cmp eax,1280" (file offset 0x94bf) is made 854.
#  - The title page's copyright: the menu takes MENU_COPYRIGHT_<language>
#    from its bank, and GOG's data has no _RU one: with Russian the game
#    crashed on the title page (a read at 0x2c, 0x43a8f2). Russian's entry
#    of that jump table (at 0x40839c, file offset 0x85b0) is made English's
#    (0x408130): GOG's English copyright, the rest of the menus Russian.
#  - saves/COLDFEAR.DAT: the options file GOG's installer puts in saves/
#    (goggame-1297439746.script), from __support, which then goes.
set -e
: "${GAME_DIR:?}"
cd "$GAME_DIR"

exe=ColdFear_retail.exe
off=$((0x23e5))
orig=be00050000bfd0020000	# mov esi,0x500; mov edi,0x2d0
new=be56030000bfe0010000	# mov esi,0x356; mov edi,0x1e0
cur=$(od -An -tx1 -j $off -N10 "$exe" | tr -d ' \n')
if [ "$cur" = "$orig" ]; then
	printf '\276\126\003\000\000\277\340\001\000\000' |
		dd of="$exe" bs=1 seek=$off conv=notrunc status=none
elif [ "$cur" != "$new" ]; then
	echo "prepare.sh: $exe: not the GOG v3 exe (at 0x23e5: $cur)" >&2
	exit 1
fi

off=$((0x94bf))
cur=$(od -An -tx1 -j $off -N5 "$exe" | tr -d ' \n')
case $cur in
3d00050000) printf '\075\126\003\000\000' |	# cmp eax,1280 -> cmp eax,854
		dd of="$exe" bs=1 seek=$off conv=notrunc status=none ;;
3d56030000) ;;
*) echo "prepare.sh: $exe: not the GOG v3 exe (at 0x94bf: $cur)" >&2; exit 1 ;;
esac

off=$((0x85b0))
cur=$(od -An -tx1 -j $off -N4 "$exe" | tr -d ' \n')
case $cur in
92814000) printf '\060\201\100\000' |	# 0x408192 (_RU) -> 0x408130 (_EN)
		dd of="$exe" bs=1 seek=$off conv=notrunc status=none ;;
30814000) ;;
*) echo "prepare.sh: $exe: not the GOG v3 exe (at 0x85b0: $cur)" >&2; exit 1 ;;
esac

printf 5 > lng.bin
printf '\000\000\000\000' > res.bin

if [ -f __support/saves/COLDFEAR.DAT ]; then
	mkdir -p saves
	[ -f saves/COLDFEAR.DAT ] || cp __support/saves/COLDFEAR.DAT saves/
	rm -r __support
fi

# The graphics options' shadows at low: the levels (shadows, surfaces,
# lighting: int32 at 0x300, 0x304, 0x308) are 16 "very high" (GOG's
# default) .. 2 "low". The stormy deck at the start: 22.8 fps with every
# level very high, 32.7 with only the shadows low (the same as all low);
# shadows at 4 or 8 cost as much as 16. The file ends in the inverted
# CRC-32 of the 1020 bytes before it.
python3 - saves/COLDFEAR.DAT <<'EOF'
import struct, sys, zlib
f = sys.argv[1]
d = bytearray(open(f, "rb").read())
if len(d) != 1024 or struct.unpack_from("<I", d, 1020)[0] != zlib.crc32(d[:1020]) ^ 0xffffffff:
    sys.exit("prepare.sh: %s: not Cold Fear's options file" % f)
struct.pack_into("<i", d, 0x300, 2)
struct.pack_into("<I", d, 1020, zlib.crc32(d[:1020]) ^ 0xffffffff)
open(f, "wb").write(d)
EOF
