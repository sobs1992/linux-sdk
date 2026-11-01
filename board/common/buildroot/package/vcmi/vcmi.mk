################################################################################
#
# vcmi
#
################################################################################

# 1.7.3 or newer: the Horn of the Abyss mod for VCMI needs it
VCMI_VERSION = 1.7.5
VCMI_SITE = $(call github,vcmi,vcmi,$(VCMI_VERSION))
VCMI_LICENSE = GPL-2.0+, GPL-3.0 (FuzzyLite, in the Nullkiller2 AI)
VCMI_LICENSE_FILES = license.txt AI/FuzzyLite/LICENSE

# AI/FuzzyLite is a git submodule, empty in the release tarball: fetch the
# commit VCMI 1.7.5 pins
VCMI_FUZZYLITE_VERSION = 13b3122f5c353c0389ed4e66041d548c44ec9df6
VCMI_FUZZYLITE_SOURCE = fuzzylite-$(VCMI_FUZZYLITE_VERSION).tar.gz
VCMI_EXTRA_DOWNLOADS = \
	https://github.com/fuzzylite/fuzzylite/archive/$(VCMI_FUZZYLITE_VERSION)/$(VCMI_FUZZYLITE_SOURCE)

define VCMI_EXTRACT_FUZZYLITE
	$(call suitable-extractor,$(VCMI_FUZZYLITE_SOURCE)) \
		$(VCMI_DL_DIR)/$(VCMI_FUZZYLITE_SOURCE) | \
		$(TAR) --strip-components=1 -C $(@D)/AI/FuzzyLite $(TAR_OPTIONS) -
endef
VCMI_POST_EXTRACT_HOOKS += VCMI_EXTRACT_FUZZYLITE
VCMI_DEPENDENCIES = \
	boost \
	libsquish \
	minizip-zlib \
	sdl2 \
	sdl2_image \
	sdl2_mixer \
	sdl2_ttf \
	tbb \
	zlib \
	ffmpeg

# Only the client: the game server is built into it. No Qt (launcher,
# editor, translations), no Discord, no ONNX (MMAI). Videos with ffmpeg.
# Nullkiller2 is the default adventure AI, BattleAI the default battle AI.
# The release tarball has no .git, so no version from git either.
VCMI_CONF_OPTS = \
	-DENABLE_CLIENT=ON \
	-DENABLE_SERVER=OFF \
	-DENABLE_LAUNCHER=OFF \
	-DENABLE_EDITOR=OFF \
	-DENABLE_LOBBY=OFF \
	-DENABLE_TRANSLATIONS=OFF \
	-DENABLE_VIDEO=ON \
	-DENABLE_DISCORD=OFF \
	-DENABLE_LUA=OFF \
	-DENABLE_ERM=OFF \
	-DENABLE_TEST=OFF \
	-DENABLE_MMAI=OFF \
	-DENABLE_NULLKILLER_AI=OFF \
	-DENABLE_NULLKILLER2_AI=ON \
	-DENABLE_BATTLE_AI=ON \
	-DENABLE_STUPID_AI=ON \
	-DENABLE_GITVERSION=OFF \
	-DENABLE_CCACHE=OFF \
	-DENABLE_COLORIZED_COMPILER_OUTPUT=OFF \
	-DFORCE_BUNDLED_FL=ON

# As a game of bare_app (0001-client-link-to-bare_app.patch): frames and
# gamepad over bare_app's src/games/game_ipc.h, read from the SDK's apps/
ifeq ($(BR2_PACKAGE_BARE_APP_HOMM3),y)
VCMI_CONF_OPTS += \
	-DVCMI_BARE_APP_IPC=$(BR2_EXTERNAL_SDK_PATH)/../../../apps/bare_app/src
endif

# Every C++ unit pulls in Boost and VCMI's big headers, about 1 GB of RAM
# per compiler; the default -j(cpus + 1) runs the build machine out of
# memory. VCMI_JOBS=N on the make command line overrides.
VCMI_JOBS ?= 4

define VCMI_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(BR2_CMAKE) --build $(VCMI_BUILDDIR) -j$(VCMI_JOBS)
endef

# VCMI draws everything in software into an SDL surface; with the dummy
# video driver SDL keeps the window in memory, so no display backend is
# needed. Buildroot's sdl2 disables that driver and sdl2_mixer disables
# MP3 (the game's music). Their *_CONF_OPTS are expanded only when they
# are configured, so a later option added here wins.
#
# sdl2_mixer also gets the patches in sdl2_mixer/ (a subdirectory: the
# ones here are VCMI's): its dr_mp3 seeks by decoding the whole track up to
# the position, and VCMI resumes tracks. Hooks are expanded when they run,
# as the options are.
#
# FFmpeg gets only what the game's videos need (Bink and Smacker, the
# original game's and Horn of the Abyss's), under 2 MB stripped
# instead of all of it; options added last win, as above.
ifeq ($(BR2_PACKAGE_VCMI),y)
SDL2_CONF_OPTS += --enable-video-dummy
SDL2_MIXER_CONF_OPTS += --enable-music-mp3 --enable-music-mp3-drmp3
FFMPEG_CONF_OPTS += \
	--disable-everything --disable-programs --disable-network \
	--disable-avdevice --disable-avfilter \
	--enable-decoder=bink,binkaudio_dct,binkaudio_rdft,smacker,smackaud \
	--enable-demuxer=bink,smacker

define VCMI_PATCH_SDL2_MIXER
	$(APPLY_PATCHES) $(SDL2_MIXER_DIR) $(VCMI_PKGDIR)/sdl2_mixer \*.patch
endef
SDL2_MIXER_POST_PATCH_HOOKS += VCMI_PATCH_SDL2_MIXER
endif

$(eval $(cmake-package))
