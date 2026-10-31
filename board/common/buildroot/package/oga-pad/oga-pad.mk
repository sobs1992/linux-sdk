################################################################################
#
# oga-pad
#
################################################################################

OGA_PAD_VERSION = 1.0
OGA_PAD_SITE = $(BR2_EXTERNAL_SDK_PATH)/../../../apps/oga-pad
OGA_PAD_SITE_METHOD = local
OGA_PAD_LICENSE = GPL-2.0

define OGA_PAD_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(TARGET_CONFIGURE_OPTS)
endef

define OGA_PAD_INSTALL_TARGET_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) DESTDIR=$(TARGET_DIR) install
endef

ifeq ($(BR2_PACKAGE_OGA_PAD_AUTOSTART),y)
define OGA_PAD_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(OGA_PAD_PKGDIR)/S90oga-pad \
		$(TARGET_DIR)/etc/init.d/S90oga-pad
endef
endif

$(eval $(generic-package))
