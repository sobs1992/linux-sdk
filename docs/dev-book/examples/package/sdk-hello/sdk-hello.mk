################################################################################
#
# sdk-hello
#
################################################################################

SDK_HELLO_VERSION = 1.0
# Source lives in the SDK itself: <sdk>/apps/hello
SDK_HELLO_SITE = $(BR2_EXTERNAL_SDK_PATH)/../../../apps/hello
SDK_HELLO_SITE_METHOD = local
SDK_HELLO_LICENSE = GPL-2.0

define SDK_HELLO_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(TARGET_CONFIGURE_OPTS)
endef

define SDK_HELLO_INSTALL_TARGET_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) DESTDIR=$(TARGET_DIR) install
endef

define SDK_HELLO_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(SDK_HELLO_PKGDIR)/S90sdk-hello \
		$(TARGET_DIR)/etc/init.d/S90sdk-hello
endef

$(eval $(generic-package))
