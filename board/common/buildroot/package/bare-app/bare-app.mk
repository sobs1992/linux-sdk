################################################################################
#
# bare-app
#
################################################################################

BARE_APP_VERSION = 1.0
# Source lives in the SDK: <sdk>/apps/bare_app (git submodule with LVGL inside)
BARE_APP_SITE = $(BR2_EXTERNAL_SDK_PATH)/../../../apps/bare_app
BARE_APP_SITE_METHOD = local
# Host build trees and the parts of LVGL that are never compiled (~140 MB)
BARE_APP_OVERRIDE_SRCDIR_RSYNC_EXCLUSIONS = \
	--exclude /build-* \
	--exclude /third_party/lvgl/tests \
	--exclude /third_party/lvgl/docs \
	--exclude /third_party/lvgl/demos \
	--exclude /third_party/lvgl/examples

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

$(eval $(cmake-package))
