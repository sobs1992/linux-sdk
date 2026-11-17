#!/bin/sh
# Unreal Tournament 2004, its Linux x86_64 build (patch 3369) under Box64,
# as a game of bare_app (package ut2004).
#
#   ut2004 [-w WIDTH -h HEIGHT] [GAME ARGUMENTS...]
#
# UT2004_DIR: the game (read-only: the games card, /games/ut2004). HOME
# (bare_app's data directory of the game, /data/ut2004): where the game
# writes, ~/.ut2004: its settings (System/UT2004.ini, User.ini), saved
# games, the cache.
#
# Settings: the game makes UT2004.ini and User.ini from its Default.ini and
# DefUser.ini at its first start. This does it before, and puts over them
# the board's own of the game's directory, bare_app/UT2004.ini and User.ini
# (renderer, sound, the gamepad's axes and the keys bare_app's buttons
# become): on the card with the game, changed without a new image. Only
# the first time: what is changed in the game's menus stays. The screen
# size (-w, -h: bare_app's video layer) is set at every start.
#
# Sound: bare_app names the sound device in AUDIODEV (SDL's variable,
# plughw:<card>,<device>, the ALSA loopback while the stream is on), or
# sets SDL_AUDIODRIVER=dummy when the game is to be silent; OpenAL Soft
# reads neither, so it gets a config file of its own with them.
# Video: SDL 1.2 is sdl12-compat over SDL2's bareapp driver; SDL looks
# for libGL for desktop OpenGL, Mesa here has EGL only, and EGL 1.5 gives
# every GL function. Box64 takes the system's SDL 1.2 and OpenAL for the
# game's own x86_64 ones (BOX64_PREFER_WRAPPED: the game names
# ./libSDL-1.2.so.0, which the installer left out).
GAME="${UT2004_DIR:-/games/ut2004}"
W=
H=
while [ $# -gt 0 ]; do
	case $1 in
	-w) W=$2; shift 2 ;;
	-h) H=$2; shift 2 ;;
	*) break ;;
	esac
done

export HOME="${HOME:-/root}"
export SDL_VIDEO_GL_DRIVER="${SDL_VIDEO_GL_DRIVER:-libEGL.so.1}"
export BOX64_PREFER_WRAPPED=1
export BOX64_LOG="${BOX64_LOG:-0}"
export BOX64_NOBANNER=1

conf="$HOME/alsoft.conf"
{
	echo "[general]"
	if [ "$SDL_AUDIODRIVER" = dummy ]; then
		echo "drivers = null"
	else
		echo "drivers = alsa"
		echo "[alsa]"
		echo "device = ${AUDIODEV:-default}"
		echo "capture = default"
	fi
} > "$conf" 2>/dev/null && export ALSOFT_CONF="$conf"

SYS="$HOME/.ut2004/System"
mkdir -p "$SYS" || exit 1

# ini_set FILE FRAGMENT: each [section] key=value of FRAGMENT into FILE,
# replacing that key in its section or added at the section's end (the
# section at the file's end if FILE has none); ";" lines are comments
ini_set() {
	awk -v frag="$2" '
	function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t\r]+$/, "", s); return s }
	BEGIN {
		sec = ""
		while ((getline line < frag) > 0) {
			line = trim(line)
			if (line == "" || line ~ /^;/) continue
			if (line ~ /^\[.*\]$/) { sec = line; continue }
			k = substr(line, 1, index(line, "=") - 1)
			if (k == "") continue
			n++; fs[n] = sec; fk[n] = k; fl[n] = line
		}
	}
	function flush(s,   i) {
		for (i = 1; i <= n; i++)
			if (fs[i] == s && !done[i]) { print fl[i]; done[i] = 1 }
	}
	{
		t = trim($0)
		if (t ~ /^\[.*\]$/) { flush(cur); cur = t; seen[t] = 1; print; next }
		if (index(t, "=") > 1) {
			k = substr(t, 1, index(t, "=") - 1)
			for (i = 1; i <= n; i++)
				if (fs[i] == cur && fk[i] == k) {
					if (!done[i]) { print fl[i]; done[i] = 1 }
					next
				}
		}
		print
	}
	END {
		flush(cur)
		for (i = 1; i <= n; i++)
			if (!done[i]) {
				if (!(fs[i] in head)) { print ""; print fs[i]; head[fs[i]] = 1 }
				print fl[i]
			}
	}' "$1" > "$1.new" && mv "$1.new" "$1"
}

for f in UT2004:Default User:DefUser; do
	ini=${f%%:*}.ini
	if [ ! -f "$SYS/$ini" ]; then
		cp "$GAME/System/${f#*:}.ini" "$SYS/$ini" || exit 1
		[ -f "$GAME/bare_app/$ini" ] && ini_set "$SYS/$ini" "$GAME/bare_app/$ini"
	fi
done
if [ -n "$W" ] && [ -n "$H" ]; then
	printf '[SDLDrv.SDLClient]\nFullscreenViewportX=%s\nFullscreenViewportY=%s\nWindowedViewportX=%s\nWindowedViewportY=%s\nStartupFullscreen=True\n' \
		"$W" "$H" "$W" "$H" > "$SYS/.size"
	ini_set "$SYS/UT2004.ini" "$SYS/.size"
	rm -f "$SYS/.size"
fi

cd "$GAME/System" || exit 1
exec box64 ./ut2004-bin-linux-amd64 "$@"
