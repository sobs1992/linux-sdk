#!/bin/sh
# RBDOOM-3-BFG as a game of bare_app (package rbdoom3-bfg).
#
# Sound: bare_app names the sound device in AUDIODEV (SDL's variable,
# plughw:<card>,<device>, the ALSA loopback while the stream is on); OpenAL
# Soft has no such variable, so it gets a config file of its own with it.
# Video: SDL looks for libGL for desktop OpenGL; Mesa here has EGL only,
# and EGL 1.5 gives every GL function.
conf="${HOME:-/tmp}/alsoft.conf"
{
	echo "[general]"
	echo "drivers = alsa"
	echo "[alsa]"
	echo "device = ${AUDIODEV:-default}"
	echo "capture = default"
} > "$conf" 2>/dev/null && export ALSOFT_CONF="$conf"
export SDL_VIDEO_GL_DRIVER="${SDL_VIDEO_GL_DRIVER:-libEGL.so.1}"
exec /usr/lib/rbdoom3bfg/RBDoom3BFG "$@"
