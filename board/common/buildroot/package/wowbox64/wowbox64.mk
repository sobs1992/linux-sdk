################################################################################
#
# wowbox64
#
################################################################################

# Box64's WoW64 build: wowbox64.dll, the x86 CPU of wine-wow64 (32-bit
# Windows programs on arm64). No release has it working yet (v0.4.4
# faults on exceptions in JIT code, fixed by a489cfe7d): a commit of main
# (2026-11-07). Only the PE dll is built, not the Linux box64.
WOWBOX64_VERSION = 37f5e4b7b0002a247c04866a44d0321e92cfef3c
WOWBOX64_SITE = $(call github,ptitSeb,box64,$(WOWBOX64_VERSION))
WOWBOX64_LICENSE = MIT
WOWBOX64_LICENSE_FILES = LICENSE
WOWBOX64_DEPENDENCIES = host-llvm-mingw

WOWBOX64_PATH = $(HOST_DIR)/llvm-mingw/bin:$(BR_PATH)

# The main project only decides the dynarec sources and runs the
# wine/wow64 project (ExternalProject, llvm-mingw's aarch64 clang)
define WOWBOX64_CONFIGURE_CMDS
	rm -rf $(@D)/build
	mkdir -p $(@D)/build
	cd $(@D)/build && PATH=$(WOWBOX64_PATH) $(BR2_CMAKE) .. \
		-DCMAKE_SYSTEM_NAME=Linux \
		-DCMAKE_SYSTEM_PROCESSOR=aarch64 \
		-DCMAKE_C_COMPILER="$(TARGET_CC)" \
		-DCMAKE_BUILD_TYPE=Release \
		-DARM64=ON \
		-DWOW64=ON \
		-DNOGIT=ON
endef

define WOWBOX64_BUILD_CMDS
	PATH=$(WOWBOX64_PATH) $(MAKE) -C $(@D)/build wowbox64
endef

define WOWBOX64_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/build/wowbox64-prefix/src/wowbox64-build/wowbox64.dll \
		$(TARGET_DIR)/usr/lib/wine/aarch64-windows/wowbox64.dll
	$(HOST_DIR)/llvm-mingw/bin/llvm-strip \
		$(TARGET_DIR)/usr/lib/wine/aarch64-windows/wowbox64.dll
endef

$(eval $(generic-package))
