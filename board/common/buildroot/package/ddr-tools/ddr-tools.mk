################################################################################
#
# ddr-tools
#
################################################################################

DDR_TOOLS_VERSION = 1.0
DDR_TOOLS_SITE = $(DDR_TOOLS_PKGDIR)/src
DDR_TOOLS_SITE_METHOD = local
DDR_TOOLS_LICENSE = MIT

DDR_TOOLS_PROGRAMS = ddr-phyreg ddr-eyescan ddr-calibrate

define DDR_TOOLS_BUILD_CMDS
	$(foreach p,$(DDR_TOOLS_PROGRAMS),\
		$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) -std=gnu11 -Wall -pthread \
			-o $(@D)/$(p) $(@D)/$(p).c$(sep))
endef

define DDR_TOOLS_INSTALL_TARGET_CMDS
	$(foreach p,$(DDR_TOOLS_PROGRAMS),\
		$(INSTALL) -D -m 0755 $(@D)/$(p) $(TARGET_DIR)/usr/sbin/$(p)$(sep))
endef

$(eval $(generic-package))
