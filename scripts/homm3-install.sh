#!/bin/bash
# Copy Heroes of Might and Magic III files and VCMI mods for a board running
# VCMI (APPS_CONFIG += bare-app.HOMM3=y) to the games partition of its SD
# card: mounted on this PC, or on the board over SSH.
#
#   homm3-install.sh [--no-hota] [--no-rus] GAME_DIR GAMES_DIR|[root@]HOST
#
# GAME_DIR is an original installation, Shadow of Death or Complete (a HotA
# installation is fine too): the directory with Data, Maps and MP3. Only
# what VCMI reads is copied (~330 MB): the SoD/AB archives of Data (empty
# placeholders and HotA's own files skipped), Maps, MP3.
#
# Mods for VCMI, downloaded once into the SDK's dl/hota/ and unpacked to
# Mods/ (VCMI turns on every mod there when bare_app runs it):
#   hota                 Horn of the Abyss, VCMI's port (~520 MB, CC BY-SA)
#   russian-translation  the original game in Russian (~70 MB): a translation
#                        mod, active only while VCMI's language is Russian
#                        (bare_app's language); with HotA it also switches
#                        HotA's main menu to Russian buttons
#
# Everything goes to heroes3/ of the games partition: GAMES_DIR is where
# the card's FAT32 "GAMES" partition is mounted on this PC; over SSH it is
# /games (IMAGE_DATA_SIZE_MB), mounted read-only, writable for the copy.
# The board has no rsync: files go as a tar stream, so a rerun copies all
# of them again. Saved games and settings are on the board's /data.
set -euo pipefail

SDK_DIR=$(cd "$(dirname "$0")/.." && pwd)
DL=$SDK_DIR/dl/hota
REPO=https://github.com/vcmi-mods
# id  download URL (VCMI's mod repository for 1.7)
MODS="
hota $REPO/horn-of-the-abyss/releases/download/1.7/horn-of-the-abyss-vcmi-1.7.zip
russian-translation $REPO/mega-pack-rus/releases/download/1.7/mega-pack-rus-vcmi-1.7.zip
"

die() { echo "homm3-install: $*" >&2; exit 1; }

skip=" "
while [ $# -gt 0 ]; do
	case $1 in
	--no-hota) skip="$skip hota " ;;
	--no-rus)  skip="$skip russian-translation " ;;
	-*) die "unknown option $1" ;;
	*) break ;;
	esac
	shift
done
[ $# -eq 2 ] || die "usage: $0 [--no-hota] [--no-rus] GAME_DIR GAMES_DIR|[root@]HOST"
game=$1
host=
if [ -d "$2" ]; then
	dest=$2/heroes3
else
	dest=/games/heroes3
	host=$2
	case $host in *@*) ;; *) host=root@$host ;; esac
fi

# Directories by name, any case (MP3, Mp3, mp3)
subdir() { find "$game" -mindepth 1 -maxdepth 1 -type d -iname "$1" | head -n1; }
data=$(subdir data)
maps=$(subdir maps)
mp3=$(subdir mp3)
[ -n "$data" ] && [ -f "$(find "$data" -maxdepth 1 -iname h3bitmap.lod | head -n1)" ] ||
	die "$game: no Data/H3bitmap.lod, not a Heroes III installation"

if [ -n "$host" ]; then
	ssh "$host" "mountpoint -q /games" ||
		die "$host: /games is not mounted (games partition, IMAGE_DATA_SIZE_MB)"
fi

staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT

# Mods: download and unpack once, on disk (/tmp may be in RAM)
mods=
while read -r id url; do
	[ -n "$id" ] || continue
	case $skip in *" $id "*) continue ;; esac
	zip=$DL/$(basename "$url")
	dir=${zip%.zip}
	if [ ! -f "$zip" ]; then
		echo "Downloading the mod $id"
		mkdir -p "$DL"
		curl -fL -o "$zip.tmp" "$url"
		mv "$zip.tmp" "$zip"
	fi
	if [ ! -f "$dir/mod.json" ]; then
		rm -rf "$dir"
		unzip -q -d "$DL" "$zip"
		[ -f "$dir/mod.json" ] || die "$zip: no $(basename "$dir")/mod.json inside"
	fi
	mkdir -p "$staging/Mods"
	ln -s "$dir" "$staging/Mods/$id"	# the directory name is the mod's id
	mods="$mods $id"
done <<< "$MODS"

# Data: archives except empty ones (Complete ships empty h3ab_*) and HotA's
mkdir "$staging/game" "$staging/game/Data"
while IFS= read -r f; do
	ln -s "$f" "$staging/game/Data/$(basename "$f")"
done < <(find "$data" -maxdepth 1 -type f -size +0 \
	\( -iname '*.lod' -o -iname '*.snd' -o -iname '*.vid' \) ! -iname 'hota*')
[ -z "$maps" ] || ln -s "$maps" "$staging/game/Maps"
[ -z "$mp3" ] || ln -s "$mp3" "$staging/game/Mp3"

# copy the contents of a directory (symlinks followed) into one on the
# games partition; run a shell command where the games partition is
copy() {
	if [ -z "$host" ]; then
		mkdir -p "$2"
		cp -rL "$1/." "$2/"
	else
		tar -C "$1" -chf - . | ssh "$host" "mkdir -p '$2' && tar -C '$2' -xf -"
	fi
}
run() { if [ -z "$host" ]; then sh -c "$1"; else ssh "$host" "$1"; fi; }

if [ -n "$host" ]; then
	ssh "$host" "mount -o remount,rw /games"
	trap 'rm -rf "$staging"; ssh "$host" "sync; mount -o remount,ro /games"' EXIT
fi

echo "Copying game data to ${host:+$host:}$dest: $(du -shL "$staging/game" | cut -f1)"
copy "$staging/game" "$dest"

for id in $mods; do
	echo "Copying the mod $id to ${host:+$host:}$dest/Mods/$id: $(du -shL "$staging/Mods/$id" | cut -f1)"
	run "rm -rf '$dest/Mods/$id'"
	copy "$staging/Mods/$id" "$dest/Mods/$id"
done

run "sync; df -h '$dest' | tail -n1"
echo "Done"
