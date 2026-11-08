################################################################################
#
# llvm-mingw
#
################################################################################

# Clang/LLD for Windows targets, prebuilt for an x86_64 Linux build machine:
# the PE parts of wine-wow64 (aarch64 and i386) and wowbox64.dll (aarch64)
LLVM_MINGW_VERSION = 20261104
LLVM_MINGW_SOURCE = llvm-mingw-$(LLVM_MINGW_VERSION)-ucrt-ubuntu-22.04-x86_64.tar.xz
LLVM_MINGW_SITE = https://github.com/mstorsjo/llvm-mingw/releases/download/$(LLVM_MINGW_VERSION)
LLVM_MINGW_LICENSE = Apache-2.0 with LLVM exception, ZPL-2.1 (mingw-w64)
LLVM_MINGW_LICENSE_FILES = LICENSE.TXT

HOST_LLVM_MINGW_DIR_INSTALL = $(HOST_DIR)/llvm-mingw

# Only the aarch64 and i686 targets are used: the others and lldb stay out
define HOST_LLVM_MINGW_INSTALL_CMDS
	rm -rf $(HOST_LLVM_MINGW_DIR_INSTALL)
	mkdir -p $(HOST_LLVM_MINGW_DIR_INSTALL)
	cp -a $(@D)/. $(HOST_LLVM_MINGW_DIR_INSTALL)/
	rm -rf $(HOST_LLVM_MINGW_DIR_INSTALL)/armv7-w64-mingw32 \
		$(HOST_LLVM_MINGW_DIR_INSTALL)/x86_64-w64-mingw32 \
		$(HOST_LLVM_MINGW_DIR_INSTALL)/lib/liblldb.so*
endef

$(eval $(host-generic-package))
