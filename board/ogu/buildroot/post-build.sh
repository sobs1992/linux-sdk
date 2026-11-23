#!/bin/sh
# Buildroot post-build hook of the ODROID-GO Ultra, after the common one.
#   $1  target dir
# The mdev daemon and the module coldplug start early, in the background
# (the overlay's /etc/init.d/S03mdev): Buildroot's S10mdev would do them a
# second time.
set -e
rm -f "$1/etc/init.d/S10mdev"

# The system bus and bluetoothd start with a Bluetooth adapter, not at boot
# (the overlay's /etc/init.d/S40bluetooth): renamed so that rcS leaves them.
for d in S30dbus-daemon:dbus-daemon S40bluetoothd:bluetoothd; do
	if [ -e "$1/etc/init.d/${d%%:*}" ]; then
		mv -f "$1/etc/init.d/${d%%:*}" "$1/etc/init.d/${d#*:}"
	fi
done
# The keys of the paired devices stay on the data partition, through a
# reflash of the system
if [ -d "$1/var/lib/bluetooth" ] && [ ! -L "$1/var/lib/bluetooth" ]; then
	rm -rf "$1/var/lib/bluetooth"
fi
mkdir -p "$1/var/lib"
ln -sfn /data/bluetooth "$1/var/lib/bluetooth"

# Games installed on the board (/usr/bin/game-install, bare_app's install
# screen): the recipes as the SDK has them, at the same paths under
# /usr/share/game-recipes (games/games.manifest and the games' directories,
# scripts/gamerecipe.py and game_pictures.py, what a recipe takes from the
# SDK: Pirates!'s wine.ini), done by the same code as games-image.py on
# the PC. Prince of Persia's poplaunch.exe is built here (its prepare.sh
# would build it with llvm-mingw, which the board has not).
SDK_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
R="$1/usr/share/game-recipes"
rm -rf "$R"
mkdir -p "$R/scripts" "$R/apps/bare_app/ports/wine"
cp -r "$SDK_DIR/games" "$R/"
find "$R" -name __pycache__ -prune -exec rm -rf {} +
cp "$SDK_DIR/scripts/gamerecipe.py" "$SDK_DIR/scripts/game_pictures.py" "$R/scripts/"
cp "$SDK_DIR/apps/bare_app/ports/wine/wine.ini" "$R/apps/bare_app/ports/wine/"
install -m 0755 "$SDK_DIR/scripts/game-install" "$1/usr/bin/game-install"
# the user guide as one HTML file: game-install prepare-card puts it on the
# games card ("Руководство.html") for the player who opens the card on a PC
python3 "$SDK_DIR/scripts/user-guide.py" "$1/usr/share/doc/user-guide.html"
cc=$HOST_DIR/llvm-mingw/bin/i686-w64-mingw32-clang
if [ -x "$cc" ]; then
	"$cc" -O2 -Wall -mwindows -s -o "$R/games/pop/poplaunch.exe" "$SDK_DIR/games/pop/poplaunch.c"
else
	echo "post-build: no $cc: Prince of Persia installs without poplaunch.exe on the board" >&2
fi
