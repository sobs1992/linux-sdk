#!/bin/bash
# Copy Heroes of Might and Magic III data and VCMI mods to a board running
# VCMI (APPS_CONFIG += bare-app.HOMM3=y), over SSH.
#
#   homm3-install.sh [--no-hota] [--no-rus] GAME_DIR [root@]HOST
#
# GAME_DIR is an original installation, Shadow of Death or Complete (a HotA
# installation is fine too): the directory with Data, Maps and MP3. Only
# what VCMI reads is copied (~330 MB): the SoD/AB archives of Data (empty
# placeholders and HotA's own files skipped), Maps, MP3.
#
# Mods for VCMI, downloaded once into the SDK's dl/hota/, unpacked to Mods/
# and enabled in VCMI's modSettings.json:
#   hota                 Horn of the Abyss, VCMI's port (~520 MB, CC BY-SA)
#   russian-translation  the original game in Russian (~70 MB): a translation
#                        mod, active only while VCMI's language is Russian
#                        (bare_app's language); with HotA it also switches
#                        HotA's main menu to Russian buttons
#
# On the board: /data/vcmi (VCMI's data directory with XDG_DATA_HOME=/data)
# and /data/config/vcmi; /data is the data partition (IMAGE_DATA_START_MB).
# The board has no rsync: files go as a tar stream, so a rerun copies all
# of them again. A rerun keeps VCMI's mod settings and adds missing mods.
set -euo pipefail

SDK_DIR=$(cd "$(dirname "$0")/.." && pwd)
DL=$SDK_DIR/dl/hota
REPO=https://github.com/vcmi-mods
# id  download URL (VCMI's mod repository for 1.7)
MODS="
hota $REPO/horn-of-the-abyss/releases/download/1.7/horn-of-the-abyss-vcmi-1.7.zip
russian-translation $REPO/mega-pack-rus/releases/download/1.7/mega-pack-rus-vcmi-1.7.zip
"
DEST=/data/vcmi
CONF=/data/config/vcmi

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
[ $# -eq 2 ] || die "usage: $0 [--no-hota] [--no-rus] GAME_DIR [root@]HOST"
game=$1
host=$2
case $host in *@*) ;; *) host=root@$host ;; esac

# Directories by name, any case (MP3, Mp3, mp3)
subdir() { find "$game" -mindepth 1 -maxdepth 1 -type d -iname "$1" | head -n1; }
data=$(subdir data)
maps=$(subdir maps)
mp3=$(subdir mp3)
[ -n "$data" ] && [ -f "$(find "$data" -maxdepth 1 -iname h3bitmap.lod | head -n1)" ] ||
	die "$game: no Data/H3bitmap.lod, not a Heroes III installation"

ssh "$host" "mountpoint -q /data" ||
	die "$host: /data is not mounted (data partition, IMAGE_DATA_START_MB)"

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

echo "Copying game data to $host:$DEST: $(du -shL "$staging/game" | cut -f1)"
tar -C "$staging/game" -chf - . | ssh "$host" "mkdir -p $DEST && tar -C $DEST -xf -"

for id in $mods; do
	echo "Copying the mod $id to $host:$DEST/Mods/$id: $(du -shL "$staging/Mods/$id" | cut -f1)"
	tar -C "$staging/Mods" -chf - "$id" |
		ssh "$host" "rm -rf $DEST/Mods/$id && mkdir -p $DEST/Mods && tar -C $DEST/Mods -xf -"
done

# Enable them. A new modSettings.json lists them (VCMI keeps the base mod
# "vcmi" itself); an existing one, with the player's submod choices, gets
# the missing ids added to the "mods" line of its active preset.
if [ -n "$mods" ]; then
	ssh "$host" "sh -s" <<-EOF
	set -e
	f=$CONF/modSettings.json
	mkdir -p $CONF
	if [ ! -f \$f ]; then
		list=\$(for m in vcmi $mods; do printf '"%s", ' \$m; done)
		printf '{\n\t"activePreset" : "default",\n\t"presets" : {\n\t\t"default" : {\n\t\t\t"mods" : [ %s ],\n\t\t\t"settings" : {}\n\t\t}\n\t}\n}\n' "\${list%, }" > \$f
	else
		for m in $mods; do
			grep -q "\"mods\" : \[.*\"\$m\"" \$f || sed -i "s/\(\"mods\" : \[\)/\1 \"\$m\",/" \$f
		done
	fi
	grep '"mods"' \$f
	EOF
fi

ssh "$host" "sync; df -h /data | tail -n1"
echo "Done"
