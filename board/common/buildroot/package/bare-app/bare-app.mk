################################################################################
#
# bare-app
#
################################################################################

BARE_APP_VERSION = 1.0
# Source lives in the SDK: <sdk>/apps/bare_app (git submodule with LVGL inside)
BARE_APP_SITE = $(BR2_EXTERNAL_SDK_PATH)/../../../apps/bare_app
BARE_APP_SITE_METHOD = local
# bare_app_doom (ports/doom, built with GAME_DOOM) is doomgeneric: GPLv2
BARE_APP_LICENSE = GPL-2.0+ (bare_app_doom)
BARE_APP_LICENSE_FILES = ports/doom/LICENSE
# Host build trees and the parts of LVGL and doomgeneric that are never
# compiled (~140 MB)
BARE_APP_OVERRIDE_SRCDIR_RSYNC_EXCLUSIONS = \
	--exclude /build-* \
	--exclude /third_party/lvgl/tests \
	--exclude /third_party/lvgl/docs \
	--exclude /third_party/lvgl/demos \
	--exclude /third_party/lvgl/examples \
	--exclude /ports/doom/doomgeneric/screenshots

# Composition of the binary: bare_app's Kconfig, see configs/ in the app.
# Kconfiglib comes with the app; it needs the host's python3.
BARE_APP_CONF_OPTS = \
	-DBARE_APP_DEFCONFIG=$(call qstrip,$(BR2_PACKAGE_BARE_APP_DEFCONFIG))

ifeq ($(BR2_PACKAGE_BARE_APP_AUTOSTART),y)
define BARE_APP_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(BARE_APP_PKGDIR)/S90bare-app \
		$(TARGET_DIR)/etc/init.d/S90bare-app
endef
endif

# SDL2 games (BARE_APP_SDL): SDL2 gets the bareapp drivers (sdl2/, with
# bare_app's protocol headers next to them) and, with Mesa, OpenGL ES,
# which it loads at run time. As in vcmi.mk: hooks and options of another
# package are expanded when they are used, so options added here win.
ifeq ($(BR2_PACKAGE_BARE_APP_SDL),y)
define BARE_APP_SDL2_DRIVERS
	$(APPLY_PATCHES) $(SDL2_DIR) $(BARE_APP_PKGDIR)/sdl2 \*.patch
	$(INSTALL) -m 0644 $(BARE_APP_SITE)/src/games/game_ipc.h \
		$(BARE_APP_SITE)/src/core/input.h $(SDL2_DIR)/src/video/bareapp/
endef
SDL2_POST_PATCH_HOOKS += BARE_APP_SDL2_DRIVERS
SDL2_CONF_OPTS += --enable-bareapp
ifeq ($(BR2_PACKAGE_MESA_PANFROST),y)
SDL2_DEPENDENCIES += mesa-panfrost
SDL2_CONF_OPTS += --enable-video-opengles --enable-video-opengles2 --disable-video-opengles1
endif
endif

# The game.ini of the SDL2 games we bring: bare_app's menu entries
BARE_APP_GAME_INIS-$(BR2_PACKAGE_BARE_APP_CHOCOLATE_DOOM) += chocolate-doom.ini
ifneq ($(BARE_APP_GAME_INIS-y),)
define BARE_APP_INSTALL_GAME_INIS
	$(foreach f,$(BARE_APP_GAME_INIS-y),\
		$(INSTALL) -D -m 0644 $(BARE_APP_PKGDIR)/games/$(f) \
			$(TARGET_DIR)/usr/share/bare_app/games/$(f)$(sep))
endef
BARE_APP_POST_INSTALL_TARGET_HOOKS += BARE_APP_INSTALL_GAME_INIS
endif

$(eval $(cmake-package))
