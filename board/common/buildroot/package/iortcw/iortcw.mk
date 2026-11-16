################################################################################
#
# iortcw
#
################################################################################

# No release since 1.51c (2021); the last commit (May 2024) has its fixes
IORTCW_VERSION = 438e7d413b5f7277187c35b032eb0ef9093ae778
IORTCW_SITE = $(call github,iortcw,iortcw,$(IORTCW_VERSION))
IORTCW_LICENSE = GPL-3.0+ with additional terms
IORTCW_LICENSE_FILES = SP/COPYING.txt
IORTCW_DEPENDENCIES = sdl2 zlib mesa-panfrost

# The game modules are named after the architecture the engine asks for
# (q_platform.h's ARCH_STRING: arm64 on aarch64)
IORTCW_ARCH = $(if $(BR2_aarch64),arm64,$(BR2_ARCH))

# Single player only, one program with its OpenGL 1 renderer (rend2 wants
# OpenGL 3.2 core), native game modules, sound through SDL; the libraries
# SDL2 and zlib of the system, the bundled libjpeg (the engine wants its
# jpeg 8 API); no Ogg/Opus music, VoIP, cURL downloads, OpenAL, FreeType.
# The Makefile's release target passes CFLAGS and OPTIMIZE on to the
# build: they come in the environment.
IORTCW_MAKE_OPTS = \
	PLATFORM=linux ARCH=$(IORTCW_ARCH) \
	CC="$(TARGET_CC)" CXX="$(TARGET_CXX)" \
	PKG_CONFIG="$(PKG_CONFIG_HOST_BINARY)" \
	BUILD_DIR=$(@D)/SP/build \
	BUILD_SERVER=0 BUILD_CLIENT=1 BUILD_GAME_SO=1 BUILD_GAME_QVM=0 \
	BUILD_RENDERER_REND2=0 USE_RENDERER_DLOPEN=0 \
	USE_LOCAL_HEADERS=0 USE_INTERNAL_LIBS=0 \
	USE_INTERNAL_JPEG=1 USE_INTERNAL_ZLIB=0 \
	USE_CODEC_VORBIS=0 USE_CODEC_OPUS=0 USE_VOIP=0 USE_MUMBLE=0 \
	USE_CURL=0 USE_OPENAL=0 USE_FREETYPE=0

define IORTCW_BUILD_CMDS
	$(TARGET_MAKE_ENV) CFLAGS="$(TARGET_CFLAGS)" LDFLAGS="$(TARGET_LDFLAGS)" \
		OPTIMIZE= OPTIMIZEVM= \
		$(MAKE) -C $(@D)/SP release $(IORTCW_MAKE_OPTS)
endef

# The installation is fs_basepath: the engine, main/ with the game modules
# and gamepad.cfg; /usr/bin/iowolfsp (iowolfsp.sh) starts it. The game's
# own files are another search path (rtcw.ini, the entry of bare_app's
# menu, GAME_NATIVE).
IORTCW_OUT = $(@D)/SP/build/release-linux-$(IORTCW_ARCH)
define IORTCW_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(IORTCW_OUT)/iowolfsp.$(IORTCW_ARCH) \
		$(TARGET_DIR)/usr/lib/iortcw/iowolfsp
	$(foreach m,cgame qagame ui,\
		$(INSTALL) -D -m 0755 $(IORTCW_OUT)/main/$(m).sp.$(IORTCW_ARCH).so \
			$(TARGET_DIR)/usr/lib/iortcw/main/$(m).sp.$(IORTCW_ARCH).so$(sep))
	$(INSTALL) -D -m 0644 $(IORTCW_PKGDIR)/gamepad.cfg \
		$(TARGET_DIR)/usr/lib/iortcw/main/gamepad.cfg
	$(INSTALL) -D -m 0755 $(IORTCW_PKGDIR)/iowolfsp.sh \
		$(TARGET_DIR)/usr/bin/iowolfsp
	$(INSTALL) -D -m 0644 $(IORTCW_PKGDIR)/rtcw.ini \
		$(TARGET_DIR)/usr/share/bare_app/games/rtcw.ini
endef

$(eval $(generic-package))
