################################################################################
#
# innoextract
#
################################################################################

# master of 2025-02-06: Inno Setup up to 6.4 (1.9, 2020, stops at 6.0.5)
INNOEXTRACT_VERSION = 6e9e34ed0876014fdb46e684103ef8c3605e382e
INNOEXTRACT_SITE = $(call github,dscharrer,innoextract,$(INNOEXTRACT_VERSION))
INNOEXTRACT_LICENSE = Zlib
INNOEXTRACT_LICENSE_FILES = LICENSE
INNOEXTRACT_DEPENDENCIES = boost xz

INNOEXTRACT_CONF_OPTS = \
	-DUSE_LZMA=ON \
	-DBUILD_TESTS=OFF \
	-DUSE_STATIC_LIBS=OFF \
	-DUSE_LTO=OFF \
	-DSET_OPTIMIZATION_FLAGS=OFF

$(eval $(cmake-package))
