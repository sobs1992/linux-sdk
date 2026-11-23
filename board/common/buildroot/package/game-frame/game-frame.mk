################################################################################
#
# game-frame
#
################################################################################

GAME_FRAME_VERSION = 1.0
GAME_FRAME_SITE = $(GAME_FRAME_PKGDIR)/src
GAME_FRAME_SITE_METHOD = local
GAME_FRAME_LICENSE = MIT
GAME_FRAME_DEPENDENCIES = ffmpeg host-pkgconf

define GAME_FRAME_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) -std=gnu11 -Wall -o $(@D)/game-frame \
		$(@D)/game-frame.c \
		`$(PKG_CONFIG_HOST_BINARY) --cflags --libs libavformat libavcodec libswscale libavutil`
endef

define GAME_FRAME_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/game-frame $(TARGET_DIR)/usr/bin/game-frame
endef

$(eval $(generic-package))
