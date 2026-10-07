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

OUT := $(OUTPUT_DIR)/$(FW)
IMAGES_DIR := $(OUT)/images

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

# ----------------------------------------------------------------------------
# Trusted Firmware-A

TFA_OUT  := $(OUT)/tf-a
TFA_BL31 := $(TFA_OUT)/$(TFA_PLAT)/release/bl31/bl31.elf
TFA_MAKE  = $(MAKE) -C $(TFA_SRC) BUILD_BASE=$(TFA_OUT) PLAT=$(TFA_PLAT) \
            CROSS_COMPILE=$(CROSS_COMPILE) $(TFA_MAKE_ARGS)

.PHONY: tfa tfa-clean
tfa: check-fw
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
else
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
uboot: check-fw $(UBOOT_DEPS) $(UBOOT_OUT)/.config
	$(UBOOT_MAKE) -j$(JOBS) BL31=$(UBOOT_BL31_FILE)
	@mkdir -p $(IMAGES_DIR)
	cp $(UBOOT_OUT)/$(UBOOT_IMAGE) $(IMAGES_DIR)/
ifeq ($(RK_LEGACY),y)
	$(SDK_DIR)/scripts/rk-legacy-pack.sh $(RKBIN_DIR) $(UBOOT_OUT) $(RK_TRUST_BL31) $(IMAGES_DIR)
endif

uboot-configure: check-fw $(UBOOT_OUT)/.config

uboot-menuconfig: check-fw $(UBOOT_OUT)/.config
	$(UBOOT_MAKE) menuconfig

uboot-savedefconfig: check-fw $(UBOOT_OUT)/.config
	$(call kconfig-savedefconfig,$(UBOOT_MAKE),$(UBOOT_OUT),$(UBOOT_DEFCONFIG))

uboot-clean: check-fw
	rm -rf $(UBOOT_OUT) $(IMAGES_DIR)/$(UBOOT_IMAGE) $(RK_LEGACY_IMAGES)

# ----------------------------------------------------------------------------
# Linux

LINUX_OUT     := $(OUT)/linux
LINUX_INSTALL := $(OUT)/linux-install
LINUX_MAKE     = $(MAKE) -C $(LINUX_SRC) O=$(LINUX_OUT) ARCH=arm64 CROSS_COMPILE=$(CROSS_COMPILE) $(LINUX_MAKE_ARGS)

ifneq ($(FW),)
$(call inputs-stamp,$(LINUX_OUT),$(LINUX_DEFCONFIG) $(LINUX_FRAGMENTS))
endif

$(LINUX_OUT)/.config: $(LINUX_OUT)/.sdk-inputs $(filter /%,$(LINUX_DEFCONFIG)) $(LINUX_FRAGMENTS)
	$(call kconfig-configure,$(LINUX_MAKE),$(LINUX_OUT),$(LINUX_DEFCONFIG),$(LINUX_FRAGMENTS),$(LINUX_SRC))

.PHONY: linux linux-configure linux-menuconfig linux-savedefconfig linux-clean
linux: check-fw $(LINUX_OUT)/.config
	$(LINUX_MAKE) -j$(JOBS) Image modules $(LINUX_DTBS)
	rm -rf $(LINUX_INSTALL)
	mkdir -p $(LINUX_INSTALL)/modules
	cp $(LINUX_OUT)/arch/arm64/boot/Image $(LINUX_OUT)/System.map $(LINUX_OUT)/.config $(LINUX_INSTALL)/
	$(foreach d,$(LINUX_DTBS),install -D -m 644 $(LINUX_OUT)/arch/arm64/boot/dts/$(d) $(LINUX_INSTALL)/dtbs/$(d) &&) true
	$(LINUX_MAKE) INSTALL_MOD_PATH=$(LINUX_INSTALL)/modules INSTALL_MOD_STRIP=1 modules_install

linux-configure: check-fw $(LINUX_OUT)/.config

linux-menuconfig: check-fw $(LINUX_OUT)/.config
	$(LINUX_MAKE) menuconfig

linux-savedefconfig: check-fw $(LINUX_OUT)/.config
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

.PHONY: rootfs rootfs-configure rootfs-menuconfig rootfs-savedefconfig rootfs-sdk rootfs-clean
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

