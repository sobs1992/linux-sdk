#!/bin/sh
# iortcw, Return to Castle Wolfenstein's single player, as a game of
# bare_app (package iortcw).
#
# The installation in /usr/lib/iortcw is fs_basepath: the engine, the game
# modules and gamepad.cfg. The game.ini on the games card adds the game's own files
# (another search path), the data directory (fs_homepath) and the screen.
# The game's first start would run its recommended settings, which set a
# 640x480 mode and restart the video: the ini gives the mode instead.
# cg_fixedAspect 2: the HUD and the crosshair at their own aspect on a wide
# screen, at its edges (0 stretches the 4:3 HUD: a flat crosshair); the
# game's menus have no setting for it.
# Video: SDL looks for libGL for desktop OpenGL; Mesa here has EGL only,
# and EGL 1.5 gives every GL function.
export SDL_VIDEO_GL_DRIVER="${SDL_VIDEO_GL_DRIVER:-libEGL.so.1}"
exec /usr/lib/iortcw/iowolfsp +set fs_basepath /usr/lib/iortcw \
	+set com_recommendedSet 1 +set cg_fixedAspect 2 "$@"
