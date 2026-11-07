################################################################################
#
# xash3d-fwgs
#
################################################################################

# No releases: a commit of master (2026-11-06), with its submodules
# (menu, codecs, mbedtls, the engine's resources in xash-extras)
XASH3D_FWGS_VERSION = e9b94dc1a89bcd8867e2d16b37cd6f1cbd4dbd1c
XASH3D_FWGS_SITE = https://github.com/FWGS/xash3d-fwgs.git
XASH3D_FWGS_SITE_METHOD = git
XASH3D_FWGS_GIT_SUBMODULES = YES
# No licence file in the tree: every source carries the GPLv3+ header
XASH3D_FWGS_LICENSE = GPL-3.0+
XASH3D_FWGS_LICENSE_FILES = Documentation/gpl_copyright_header.h
XASH3D_FWGS_DEPENDENCIES = alsa-lib zlib

# 0001 adds the bare_app platform; game_ipc.h is read from the SDK's apps/.
# -P (packaging): the launcher in /usr/bin, the libraries in
# /usr/lib/xash3d, extras.pk3 in /usr/share/xash3d. Fonts by stb_truetype
# (no freetype), codecs from the bundled submodules, not what staging has.
XASH3D_FWGS_CONF_OPTS = \
	-T release \
	-P \
	--disable-werror \
	--enable-bare-app=$(BR2_EXTERNAL_SDK_PATH)/../../../apps/bare_app/src \
	--enable-soft \
	--disable-gl \
	--enable-stbtt \
	--enable-bundled-deps

# With Mesa: the OpenGL ES renderer (ref_gles3compat), drawn off screen by
# the GPU through EGL; bare_app picks it when it is installed
ifeq ($(BR2_PACKAGE_MESA_PANFROST),y)
XASH3D_FWGS_DEPENDENCIES += mesa-panfrost
XASH3D_FWGS_CONF_OPTS += --enable-gles3compat
endif

# Russian of our own, into extras.pk3 (packed at build time): the strings
# of mainui that Steam's valve_russian/ lacks, and Half-Life's messages
# (titles.txt), in cp1251 since the client draws them byte by byte
define XASH3D_FWGS_RUSSIAN
	mkdir -p $(@D)/3rdparty/extras/xash-extras/resource
	cp $(XASH3D_FWGS_PKGDIR)/russian/mainui_russian.txt \
		$(@D)/3rdparty/extras/xash-extras/resource/
	iconv -f UTF-8 -t CP1251 $(XASH3D_FWGS_PKGDIR)/russian/titles_valve_russian.txt \
		> $(@D)/3rdparty/extras/xash-extras/titles_valve_russian.txt
endef
XASH3D_FWGS_POST_PATCH_HOOKS += XASH3D_FWGS_RUSSIAN

$(eval $(waf-package))
