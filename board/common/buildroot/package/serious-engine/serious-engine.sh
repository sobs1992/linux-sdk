#!/bin/sh
# Serious Sam: The First Encounter (serioussam) or The Second Encounter
# (serioussamse), Serious Engine 1.10, as a game of bare_app (package
# serious-engine): this script under the game's name.
#
# /usr/lib/serious-engine/<game> holds the program, the game libraries
# and the engine's own SE1_10b.gro (SE1_LIB_DIR). The game.ini on the
# games card gives the game's data (SE1_DATA_DIR, read only) and the
# screen (SE1_SCREEN_WIDTH, SE1_SCREEN_HEIGHT); the player's files go to
# SDL's pref path, $XDG_DATA_HOME/Serious-Engine/<game>, which bare_app
# puts in the game's data directory.
# Video: SDL looks for libGL for desktop OpenGL; Mesa here has EGL only,
# and EGL 1.5 gives every GL function.
game=${0##*/}
export SE1_LIB_DIR=/usr/lib/serious-engine/$game
export SDL_VIDEO_GL_DRIVER="${SDL_VIDEO_GL_DRIVER:-libEGL.so.1}"
exec "$SE1_LIB_DIR/SeriousSam" "$@"
