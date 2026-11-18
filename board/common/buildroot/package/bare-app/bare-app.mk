################################################################################
#
# bare-app
#
################################################################################

BARE_APP_VERSION = 1.0
# Source lives in the SDK: <sdk>/apps/bare_app (git submodule with LVGL inside)
BARE_APP_SITE = $(BR2_EXTERNAL_SDK_PATH)/../../../apps/bare_app
BARE_APP_SITE_METHOD = local
# bare_app_doom (ports/doom, built with GAME_DOOM) is doomgeneric: GPLv2;
# bare_app_media (MEDIA) links FFmpeg's LGPL libraries as shared ones
BARE_APP_LICENSE = GPL-2.0+ (bare_app_doom)
BARE_APP_LICENSE_FILES = ports/doom/LICENSE
# Host build trees and the parts of LVGL and doomgeneric that are never
# compiled (~140 MB)
BARE_APP_OVERRIDE_SRCDIR_RSYNC_EXCLUSIONS = \
	--exclude /build-* \
	--exclude /third_party/lvgl/tests \
	--exclude /third_party/lvgl/docs \
	--exclude /third_party/lvgl/demos \
	--exclude /third_party/lvgl/examples \
	--exclude /ports/doom/doomgeneric/screenshots

# Composition of the binary: bare_app's Kconfig, see configs/ in the app.
# Kconfiglib comes with the app; it needs the host's python3.
BARE_APP_CONF_OPTS = \
	-DBARE_APP_DEFCONFIG=$(call qstrip,$(BR2_PACKAGE_BARE_APP_DEFCONFIG))

# The games whose engines this image has, over that defconfig: a game is
# switched on in one place, the firmware's APPS_CONFIG (bare-app.HOMM3=y)
BARE_APP_YN = $(if $(1),y,n)
BARE_APP_KCONFIG = \
	CONFIG_GAME_HOMM3=$(call BARE_APP_YN,$(BR2_PACKAGE_BARE_APP_HOMM3)) \
	CONFIG_GAME_HALFLIFE=$(call BARE_APP_YN,$(BR2_PACKAGE_BARE_APP_HALFLIFE)) \
	CONFIG_GAME_WINE=$(call BARE_APP_YN,$(BR2_PACKAGE_BARE_APP_WINE)) \
	CONFIG_STREAM=$(call BARE_APP_YN,$(BR2_PACKAGE_BARE_APP_STREAM)) \
	CONFIG_SCREEN_MEDIA=$(call BARE_APP_YN,$(BR2_PACKAGE_BARE_APP_MEDIA))
ifeq ($(BR2_PACKAGE_BARE_APP_STREAM),y)
BARE_APP_DEPENDENCIES += libopenh264 host-pkgconf
endif
# the media viewer's player, bare_app_media: FFmpeg and ALSA
ifeq ($(BR2_PACKAGE_BARE_APP_MEDIA),y)
BARE_APP_DEPENDENCIES += ffmpeg alsa-lib host-pkgconf
endif

# FFmpeg for the viewer: the decoders, demuxers and parsers of the
# pictures, videos and sound files a PC has (and the Bink and Smacker
# videos VCMI plays: vcmi.mk leaves FFmpeg to this list then), reading
# files only, nothing else. Its configure takes the last option given for
# each part; wine-wow64.mk, read after this file, adds its own on top.
BARE_APP_FFMPEG_DECODERS = \
	h264 hevc mpeg4 mpeg1video mpeg2video h263 h263p flv msmpeg4v1 msmpeg4v2 \
	msmpeg4v3 wmv1 wmv2 wmv3 vc1 vp3 vp5 vp6 vp6a vp6f vp8 vp9 theora cinepak \
	indeo2 indeo3 indeo4 indeo5 truemotion1 truemotion2 msvideo1 msrle svq1 svq3 \
	rv10 rv20 rv30 rv40 dvvideo qtrle huffyuv ffvhuff rawvideo mjpeg mjpegb \
	interplay_video roq bink smacker \
	png apng bmp gif webp tiff targa pcx ppm pgm pgmyuv pbm pam jpegls \
	aac aac_latm mp1 mp1float mp2 mp2float mp3 mp3float vorbis opus flac alac \
	ac3 eac3 dca ape wavpack cook atrac3 amrnb amrwb gsm_ms wmav1 wmav2 wmapro \
	wmavoice wmalossless pcm_s16le pcm_s16be pcm_u8 pcm_s8 pcm_s24le pcm_s24be \
	pcm_s32le pcm_f32le pcm_f64le pcm_alaw pcm_mulaw adpcm_ms adpcm_ima_wav \
	adpcm_ima_qt adpcm_ima_dk3 adpcm_ima_dk4 interplay_dpcm roq_dpcm \
	binkaudio_dct binkaudio_rdft smackaud
