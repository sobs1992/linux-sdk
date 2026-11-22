#!/bin/sh
# Need for Speed: Most Wanted for the GO Ultra, run by scripts/games-image.py
# once the game is copied to $GAME_DIR (games/nfsmw/README.md). The copy
# already has ThirteenAG's widescreen fix (scripts/*.asi, loaded by the ASI
# loader dinput8.dll), its user files in SAVES/ (the profile and
# Settings.ini, CustomUserFilesDirectoryInGameDir, WriteSettingsToFile) and
# Russian chosen there. This sets:
#   - the widescreen fix: no intro videos, the pad's icons and menu actions
#     (XInput: bare_app_wine's pad is an Xbox 360 pad), shadows at the
#     game's original 1024 and none of its costlier extras
#   - Settings.ini: the lowest graphics (the game's own options screen
#     writes the same values)
set -e
: "${GAME_DIR:?}"
ini=$GAME_DIR/SCRIPTS/NFSMostWanted.WidescreenFix.ini
set="$GAME_DIR/SAVES/NFS Most Wanted/Settings.ini"

for f in "$ini" "$set"; do
	[ -f "$f" ] || { echo "prepare.sh: no $f" >&2; exit 1; }
done

set_ini() {	# FILE KEY VALUE: "KEY = VALUE" or "KEY=VALUE", the rest of the line kept
	grep -q "^$2 *=" "$1" || { echo "prepare.sh: $1 has no $2" >&2; exit 1; }
	sed -i "s/^\($2 *= *\)[^ ;\r]*/\1$3/" "$1"
}
set_ini "$ini" SkipIntro 1
set_ini "$ini" ImproveGamepadSupport 1
set_ini "$ini" ShadowsRes 1024
set_ini "$ini" ImproveShadowLOD 0
set_ini "$ini" AutoScaleShadowsRes 0

for kv in g_CarEnvironmentMapEnable=0 g_CarEnvironmentMapUpdateData=0 \
	g_RoadReflectionEnable=0 g_MotionBlurEnable=0 g_ParticleSystemEnable=1 \
	g_WorldLodLevel=0 g_CarLodLevel=0 g_OverBrightEnable=0 g_FSAALevel=0 \
	g_RainEnable=0 g_TextureFiltering=0 g_PerformanceLevel=0 g_VSyncOn=0 \
	g_ShadowDetail=0 g_VisualTreatment=0; do
	set_ini "$set" "${kv%%=*}" "${kv#*=}"
done
