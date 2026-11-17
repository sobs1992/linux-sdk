################################################################################
#
# box64
#
################################################################################

# The commit of wowbox64 (box64's main, 2026-11-07): one source for both,
# downloaded once
BOX64_VERSION = 37f5e4b7b0002a247c04866a44d0321e92cfef3c
BOX64_SITE = $(call github,ptitSeb,box64,$(BOX64_VERSION))
BOX64_SOURCE = wowbox64-$(BOX64_VERSION).tar.gz
BOX64_DL_SUBDIR = wowbox64
BOX64_LICENSE = MIT
BOX64_LICENSE_FILES = LICENSE

# ODROIDN2: the S922X's tuning (dynarec on, SAVE_MEM); no box32 (no
# 32-bit x86 Linux programs here). Its install would add binfmt entries
# and bash/python wrappers: games start box64 themselves, so only the
# program is installed by CMake (not its configurator, a desktop tool) and
# the rest by hand below: the per-program
# settings (/etc/box64.box64rc, read by box64 at start) and the x86_64 C++
# runtimes of x64lib (not its libssl/libcrypto/mbedtls).
BOX64_CONF_OPTS = \
	-DODROIDN2=ON \
	-DNOGIT=ON \
	-DNO_LIB_INSTALL=ON \
	-DNO_CONF_INSTALL=ON

BOX64_X64LIB = libstdc++.so.5 libstdc++.so.6 libgcc_s.so.1
# they are x86_64 code (run by box64), not the target's
BOX64_BIN_ARCH_EXCLUDE = /usr/lib/box64-x86_64-linux-gnu

define BOX64_X64LIBS
	rm -f $(TARGET_DIR)/usr/bin/box64-configurator \
		$(TARGET_DIR)/usr/share/applications/box64-configurator.desktop
	$(INSTALL) -D -m 0644 $(@D)/system/box64.box64rc $(TARGET_DIR)/etc/box64.box64rc
	$(foreach l,$(BOX64_X64LIB),\
		$(INSTALL) -D -m 0644 $(@D)/x64lib/$(l) \
			$(TARGET_DIR)/usr/lib/box64-x86_64-linux-gnu/$(l)$(sep))
endef
BOX64_POST_INSTALL_TARGET_HOOKS += BOX64_X64LIBS

$(eval $(cmake-package))