BARE_APP_FFMPEG_DEMUXERS = \
	mov matroska avi asf mpegps mpegts mpegvideo m4v h264 hevc flv ogg mp3 aac \
	flac wav ape wv ac3 eac3 dts aiff au voc amr gif dv rm bink smacker ipmovie \
	roq image2 image_jpeg_pipe image_png_pipe image_bmp_pipe image_webp_pipe \
	image_tiff_pipe image_pcx_pipe image_ppm_pipe image_pgm_pipe image_pam_pipe \
	image_jpegls_pipe
BARE_APP_FFMPEG_PARSERS = \
	h264 hevc mpeg4video mpegvideo mpegaudio aac aac_latm ac3 dca vorbis opus \
	flac vp3 vp8 vp9 vc1 h263 png mjpeg bmp gif webp cook
BARE_APP_FFMPEG_LIST = $(subst $(space),$(comma),$(strip $(1)))
ifeq ($(BR2_PACKAGE_BARE_APP_MEDIA),y)
FFMPEG_CONF_OPTS += \
	--disable-everything --disable-programs --disable-network \
	--disable-avdevice --disable-avfilter \
	--enable-protocol=file,pipe \
	--enable-decoder=$(call BARE_APP_FFMPEG_LIST,$(BARE_APP_FFMPEG_DECODERS)) \
	--enable-demuxer=$(call BARE_APP_FFMPEG_LIST,$(BARE_APP_FFMPEG_DEMUXERS)) \
	--enable-parser=$(call BARE_APP_FFMPEG_LIST,$(BARE_APP_FFMPEG_PARSERS))
endif
# SDL2 games come by game.ini; other programs may too, so only "on"
ifeq ($(BR2_PACKAGE_BARE_APP_SDL),y)
BARE_APP_KCONFIG += CONFIG_GAME_NATIVE=y
endif
# The stress test (GAME_BENCH, bare_app_bench) draws with OpenGL ES 3
# through EGL: Mesa's, so only "off" without it
ifeq ($(BR2_PACKAGE_MESA_PANFROST),y)
BARE_APP_DEPENDENCIES += mesa-panfrost host-pkgconf
else
BARE_APP_KCONFIG += CONFIG_GAME_BENCH=n
endif
BARE_APP_CONF_OPTS += \
	-DBARE_APP_CONFIG_EXTRA="$(subst $(space),;,$(strip $(BARE_APP_KCONFIG)))"

# bare_app's side of its games for the packages that build them (vcmi,
# xash3d-fwgs, wine-wow64, SDL2's bareapp drivers): the protocol
# (games/game_ipc.h, the game side games/game_ipc_client.h), the gamepad
# names (core/input.h) and winebare.drv's protocol, in
# $(STAGING_DIR)/usr/include/bare_app with the layout of bare_app's src/.
# Those packages depend on bare-app; the rest of it goes to the target only.
BARE_APP_INSTALL_STAGING = YES
BARE_APP_HEADERS = games/game_ipc.h games/game_ipc_client.h core/input.h
BARE_APP_INCLUDE = $(STAGING_DIR)/usr/include/bare_app

define BARE_APP_INSTALL_STAGING_CMDS
	$(foreach h,$(BARE_APP_HEADERS),\
		$(INSTALL) -D -m 0644 $(@D)/src/$(h) $(BARE_APP_INCLUDE)/$(h)$(sep))
	$(INSTALL) -D -m 0644 $(@D)/ports/wine/winebare_proto.h \
		$(BARE_APP_INCLUDE)/wine/winebare_proto.h
