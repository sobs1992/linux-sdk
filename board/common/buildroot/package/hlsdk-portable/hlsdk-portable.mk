################################################################################
#
# hlsdk-portable
#
################################################################################

# Half-Life itself (branch master), a commit of 2026-11-05, with its
# freevgui submodule
HLSDK_PORTABLE_VERSION = a5049a40ec852ea01d0f38f167e7c3227a850ccf
HLSDK_PORTABLE_SITE = https://github.com/FWGS/hlsdk-portable.git
HLSDK_PORTABLE_SITE_METHOD = git
HLSDK_PORTABLE_GIT_SUBMODULES = YES
HLSDK_PORTABLE_LICENSE = Half-Life 1 SDK License (non-commercial)
HLSDK_PORTABLE_LICENSE_FILES = LICENSE

# The libraries go into <prefix>/valve: next to the engine, where bare_app
# looks for them (the game files are elsewhere, read only)
HLSDK_PORTABLE_CONF_OPTS = -T release --prefix=/usr/lib/xash3d

$(eval $(waf-package))
