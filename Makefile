# OdroidLinux SDK: top-level build orchestrator.
#
# Every component (TF-A, U-Boot, Linux, Buildroot) lives in its own git
# repository under src/ and is built out-of-tree into output/<fw>/.
# A firmware config (configs/<fw>_defconfig) selects component configs and
# the SD card layout; "make image" glues the built components into an .img.
#
#   make oga_defconfig      select firmware config
#   make                    build everything and assemble the image
#   make help               list all targets

SDK_DIR    := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OUTPUT_DIR ?= $(SDK_DIR)/output
DL_DIR     ?= $(SDK_DIR)/dl
CROSS_COMPILE ?= aarch64-linux-gnu-
JOBS       ?= $(shell nproc)

# Command-line variables of this Makefile must not leak into component builds
MAKEOVERRIDES :=

.DEFAULT_GOAL := all

# ----------------------------------------------------------------------------
# Firmware config selection

FW ?= $(shell cat $(OUTPUT_DIR)/.fw 2>/dev/null)

# Output locations, usable in firmware configs
OUT           := $(OUTPUT_DIR)/$(FW)
IMAGES_DIR    := $(OUT)/images
LINUX_INSTALL := $(OUT)/linux-install

ifeq ($(filter $(notdir $(wildcard $(SDK_DIR)/configs/*_defconfig)),$(MAKECMDGOALS)),)
ifneq ($(FW),)
FW_CONFIG := $(SDK_DIR)/configs/$(FW)_defconfig
ifeq ($(wildcard $(FW_CONFIG)),)
$(error Firmware config $(FW_CONFIG) not found)
endif
include $(FW_CONFIG)
endif
endif

FW_DEFCONFIGS := $(notdir $(wildcard $(SDK_DIR)/configs/*_defconfig))
.PHONY: $(FW_DEFCONFIGS)
$(FW_DEFCONFIGS): %_defconfig:
	@mkdir -p $(OUTPUT_DIR)
	@echo $* > $(OUTPUT_DIR)/.fw
	@echo "Firmware config: $* (output: $(OUTPUT_DIR)/$*)"

# Absolute path for a path relative to the SDK root
sdkpath = $(if $(filter /%,$(1)),$(1),$(SDK_DIR)/$(1))
# In-tree defconfig names stay as they are, paths become absolute
cfgpath = $(if $(findstring /,$(1)),$(call sdkpath,$(1)),$(1))
# "path<sep>suffix" -> "/abs/path<sep>suffix" ($(1)=list $(2)=separator)
sdkpath-pairs = $(foreach e,$(1),$(call sdkpath,$(firstword $(subst $(2), ,$(e))))$(if $(findstring $(2),$(e)),$(2)$(lastword $(subst $(2), ,$(e)))))

LINUX_ARCH  ?= arm64
LINUX_IMAGE ?= Image

TFA_SRC   := $(call sdkpath,$(TFA_SRC))
UBOOT_SRC := $(call sdkpath,$(UBOOT_SRC))
LINUX_SRC := $(call sdkpath,$(LINUX_SRC))
BUILDROOT_SRC      := $(call sdkpath,$(BUILDROOT_SRC))
BUILDROOT_EXTERNAL := $(call sdkpath,$(BUILDROOT_EXTERNAL))

UBOOT_DEFCONFIG     := $(call cfgpath,$(UBOOT_DEFCONFIG))
LINUX_DEFCONFIG     := $(call cfgpath,$(LINUX_DEFCONFIG))
BUILDROOT_DEFCONFIG := $(call cfgpath,$(BUILDROOT_DEFCONFIG))
UBOOT_FRAGMENTS     := $(foreach f,$(UBOOT_FRAGMENTS),$(call sdkpath,$(f)))
LINUX_FRAGMENTS     := $(foreach f,$(LINUX_FRAGMENTS),$(call sdkpath,$(f)))

# ----------------------------------------------------------------------------
# Kconfig helpers (U-Boot and Linux)
#
# $(OBJ)/.config is regenerated when its inputs change: the defconfig file,
# a fragment, or the list of inputs itself (stored in .sdk-inputs). Changes
# made with *-menuconfig are kept until then; use *-savedefconfig to keep
# them for good.

# $(1)=objdir $(2)=inputs: rewrite the stamp only when the inputs differ
define inputs-stamp
$(shell mkdir -p $(1) && { test "$$(cat $(1)/.sdk-inputs 2>/dev/null)" = "$(strip $(2))" || echo "$(strip $(2))" > $(1)/.sdk-inputs; })
endef

# $(1)=make command $(2)=objdir $(3)=defconfig $(4)=fragments $(5)=src
define kconfig-configure
	@echo ">>> Configuring $(2)"
	$(if $(findstring /,$(3)),cp $(3) $(2)/.config && $(1) olddefconfig,$(1) $(3))
	$(if $(strip $(4)),$(5)/scripts/kconfig/merge_config.sh -m -O $(2) $(2)/.config $(4) && $(1) olddefconfig && $(SDK_DIR)/scripts/kconfig-check.sh $(2)/.config $(4))
endef

# $(1)=make command $(2)=objdir $(3)=defconfig
define kconfig-savedefconfig
	$(1) savedefconfig
	@if [ -n "$(findstring /,$(3))" ]; then cp $(2)/defconfig $(3) && echo "Saved to $(3)"; else \
		echo "Saved to $(2)/defconfig. The firmware config uses the in-tree '$(3)':"; \
		echo "move the changes to a fragment, or point the *_DEFCONFIG at a file."; fi
endef

.PHONY: check-fw check-cc
check-fw:
	@test -n "$(FW)" || { echo "No firmware config selected: run 'make <name>_defconfig'."; \
		echo "Available:"; ls $(SDK_DIR)/configs | sed -n 's/_defconfig$$//p' | sed 's/^/  /'; exit 1; }

# Cross compiler for TF-A, U-Boot and Linux (Buildroot builds its own)
check-cc: check-fw
	@command -v $(CROSS_COMPILE)gcc >/dev/null || { echo "$(CROSS_COMPILE)gcc not found."; \
		echo "Install it (e.g. 'sudo apt install gcc-$(patsubst %-,%,$(CROSS_COMPILE))') or pass CROSS_COMPILE=..."; exit 1; }

# ----------------------------------------------------------------------------
# Trusted Firmware-A (only for boards with TFA_PLAT)

TFA_OUT  := $(OUT)/tf-a
TFA_BL31 := $(TFA_OUT)/$(TFA_PLAT)/release/bl31/bl31.elf
TFA_MAKE  = $(MAKE) -C $(TFA_SRC) BUILD_BASE=$(TFA_OUT) PLAT=$(TFA_PLAT) \
            CROSS_COMPILE=$(CROSS_COMPILE) $(TFA_MAKE_ARGS)

.PHONY: tfa tfa-clean
tfa: check-cc
	@test -n "$(TFA_PLAT)" || { echo "$(FW) does not use TF-A (TFA_PLAT is not set)"; exit 1; }
	$(TFA_MAKE) -j$(JOBS) bl31

tfa-clean: check-fw
	rm -rf $(TFA_OUT)

# ----------------------------------------------------------------------------
# U-Boot

UBOOT_OUT := $(OUT)/u-boot
UBOOT_MAKE = $(MAKE) -C $(UBOOT_SRC) O=$(UBOOT_OUT) CROSS_COMPILE=$(CROSS_COMPILE) $(UBOOT_MAKE_ARGS)

ifeq ($(UBOOT_BL31),tf-a)
UBOOT_BL31_FILE := $(TFA_BL31)
UBOOT_DEPS := tfa
else ifneq ($(UBOOT_BL31),)
UBOOT_BL31_FILE := $(call sdkpath,$(UBOOT_BL31))
endif

# Rockchip legacy uboot.img/trust.img for the SPI miniloader
ifeq ($(RK_LEGACY),y)
RKBIN_DIR     := $(call sdkpath,$(RKBIN_DIR))
RK_TRUST_BL31 := $(call sdkpath,$(RK_TRUST_BL31))
RK_LEGACY_IMAGES := $(IMAGES_DIR)/uboot.img $(IMAGES_DIR)/trust.img
endif

ifneq ($(FW),)
$(call inputs-stamp,$(UBOOT_OUT),$(UBOOT_DEFCONFIG) $(UBOOT_FRAGMENTS))
endif

$(UBOOT_OUT)/.config: $(UBOOT_OUT)/.sdk-inputs $(filter /%,$(UBOOT_DEFCONFIG)) $(UBOOT_FRAGMENTS)
	$(call kconfig-configure,$(UBOOT_MAKE),$(UBOOT_OUT),$(UBOOT_DEFCONFIG),$(UBOOT_FRAGMENTS),$(UBOOT_SRC))

.PHONY: uboot uboot-configure uboot-menuconfig uboot-savedefconfig uboot-clean
uboot: check-cc $(UBOOT_DEPS) $(UBOOT_OUT)/.config
	$(UBOOT_MAKE) -j$(JOBS) $(if $(UBOOT_BL31_FILE),BL31=$(UBOOT_BL31_FILE))
	@mkdir -p $(IMAGES_DIR)
	cp $(addprefix $(UBOOT_OUT)/,$(UBOOT_IMAGES)) $(IMAGES_DIR)/
ifeq ($(RK_LEGACY),y)
	$(SDK_DIR)/scripts/rk-legacy-pack.sh $(RKBIN_DIR) $(UBOOT_OUT) $(RK_TRUST_BL31) $(IMAGES_DIR)
endif

uboot-configure: check-cc $(UBOOT_OUT)/.config

uboot-menuconfig: check-cc $(UBOOT_OUT)/.config
	$(UBOOT_MAKE) menuconfig

uboot-savedefconfig: check-cc $(UBOOT_OUT)/.config
	$(call kconfig-savedefconfig,$(UBOOT_MAKE),$(UBOOT_OUT),$(UBOOT_DEFCONFIG))

uboot-clean: check-fw
	rm -rf $(UBOOT_OUT) $(addprefix $(IMAGES_DIR)/,$(notdir $(UBOOT_IMAGES))) $(RK_LEGACY_IMAGES)

# ----------------------------------------------------------------------------
# Boot firmware blobs (e.g. Raspberry Pi GPU firmware), fetched by URL and
# checked against BOOTFW_HASH, then copied to images/

ifneq ($(strip $(BOOTFW_FILES)),)
BOOTFW_DEPS := bootfw
endif

.PHONY: bootfw bootfw-clean
bootfw: check-fw
	@test -n "$(strip $(BOOTFW_FILES))" || { echo "$(FW) has no boot firmware (BOOTFW_FILES is not set)"; exit 1; }
	$(SDK_DIR)/scripts/fetch-files.sh $(BOOTFW_URL) $(DL_DIR)/$(BOOTFW_NAME) \
		$(call sdkpath,$(BOOTFW_HASH)) $(IMAGES_DIR) $(BOOTFW_FILES)

bootfw-clean: check-fw
	rm -f $(addprefix $(IMAGES_DIR)/,$(BOOTFW_FILES))

# ----------------------------------------------------------------------------
# Linux

LINUX_OUT := $(OUT)/linux
LINUX_MAKE = $(MAKE) -C $(LINUX_SRC) O=$(LINUX_OUT) ARCH=$(LINUX_ARCH) CROSS_COMPILE=$(CROSS_COMPILE) $(LINUX_MAKE_ARGS)

ifneq ($(FW),)
$(call inputs-stamp,$(LINUX_OUT),$(LINUX_DEFCONFIG) $(LINUX_FRAGMENTS))
endif

$(LINUX_OUT)/.config: $(LINUX_OUT)/.sdk-inputs $(filter /%,$(LINUX_DEFCONFIG)) $(LINUX_FRAGMENTS)
	$(call kconfig-configure,$(LINUX_MAKE),$(LINUX_OUT),$(LINUX_DEFCONFIG),$(LINUX_FRAGMENTS),$(LINUX_SRC))

.PHONY: linux linux-configure linux-menuconfig linux-savedefconfig linux-clean
linux: check-cc $(LINUX_OUT)/.config
	$(LINUX_MAKE) -j$(JOBS) $(LINUX_IMAGE) modules $(LINUX_DTBS)
	rm -rf $(LINUX_INSTALL)
	mkdir -p $(LINUX_INSTALL)/modules
	cp $(LINUX_OUT)/arch/$(LINUX_ARCH)/boot/$(LINUX_IMAGE) $(LINUX_OUT)/System.map $(LINUX_OUT)/.config $(LINUX_INSTALL)/
	$(foreach d,$(LINUX_DTBS),install -D -m 644 $(LINUX_OUT)/arch/$(LINUX_ARCH)/boot/dts/$(d) $(LINUX_INSTALL)/dtbs/$(d) &&) true
	$(LINUX_MAKE) INSTALL_MOD_PATH=$(LINUX_INSTALL)/modules INSTALL_MOD_STRIP=1 modules_install

linux-configure: check-cc $(LINUX_OUT)/.config

linux-menuconfig: check-cc $(LINUX_OUT)/.config
	$(LINUX_MAKE) menuconfig

linux-savedefconfig: check-cc $(LINUX_OUT)/.config
	$(call kconfig-savedefconfig,$(LINUX_MAKE),$(LINUX_OUT),$(LINUX_DEFCONFIG))

linux-clean: check-fw
	rm -rf $(LINUX_OUT) $(LINUX_INSTALL)

# ----------------------------------------------------------------------------
# Root filesystem (Buildroot)

ROOTFS_OUT := $(OUT)/buildroot
ROOTFS_MAKE = BR2_DL_DIR=$(DL_DIR) $(MAKE) -C $(BUILDROOT_SRC) O=$(ROOTFS_OUT) \
              BR2_EXTERNAL=$(BUILDROOT_EXTERNAL) $(BUILDROOT_MAKE_ARGS)

ifneq ($(FW),)
$(call inputs-stamp,$(ROOTFS_OUT),$(BUILDROOT_DEFCONFIG) $(BUILDROOT_EXTERNAL))
endif

$(ROOTFS_OUT)/.config: $(ROOTFS_OUT)/.sdk-inputs $(filter /%,$(BUILDROOT_DEFCONFIG))
	@echo ">>> Configuring $(ROOTFS_OUT)"
	$(if $(findstring /,$(BUILDROOT_DEFCONFIG)),$(ROOTFS_MAKE) defconfig BR2_DEFCONFIG=$(BUILDROOT_DEFCONFIG),$(ROOTFS_MAKE) $(BUILDROOT_DEFCONFIG))

.PHONY: rootfs rootfs-configure rootfs-menuconfig rootfs-savedefconfig rootfs-sdk rootfs-make rootfs-clean
rootfs: check-fw $(ROOTFS_OUT)/.config
	$(ROOTFS_MAKE)
	@mkdir -p $(IMAGES_DIR)
	cp $(ROOTFS_OUT)/images/rootfs.tar $(IMAGES_DIR)/

rootfs-configure: check-fw $(ROOTFS_OUT)/.config

rootfs-menuconfig: check-fw $(ROOTFS_OUT)/.config
	$(ROOTFS_MAKE) menuconfig

rootfs-savedefconfig: check-fw $(ROOTFS_OUT)/.config
	$(ROOTFS_MAKE) savedefconfig

# Relocatable cross toolchain + sysroot for application development
rootfs-sdk: check-fw $(ROOTFS_OUT)/.config
	$(ROOTFS_MAKE) sdk
	@mkdir -p $(IMAGES_DIR)
	cp $(ROOTFS_OUT)/images/*_sdk-buildroot.tar.gz $(IMAGES_DIR)/

# Run any Buildroot target: make rootfs-make BR=busybox-menuconfig
rootfs-make: check-fw $(ROOTFS_OUT)/.config
	$(ROOTFS_MAKE) $(BR)

rootfs-clean: check-fw
	rm -rf $(ROOTFS_OUT) $(IMAGES_DIR)/rootfs.tar

# ----------------------------------------------------------------------------
# SD card image

IMAGE_FILE := $(IMAGES_DIR)/$(IMAGE_NAME).img
IMAGE_DTB_LAYOUT ?= tree

.PHONY: image all flash flash-boot clean info help
image: check-fw
	KERNEL=$(LINUX_INSTALL)/$(LINUX_IMAGE) \
	LINUX_DIR=$(LINUX_INSTALL) \
	DTB_LAYOUT=$(IMAGE_DTB_LAYOUT) \
	RAW="$(call sdkpath-pairs,$(IMAGE_RAW),@)" \
	BOOT_FILES="$(call sdkpath-pairs,$(IMAGE_BOOT_FILES),:)" \
	ROOTFS_TAR=$(IMAGES_DIR)/rootfs.tar \
	CMDLINE="$(LINUX_CMDLINE)" \
	BOOT_SIZE_MB=$(IMAGE_BOOT_SIZE_MB) \
	ROOTFS_FREE_MB=$(IMAGE_ROOTFS_FREE_MB) \
	DISK_ID=$(IMAGE_DISK_ID) \
	WORK_DIR=$(OUT)/image-work \
	HOST_TOOLS=$(ROOTFS_OUT)/host/bin \
	$(SDK_DIR)/scripts/mkimage.sh $(IMAGE_FILE)

all: uboot linux rootfs $(BOOTFW_DEPS)
	$(MAKE) FW=$(FW) image

# make flash DEV=/dev/sdX
flash: check-fw
	$(SDK_DIR)/scripts/flash.sh $(IMAGE_FILE) $(DEV) 0

# Rewrite the bootloader and the BOOT partition (kernel, dtbs, extlinux),
# keeping the MBR and the rootfs: make flash-boot DEV=/dev/sdX.
# The card must hold an image of the same firmware config.
flash-boot: check-fw
	@test -f $(IMAGES_DIR)/boot-area.sector || { echo "Run 'make image' first"; exit 1; }
	$(SDK_DIR)/scripts/flash.sh $(IMAGES_DIR)/boot-area.bin $(DEV) $$(cat $(IMAGES_DIR)/boot-area.sector)

clean: check-fw
	rm -rf $(OUT)

gitdesc = [$$(git -C $(1) describe --always --dirty 2>/dev/null)]

info: check-fw
	@echo "Firmware:  $(FW) ($(FW_CONFIG))"
	@echo "Output:    $(OUT)"
	@echo "Compiler:  $(CROSS_COMPILE)gcc"
	@$(if $(TFA_PLAT),echo "TF-A:      $(TFA_SRC) $(call gitdesc,$(TFA_SRC)) PLAT=$(TFA_PLAT)",true)
	@echo "U-Boot:    $(UBOOT_SRC) $(call gitdesc,$(UBOOT_SRC)) $(UBOOT_DEFCONFIG) $(notdir $(UBOOT_FRAGMENTS))"
	@$(if $(UBOOT_BL31_FILE),echo "BL31:      $(UBOOT_BL31_FILE)",true)
	@$(if $(strip $(BOOTFW_FILES)),echo "Boot FW:   $(BOOTFW_NAME): $(BOOTFW_FILES)",true)
	@echo "Linux:     $(LINUX_SRC) $(call gitdesc,$(LINUX_SRC)) ARCH=$(LINUX_ARCH) $(LINUX_DEFCONFIG) $(notdir $(LINUX_FRAGMENTS))"
	@echo "Buildroot: $(BUILDROOT_SRC) $(call gitdesc,$(BUILDROOT_SRC)) $(BUILDROOT_DEFCONFIG)"
	@echo "Image:     $(IMAGE_FILE)"

help:
	@echo "Firmware config:"
	@echo "  <name>_defconfig       select configs/<name>_defconfig (or pass FW=<name>)"
	@echo "  info                   show selected config and component versions"
	@echo
	@echo "Components (each is built separately, out-of-tree):"
	@echo "  tfa                    BL31 from src/tf-a (boards with TFA_PLAT)"
	@echo "  uboot                  U-Boot (+ tfa if UBOOT_BL31=tf-a)"
	@echo "  bootfw                 fetch boot firmware blobs (boards with BOOTFW_FILES)"
	@echo "  linux                  kernel image, dtbs, modules"
	@echo "  rootfs                 Buildroot rootfs.tar"
	@echo "  rootfs-sdk             Buildroot cross toolchain + sysroot tarball"
	@echo "  rootfs-make BR=<tgt>   run a Buildroot target (e.g. BR=busybox-menuconfig)"
	@echo "  <comp>-configure / -menuconfig / -savedefconfig / -clean"
	@echo
	@echo "Image:"
	@echo "  image                  glue built components into images/<name>.img"
	@echo "  all (default)          all components + image"
	@echo "  flash DEV=/dev/sdX     write the image to an SD card"
	@echo "  flash-boot DEV=...     rewrite bootloader + BOOT partition, keep rootfs"
	@echo "  clean                  remove output/<fw>"
