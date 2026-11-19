################################################################################
#
# serious-engine
#
################################################################################

# tx00100xt's SeriousSamClassic (Serious Engine 1.10, both games): its last
# commit (2026-01-14), no release since 1.10.7
SERIOUS_ENGINE_VERSION = 80b9893e5b74e5a2160eaf63e6d6b3f3981dfbbd
SERIOUS_ENGINE_SITE = $(call github,tx00100xt,SeriousSamClassic,$(SERIOUS_ENGINE_VERSION))
SERIOUS_ENGINE_LICENSE = GPL-2.0
SERIOUS_ENGINE_LICENSE_FILES = LICENSE
SERIOUS_ENGINE_DEPENDENCIES = host-bison host-flex sdl2 zlib libvorbis mesa-panfrost
SERIOUS_ENGINE_SUPPORTS_IN_SOURCE_BUILD = NO

# The Entity Class Compiler turns the game's .es files into C++ during the
# build: a program for the build machine (ECC), made before the cross build
SERIOUS_ENGINE_ECC_DIR = $(@D)/ecc-host
define SERIOUS_ENGINE_BUILD_ECC
	mkdir -p $(SERIOUS_ENGINE_ECC_DIR)/Ecc
	$(foreach f,Main.cpp Main.h StdH.h Parser.y Scanner.l bison.simple,\
		cp $(@D)/SamTSE/Sources/Ecc/$(f) $(SERIOUS_ENGINE_ECC_DIR)/Ecc/$(sep))
	cd $(SERIOUS_ENGINE_ECC_DIR) && \
		$(HOST_DIR)/bin/bison -o Ecc/Parser.cpp Ecc/Parser.y -d && \
		cp Ecc/Parser.hpp Ecc/Parser.h && \
		$(HOST_DIR)/bin/flex -oEcc/Scanner.cpp Ecc/Scanner.l && \
		$(HOSTCXX) $(HOST_CXXFLAGS) -w -DPLATFORM_UNIX=1 -D_REENTRANT=1 -I. \
			-o ecc Ecc/Main.cpp Ecc/Parser.cpp Ecc/Scanner.cpp
endef
SERIOUS_ENGINE_PRE_CONFIGURE_HOOKS += SERIOUS_ENGINE_BUILD_ECC

# Both games (the top CMakeLists.txt), portable C (the assembly is x86's),
# the engine's tools too (small; leaving them out breaks the CMake files).
# A "local" installation (prefix /usr/local, the CMake files then install
# into the source tree): the build's names
# (SeriousSam, Debug/lib*.so), no icons made by ImageMagick; the files are
# installed below by hand
SERIOUS_ENGINE_CONF_OPTS = \
	-DCMAKE_INSTALL_PREFIX=/usr/local \
	-DECC=$(SERIOUS_ENGINE_ECC_DIR)/ecc \
	-DUSE_ASM=OFF \
	-DUSE_SYSTEM_SDL2=ON \
	-DUSE_SYSTEM_ZLIB=ON

# /usr/lib/serious-engine/<game>: the program, the game libraries and the
# engine's SE1_10b.gro; /usr/bin/<game> (serious-engine.sh) starts it.
# serioussam: The First Encounter, serioussamse: The Second Encounter
define SERIOUS_ENGINE_INSTALL_GAME
	$(INSTALL) -D -m 0755 $(SERIOUS_ENGINE_BUILDDIR)/$(2)/Sources/SeriousSam \
		$(TARGET_DIR)/usr/lib/serious-engine/$(1)/SeriousSam
	$(foreach l,Engine Game Entities Shaders,\
		$(INSTALL) -D -m 0755 $(SERIOUS_ENGINE_BUILDDIR)/$(2)/Sources/Debug/lib$(l)$(3).so \
			$(TARGET_DIR)/usr/lib/serious-engine/$(1)/lib$(l)$(3).so$(sep))
	$(INSTALL) -D -m 0755 $(SERIOUS_ENGINE_BUILDDIR)/$(2)/Sources/Debug/libamp11lib.so \
		$(TARGET_DIR)/usr/lib/serious-engine/$(1)/libamp11lib.so
	$(INSTALL) -D -m 0644 $(@D)/$(2)/SE1_10b.gro \
		$(TARGET_DIR)/usr/lib/serious-engine/$(1)/SE1_10b.gro
	$(INSTALL) -D -m 0755 $(SERIOUS_ENGINE_PKGDIR)/serious-engine.sh \
		$(TARGET_DIR)/usr/bin/$(1)
endef

define SERIOUS_ENGINE_INSTALL_TARGET_CMDS
	$(call SERIOUS_ENGINE_INSTALL_GAME,serioussam,SamTFE,)
	$(call SERIOUS_ENGINE_INSTALL_GAME,serioussamse,SamTSE,MP)
endef

$(eval $(cmake-package))
