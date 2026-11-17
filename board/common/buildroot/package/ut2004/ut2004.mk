################################################################################
#
# ut2004
#
################################################################################

# Only the starter: the game is the player's (/games/ut2004)
UT2004_LICENSE = MIT
UT2004_DEPENDENCIES = box64 sdl12-compat

define UT2004_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(UT2004_PKGDIR)/ut2004.sh $(TARGET_DIR)/usr/bin/ut2004
endef

$(eval $(generic-package))
