################################################################################
#
# cabextract
#
################################################################################

CABEXTRACT_VERSION = 1.11
CABEXTRACT_SITE = https://www.cabextract.org.uk
CABEXTRACT_LICENSE = GPL-3.0+
CABEXTRACT_LICENSE_FILES = COPYING

# its own copy of libmspack (Buildroot's libmspack package is not needed)
CABEXTRACT_CONF_OPTS = --without-external-libmspack
# configure cannot run its fnmatch test when cross-compiling and takes a
# replacement it then does not link (rpl_fnmatch); glibc's fnmatch works
CABEXTRACT_CONF_ENV = ac_cv_func_fnmatch_works=yes

$(eval $(autotools-package))
