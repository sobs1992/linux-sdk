################################################################################
#
# sdl12-compat
#
################################################################################

SDL12_COMPAT_VERSION = 1.2.78
SDL12_COMPAT_SITE = https://github.com/libsdl-org/sdl12-compat/archive/release-$(SDL12_COMPAT_VERSION)
SDL12_COMPAT_LICENSE = Zlib
SDL12_COMPAT_LICENSE_FILES = LICENSE.txt
SDL12_COMPAT_DEPENDENCIES = sdl2
SDL12_COMPAT_INSTALL_STAGING = YES

# libSDL-1.2.so.0 and the headers; it dlopens libSDL2-2.0.so.0 at run time
# (SDL2's headers only for the build)
SDL12_COMPAT_CONF_OPTS = -DSDL12TESTS=OFF -DSDL12DEVEL=ON -DSTATICDEVEL=OFF

$(eval $(cmake-package))
