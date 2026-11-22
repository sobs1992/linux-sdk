#!/bin/sh
# Call of Duty 2 (1C's Russian edition) for the GO Ultra, run by
# scripts/games-image.py once the game is copied to $GAME_DIR
# (games/cod2/README.md):
#  - CoD2SP_s.exe: the check for an improper quit left out. The game keeps
#    its process id in __CoD2SP_s while it runs and deletes it at a clean
#    exit; at the start it compares the one in the file with its own and,
#    the same, offers the safe mode in a Windows message box. Under Wine the
#    first process of a prefix is always 0x20, so every quit by F6 (or the
#    battery) brought the box up on the next start. The "jne" after the
#    file's read (file offset 0x4f79d, 0x44f79d: cmpl $4,0xc(%esp); jne)
#    becomes a "jmp" past the box.
#  - the profile "player" (main/players, from the overlay): its config as
#    the game wrote it on the GO Ultra (854x480 16:9, the intro videos
#    played once, the textures it chose for the device, picmip 2): with the
#    sys_gpu and sys_cpuGHz of another computer it asks at the start
#    whether to set the "optimal" settings for the changed hardware
set -e
: "${GAME_DIR:?}"
exe=$GAME_DIR/CoD2SP_s.exe
off=$((0x4f79d))

cur=$(od -An -tx1 -j $off -N2 "$exe" | tr -d ' \n')
case $cur in
7560) printf '\353' | dd of="$exe" bs=1 seek=$off conv=notrunc status=none ;;
eb60) ;;
*) echo "prepare.sh: $exe: not 1C's CoD2SP_s.exe 1.0 (at 0x4f79d: $cur)" >&2; exit 1 ;;
esac
