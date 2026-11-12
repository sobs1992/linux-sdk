#!/bin/bash
# Copy the Half-Life game files for a board running Xash3D FWGS
# (APPS_CONFIG += bare-app.HALFLIFE=y) to the games partition: mounted on
# this PC, or on the board over SSH.
#
#   halflife-install.sh GAME_DIR GAMES_DIR|[root@]HOST
#
# GAME_DIR is a bought copy, for Steam steamapps/common/Half-Life: the
# directory with valve/. Copied are valve/ (~550 MB) and the translations
# of the menus, valve_<language>/ (Steam's valve_russian: the engine
# mounts it when the console's language is Russian), without what the
# engine on the board does not use: the Windows, macOS and x86 Linux
# libraries (the game code comes with the image), saved games and settings
# of that copy (the board keeps its own in /data/halflife).
#
# Everything goes to halflife/ of the games partition: GAMES_DIR is where
# the card's FAT32 "GAMES" partition is mounted on this PC; over SSH it is
# /games, mounted read-only, writable for the copy. The board has no
# rsync: files go as a tar stream, so a rerun copies all of them again.
set -euo pipefail

die() { echo "halflife-install: $*" >&2; exit 1; }

[ $# -eq 2 ] || die "usage: $0 GAME_DIR GAMES_DIR|[root@]HOST"
game=$1
host=
if [ -d "$2" ]; then
	dest=$2/halflife
else
	dest=/games/halflife
	host=$2
	case $host in *@*) ;; *) host=root@$host ;; esac
fi

[ -f "$game/valve/liblist.gam" ] || die "$game: no valve/liblist.gam, not a Half-Life installation"

if [ -n "$host" ]; then
	ssh "$host" "mountpoint -q /games" ||
		die "$host: /games is not mounted (games partition, IMAGE_DATA_SIZE_MB)"
fi

# valve_<language>/ with the menus' strings, resource/gameui_<language>.txt
# (not valve_hd/, valve_downloads/ and the like)
dirs=valve
for d in "$game"/valve_*/resource/gameui_*.txt; do
	[ -f "$d" ] || continue
	lang=${d##*/gameui_}
	lang=${lang%.txt}
	dir=${d%/resource/*}
	[ "${dir##*/}" = "valve_$lang" ] && dirs="$dirs valve_$lang"
done

pack() {
	tar -C "$game" -cf - \
		--exclude='*.dll' --exclude='*.so' --exclude='*.dylib' --exclude='*.exe' \
		--exclude='valve/SAVE' --exclude='valve/config.cfg' \
		$dirs
}
run() { if [ -z "$host" ]; then sh -c "$1"; else ssh "$host" "$1"; fi; }

if [ -n "$host" ]; then
	ssh "$host" "games-mount rw"
	trap 'ssh "$host" "games-mount ro"' EXIT
fi

echo "Copying $dirs to ${host:+$host:}$dest"
rm=
for d in $dirs; do rm="$rm '$dest/$d'"; done
run "rm -rf$rm && mkdir -p '$dest'"
if [ -z "$host" ]; then
	pack | tar -C "$dest" -xf -
else
	pack | ssh "$host" "tar -C '$dest' -xf -"
fi

run "sync; cd '$dest' && du -sh $dirs; df -h . | tail -n1"
echo "Done"
