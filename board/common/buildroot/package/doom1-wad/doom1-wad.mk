################################################################################
#
# doom1-wad
#
################################################################################

# Same archive as Buildroot's package/doom-wad
DOOM1_WAD_VERSION = 1.9
DOOM1_WAD_SOURCE = doom$(subst .,,$(DOOM1_WAD_VERSION))s.zip
DOOM1_WAD_SITE = http://www.jbserver.com/downloads/games/doom/misc/shareware
DOOM1_WAD_LICENSE = Doom shareware (freely redistributable unmodified)

define DOOM1_WAD_EXTRACT_CMDS
	$(UNZIP) -p $(DOOM1_WAD_DL_DIR)/$(DOOM1_WAD_SOURCE) 'DOOMS_19.[12]' > \
		$(@D)/doom-$(DOOM1_WAD_VERSION).zip
	$(UNZIP) -d $(@D) $(@D)/doom-$(DOOM1_WAD_VERSION).zip DOOM1.WAD
endef

define DOOM1_WAD_INSTALL_TARGET_CMDS
	$(INSTALL) -m 0644 -D $(@D)/DOOM1.WAD \
		$(TARGET_DIR)/usr/share/games/doom/doom1.wad
endef

$(eval $(generic-package))
