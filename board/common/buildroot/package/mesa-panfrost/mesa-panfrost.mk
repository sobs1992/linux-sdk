################################################################################
#
# mesa-panfrost
#
################################################################################

# The last release whose panfrost builds without LLVM (25.1 needs mesa_clc
# for libpan). 24.3 faulted on the GPU in Half-Life. From GitLab: the same
# tag, archive.mesa3d.org serves it at a few kB/s.
MESA_PANFROST_VERSION = 25.0.7
MESA_PANFROST_SOURCE = mesa-mesa-$(MESA_PANFROST_VERSION).tar.gz
MESA_PANFROST_SITE = https://gitlab.freedesktop.org/mesa/mesa/-/archive/mesa-$(MESA_PANFROST_VERSION)
MESA_PANFROST_LICENSE = MIT, SGI, Khronos
MESA_PANFROST_LICENSE_FILES = docs/license.rst
MESA_PANFROST_INSTALL_STAGING = YES

MESA_PANFROST_DEPENDENCIES = \
	host-bison \
	host-flex \
	host-python-mako \
	host-python-pyyaml \
	libdrm \
	zlib

MESA_PANFROST_CONF_OPTS = \
	-Dplatforms= \
	-Dgallium-drivers=panfrost \
	-Dvulkan-drivers= \
	-Degl=enabled \
	-Dgbm=enabled \
	-Dgles1=disabled \
	-Dgles2=enabled \
	-Dopengl=false \
	-Dglx=disabled \
	-Dllvm=disabled \
	-Dshared-glapi=enabled \
	-Dxmlconfig=disabled \
	-Dexpat=disabled \
	-Dgallium-va=disabled \
	-Dgallium-vdpau=disabled \
	-Dgallium-xa=disabled \
	-Dgallium-nine=false \
	-Dgallium-opencl=disabled \
	-Dgallium-rusticl=false \
	-Dmicrosoft-clc=disabled \
	-Dvalgrind=disabled \
	-Dlibunwind=disabled \
	-Dlmsensors=disabled \
	-Dzstd=disabled \
	-Dbuild-tests=false \
	-Dtools=

$(eval $(meson-package))