.PHONY: image all flash flash-uboot clean info help check-fw
image: check-fw
	UBOOT_BIN=$(IMAGES_DIR)/$(UBOOT_IMAGE) \
	UBOOT_SECTOR=$(IMAGE_UBOOT_SECTOR) \
	LINUX_DIR=$(LINUX_INSTALL) \
	ROOTFS_TAR=$(IMAGES_DIR)/rootfs.tar \
	CMDLINE="$(LINUX_CMDLINE)" \
	BOOT_SIZE_MB=$(IMAGE_BOOT_SIZE_MB) \
	ROOTFS_FREE_MB=$(IMAGE_ROOTFS_FREE_MB) \
	DISK_ID=$(IMAGE_DISK_ID) \
	WORK_DIR=$(OUT)/image-work \
	RK_UBOOT_IMG=$(filter %/uboot.img,$(RK_LEGACY_IMAGES)) \
	RK_TRUST_IMG=$(filter %/trust.img,$(RK_LEGACY_IMAGES)) \
	HOST_TOOLS=$(ROOTFS_OUT)/host/bin \
	$(SDK_DIR)/scripts/mkimage.sh $(IMAGE_FILE)

all: uboot linux rootfs
	$(MAKE) FW=$(FW) image

# make flash DEV=/dev/sdX
flash: check-fw
	$(SDK_DIR)/scripts/flash.sh $(IMAGE_FILE) $(DEV) 0

# Write only the bootloader area (sector 64 up to the first partition),
# keeping the partitions: make flash-uboot DEV=/dev/sdX. Run "make image" first.
flash-uboot: check-fw
	$(SDK_DIR)/scripts/flash.sh $(IMAGES_DIR)/bootloader.bin $(DEV) $(IMAGE_UBOOT_SECTOR)

clean: check-fw
	rm -rf $(OUT)

check-fw:
	@test -n "$(FW)" || { echo "No firmware config selected: run 'make <name>_defconfig'."; \
		echo "Available:"; ls $(SDK_DIR)/configs | sed -n 's/_defconfig$$//p' | sed 's/^/  /'; exit 1; }

info: check-fw
	@echo "Firmware:  $(FW) ($(FW_CONFIG))"
	@echo "Output:    $(OUT)"
	@echo "TF-A:      $(TFA_SRC) [$$(git -C $(TFA_SRC) describe --always --dirty 2>/dev/null)] PLAT=$(TFA_PLAT)"
	@echo "U-Boot:    $(UBOOT_SRC) [$$(git -C $(UBOOT_SRC) describe --always --dirty 2>/dev/null)] $(UBOOT_DEFCONFIG) $(notdir $(UBOOT_FRAGMENTS))"
	@echo "BL31:      $(UBOOT_BL31_FILE)"
	@echo "Linux:     $(LINUX_SRC) [$$(git -C $(LINUX_SRC) describe --always --dirty 2>/dev/null)] $(LINUX_DEFCONFIG) $(notdir $(LINUX_FRAGMENTS))"
	@echo "Buildroot: $(BUILDROOT_SRC) [$$(git -C $(BUILDROOT_SRC) describe --always --dirty 2>/dev/null)] $(BUILDROOT_DEFCONFIG)"
	@echo "Image:     $(IMAGE_FILE)"

help:
	@echo "Firmware config:"
	@echo "  <name>_defconfig       select configs/<name>_defconfig (or pass FW=<name>)"
	@echo "  info                   show selected config and component versions"
	@echo
	@echo "Components (each is built separately, out-of-tree):"
	@echo "  tfa                    BL31 from src/tf-a"
	@echo "  uboot                  U-Boot (+ tfa if UBOOT_BL31=tf-a)"
	@echo "  linux                  kernel Image, dtbs, modules"
	@echo "  rootfs                 Buildroot rootfs.tar"
	@echo "  rootfs-sdk             Buildroot cross toolchain + sysroot tarball"
	@echo "  rootfs-make BR=<tgt>   run a Buildroot target (e.g. BR=busybox-menuconfig)"
	@echo "  <comp>-configure / -menuconfig / -savedefconfig / -clean"
	@echo
	@echo "Image:"
	@echo "  image                  glue built components into images/<name>.img"
	@echo "  all (default)          uboot linux rootfs image"
	@echo "  flash DEV=/dev/sdX     write the image to an SD card"
	@echo "  flash-uboot DEV=...    write only the bootloader"
	@echo "  clean                  remove output/<fw>"
