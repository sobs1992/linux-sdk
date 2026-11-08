################################################################################
#
# wine-wow64
#
################################################################################

# Wine for arm64 in the WoW64 mode: the Unix side and the 64-bit Windows
# dlls native (aarch64), the 32-bit x86 dlls (i386) for the programs,
# whose x86 code runs in Box64's wowbox64.dll (package wowbox64). The PE
# dlls are built by llvm-mingw. Buildroot's own wine package is x86 only
# and has no PE dlls. The same stable release as Buildroot's wine.
WINE_WOW64_VERSION = 11.0
WINE_WOW64_SOURCE = wine-$(WINE_WOW64_VERSION).tar.xz
WINE_WOW64_SITE = https://dl.winehq.org/wine/source/11.0
WINE_WOW64_LICENSE = LGPL-2.1+
WINE_WOW64_LICENSE_FILES = COPYING.LIB LICENSE
WINE_WOW64_CPE_ID_VENDOR = winehq
WINE_WOW64_CPE_ID_PRODUCT = wine

# The build tools (winebuild, winegcc, widl, wrc, sfnt2fon...) from this
# tree, so that our patches (winegcc 0002) apply to them; built in place,
# where wrc finds nls/locale.nls. sfnt2fon needs FreeType for the fonts.
HOST_WINE_WOW64_DEPENDENCIES = host-bison host-flex host-freetype

HOST_WINE_WOW64_CONF_OPTS = \
	--enable-win64 \
	--disable-tests \
	--with-freetype \
	--without-alsa \
	--without-capi \
	--without-cups \
	--without-dbus \
	--without-ffmpeg \
	--without-fontconfig \
	--without-gettext \
	--without-gettextpo \
	--without-gnutls \
	--without-gphoto \
	--without-gssapi \
	--without-gstreamer \
	--without-krb5 \
	--without-mingw \
	--without-netapi \
	--without-opencl \
	--without-opengl \
	--without-oss \
	--without-pcap \
	--without-pcsclite \
	--without-pulse \
	--without-sane \
	--without-sdl \
	--without-udev \
	--without-unwind \
	--without-usb \
	--without-v4l2 \
	--without-vulkan \
	--without-wayland \
	--without-x

define HOST_WINE_WOW64_BUILD_CMDS
	$(HOST_MAKE_ENV) $(MAKE) -C $(@D) __tooldeps__
endef

# The tools are used from their build directory
define HOST_WINE_WOW64_INSTALL_CMDS
	:
endef

WINE_WOW64_DEPENDENCIES = host-bison host-flex host-wine-wow64 host-llvm-mingw \
	alsa-lib freetype gstreamer1 gst1-plugins-base

WINE_WOW64_PATH = $(HOST_DIR)/llvm-mingw/bin:$(BR_PATH)
WINE_WOW64_CONF_ENV = PATH=$(WINE_WOW64_PATH) CROSSCFLAGS="-O2"
WINE_WOW64_MAKE_ENV = PATH=$(WINE_WOW64_PATH)

# No window system: the graphics driver is winebare.drv (0003). Sound by
# ALSA, fonts by FreeType, media by GStreamer, no network services.
# --enable-nls undoes Buildroot's --disable-nls, which for Wine means "skip
# the nls directory" (its code pages and locale tables: wineserver does not
# start without).
WINE_WOW64_CONF_OPTS = \
	--with-wine-tools=$(HOST_WINE_WOW64_DIR) \
	--enable-nls \
	--enable-archs=aarch64,i386 \
	--with-mingw=llvm-mingw \
	--disable-tests \
	--with-alsa \
	--with-freetype \
	--without-capi \
	--without-coreaudio \
	--without-cups \
	--without-dbus \
	--without-ffmpeg \
	--without-fontconfig \
	--without-gettext \
	--without-gettextpo \
	--without-gnutls \
	--without-gphoto \
	--without-gssapi \
	--with-gstreamer \
	--without-krb5 \
	--without-netapi \
	--without-opencl \
	--without-oss \
	--without-pcap \
	--without-pcsclite \
	--without-pulse \
	--without-sane \
	--without-sdl \
	--without-udev \
	--without-unwind \
	--without-usb \
	--without-v4l2 \
	--without-vulkan \
	--without-wayland \
	--without-x

# winegstreamer decodes with gst1-libav, which needs libavfilter and the
# codecs of old games' sound and videos. VCMI cuts FFmpeg down to Bink and
# Smacker (--disable-everything --disable-avfilter); this file comes after
# vcmi.mk, so these options win (FFmpeg's configure: the last one counts).
FFMPEG_CONF_OPTS += \
	--enable-avfilter \
	--enable-decoder=wmav1,wmav2,wmapro,wmavoice,wmalossless \
	--enable-decoder=mp1,mp1float,mp2,mp2float,mp3,mp3float,vorbis \
	--enable-decoder=adpcm_ms,adpcm_ima_wav,gsm_ms \
	--enable-decoder=wmv1,wmv2,wmv3,vc1,msmpeg4v1,msmpeg4v2,msmpeg4v3 \
	--enable-decoder=mpeg1video,mpeg2video,mpeg4,theora,vp3,vp5,vp6,vp6a,vp6f \
	--enable-decoder=cinepak,msvideo1,msrle,indeo2,indeo3,indeo4,indeo5 \
	--enable-decoder=truemotion1,truemotion2

# OpenGL through EGL (opengl32 needs no libGL)
ifeq ($(BR2_PACKAGE_MESA_PANFROST),y)
WINE_WOW64_DEPENDENCIES += mesa-panfrost
WINE_WOW64_CONF_OPTS += --with-opengl
else
WINE_WOW64_CONF_OPTS += --without-opengl
endif

# winebare.drv (0003) speaks the protocol of bare_app's ports/wine: its
# header, in staging from bare-app, is put next to the driver (makedep
# looks for includes only in the tree, not in CPPFLAGS). Before configure:
# dependencies are built by then, not before the patches.
WINE_WOW64_DEPENDENCIES += bare-app
define WINE_WOW64_WINEBARE_PROTO
	$(INSTALL) -m 0644 $(STAGING_DIR)/usr/include/bare_app/wine/winebare_proto.h \
		$(@D)/dlls/winebare.drv/
endef
WINE_WOW64_PRE_CONFIGURE_HOOKS += WINE_WOW64_WINEBARE_PROTO

# install-lib: the programs and dlls, not the headers and build tools.
# It makes bin/winecfg etc. links to "wine" but not bin/wine itself.
WINE_WOW64_INSTALL_TARGET_OPTS = DESTDIR=$(TARGET_DIR) install-lib

define WINE_WOW64_LOADER_LINK
	ln -sf ../lib/wine/aarch64-unix/wine $(TARGET_DIR)/usr/bin/wine
endef
WINE_WOW64_POST_INSTALL_TARGET_HOOKS += WINE_WOW64_LOADER_LINK

$(eval $(autotools-package))
$(eval $(host-autotools-package))
