################################################################################
#
# rbdoom3-bfg
#
################################################################################

# 1.2.0 (October 2019): the last release with the OpenGL renderer of
# DOOM 3 BFG (stencil shadows) next to RB's HDR and shadow maps, and its
# own Bink decoder (no FFmpeg). 1.3.0 on want OpenGL 4.5 or Vulkan.
RBDOOM3_BFG_VERSION = 1.2.0-preview1
RBDOOM3_BFG_SITE = $(call github,RobertBeckebans,RBDOOM-3-BFG,$(RBDOOM3_BFG_VERSION))
RBDOOM3_BFG_LICENSE = GPL-3.0+
RBDOOM3_BFG_LICENSE_FILES = COPYING.txt
RBDOOM3_BFG_SUBDIR = neo
RBDOOM3_BFG_DEPENDENCIES = sdl2 openal zlib mesa-panfrost

# CMake 4 refuses the cmake_minimum_required of 2013; C++17 (the default of
# GCC 14) the dynamic exception specifications of idlib/Heap.h
RBDOOM3_BFG_CONF_OPTS = \
	-DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
	-DCMAKE_CXX_STANDARD=14 \
	-DSDL2=ON \
	-DOPENAL=ON \
	-DBINKDEC=ON \
	-DFFMPEG=OFF \
	-DUSE_VULKAN=OFF \
	-DUSE_INTRINSICS=OFF \
	-DCPU_OPTIMIZATION= \
	-DUSE_PRECOMPILED_HEADERS=OFF \
	-DUSE_SYSTEM_ZLIB=ON \
	-DUSE_EGL=ON \
	-DBUILD_SHARED_LIBS=OFF \
	-DHANDHELD_DEFAULTS=ON

# The engine in /usr/lib/rbdoom3bfg, started by /usr/bin/rbdoom3bfg
# (rbdoom3bfg.sh: OpenAL's sound device from SDL's AUDIODEV, SDL's libGL)
define RBDOOM3_BFG_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/neo/RBDoom3BFG \
		$(TARGET_DIR)/usr/lib/rbdoom3bfg/RBDoom3BFG
	$(INSTALL) -D -m 0755 $(RBDOOM3_BFG_PKGDIR)/rbdoom3bfg.sh \
		$(TARGET_DIR)/usr/bin/rbdoom3bfg
endef

$(eval $(cmake-package))
