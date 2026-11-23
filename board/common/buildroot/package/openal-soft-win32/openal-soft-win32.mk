################################################################################
#
# openal-soft-win32
#
################################################################################

OPENAL_SOFT_WIN32_VERSION = 1.23.1
OPENAL_SOFT_WIN32_SOURCE = openal-soft-$(OPENAL_SOFT_WIN32_VERSION)-bin.zip
OPENAL_SOFT_WIN32_SITE = https://openal-soft.org/openal-binaries
OPENAL_SOFT_WIN32_LICENSE = LGPL-2.0+
OPENAL_SOFT_WIN32_LICENSE_FILES = COPYING

define OPENAL_SOFT_WIN32_EXTRACT_CMDS
	$(UNZIP) -q -d $(@D) $(OPENAL_SOFT_WIN32_DL_DIR)/$(OPENAL_SOFT_WIN32_SOURCE)
	mv $(@D)/openal-soft-$(OPENAL_SOFT_WIN32_VERSION)-bin/* $(@D)/
	rmdir $(@D)/openal-soft-$(OPENAL_SOFT_WIN32_VERSION)-bin
endef

# the source of this LGPL binary: openal-soft.org/openal-releases, the same version
define OPENAL_SOFT_WIN32_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/bin/Win32/soft_oal.dll $(TARGET_DIR)/usr/share/game-redist/soft_oal.dll
	$(INSTALL) -D -m 0644 $(@D)/COPYING $(TARGET_DIR)/usr/share/game-redist/openal-soft-COPYING
endef

$(eval $(generic-package))
