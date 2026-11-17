#!/bin/sh
# Archolos for the GO Ultra: ../gothic/prepare.sh, its saved games in
# Saves_TheChroniclesOfMyrtana. Its Gothic.ini from Steam had textures at
# most 128 pixels: 256 (no difference in speed, ~35 MB more; 512 left
# Archolos' city with 290 MB of the 2 GB free).
G2_SAVES=Saves_TheChroniclesOfMyrtana G2_INI="VIDEO.zTexMaxSize=256" \
	exec "$(dirname "$0")/../gothic/prepare.sh" "$@"
