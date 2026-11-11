#!/bin/sh
# RBDOOM-3-BFG as a game of bare_app (package rbdoom3-bfg).
#
# Sound: bare_app names the sound device in AUDIODEV (SDL's variable,
# plughw:<card>,<device>, the ALSA loopback while the stream is on), or
# sets SDL_AUDIODRIVER=dummy when the game is to be silent; OpenAL Soft
# reads neither, so it gets a config file of its own with them.
# Video: SDL looks for libGL for desktop OpenGL; Mesa here has EGL only,
# and EGL 1.5 gives every GL function.
conf="${HOME:-/tmp}/alsoft.conf"
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
export SDL_VIDEO_GL_DRIVER="${SDL_VIDEO_GL_DRIVER:-libEGL.so.1}"
exec /usr/lib/rbdoom3bfg/RBDoom3BFG "$@"