endef

# /etc/init.d/S<INIT_ORDER>bare-app: the board decides when bare_app
# starts among the other init scripts (the OGA: 06, right after the data
# partitions, before the network)
ifeq ($(BR2_PACKAGE_BARE_APP_AUTOSTART),y)
BARE_APP_INIT_ORDER = $(call qstrip,$(BR2_PACKAGE_BARE_APP_INIT_ORDER))
ifneq ($(filter-out 0 1 2 3 4 5 6 7 8 9,$(subst 9,9 ,$(subst 8,8 ,$(subst 7,7 ,$(subst 6,6 ,$(subst 5,5 ,$(subst 4,4 ,$(subst 3,3 ,$(subst 2,2 ,$(subst 1,1 ,$(subst 0,0 ,$(BARE_APP_INIT_ORDER)))))))))))),)
$(error BR2_PACKAGE_BARE_APP_INIT_ORDER must be digits (two, as S90bare-app), not "$(BARE_APP_INIT_ORDER)")
endif
define BARE_APP_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(BARE_APP_PKGDIR)/bare-app.init \
		$(TARGET_DIR)/etc/init.d/S$(BARE_APP_INIT_ORDER)bare-app
endef
endif

# SDL2 games (BARE_APP_SDL): SDL2 gets the bareapp drivers (sdl2/, with
# bare_app's protocol headers next to them) and, with Mesa, OpenGL ES,
# which it loads at run time. As in vcmi.mk: hooks and options of another
# package are expanded when they are used, so options added here win.
ifeq ($(BR2_PACKAGE_BARE_APP_SDL),y)
define BARE_APP_SDL2_DRIVERS
	$(APPLY_PATCHES) $(SDL2_DIR) $(BARE_APP_PKGDIR)/sdl2 \*.patch
endef
SDL2_POST_PATCH_HOOKS += BARE_APP_SDL2_DRIVERS
# the headers once bare-app is in staging: dependencies come before configure
define BARE_APP_SDL2_HEADERS
	$(INSTALL) -m 0644 $(addprefix $(BARE_APP_INCLUDE)/,$(BARE_APP_HEADERS)) \
		$(SDL2_DIR)/src/video/bareapp/
endef
SDL2_PRE_CONFIGURE_HOOKS += BARE_APP_SDL2_HEADERS
SDL2_CONF_OPTS += --enable-bareapp
# SDL2_DEPENDENCIES += would come too late: Buildroot makes a package's
# rules when it reads its .mk, before this one. So SDL2 is configured
# after bare-app (the headers) and Mesa (OpenGL ES) by a rule of our own.
BARE_APP_SDL2_AFTER = bare-app
ifeq ($(BR2_PACKAGE_MESA_PANFROST),y)
BARE_APP_SDL2_AFTER += mesa-panfrost
SDL2_CONF_OPTS += --enable-video-opengles --enable-video-opengles2 --disable-video-opengles1
endif
$(SDL2_TARGET_CONFIGURE): | $(BARE_APP_SDL2_AFTER)
endif

# The game.ini (bare_app's menu entry) of SDL2 games that are Buildroot's
# own packages and all in the image. A game whose files are on the games
# card brings its game.ini there (the SDK's games/<game>/overlay: DOOM 3,
# RTCW, UT2004), so the menu follows the card without a new rootfs
BARE_APP_GAME_INIS-$(BR2_PACKAGE_BARE_APP_CHOCOLATE_DOOM) += chocolate-doom.ini
ifneq ($(BARE_APP_GAME_INIS-y),)
define BARE_APP_INSTALL_GAME_INIS
	$(foreach f,$(BARE_APP_GAME_INIS-y),\
		$(INSTALL) -D -m 0644 $(BARE_APP_PKGDIR)/games/$(f) \
			$(TARGET_DIR)/usr/share/bare_app/games/$(f)$(sep))
endef
BARE_APP_POST_INSTALL_TARGET_HOOKS += BARE_APP_INSTALL_GAME_INIS
endif

$(eval $(cmake-package))
