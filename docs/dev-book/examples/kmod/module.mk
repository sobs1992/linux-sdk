# Shared wrapper for out-of-tree modules, built against a kernel built by the SDK.
#
#   make                   for the firmware selected in the SDK (output/.fw)
#   make FW=bbb            for another firmware
#   make install           into output/<fw>/linux-install/modules (goes into the image)
#   make SDK=/path/to/sdk  if this directory is not inside the SDK
#
# The module source list lives in the Kbuild file next to the Makefile.

SDK  ?= $(abspath $(CURDIR)/../../../../..)
FW   ?= $(shell cat $(SDK)/output/.fw 2>/dev/null)
KDIR ?= $(SDK)/output/$(FW)/linux

ifeq ($(wildcard $(KDIR)/.config),)
$(error Kernel for '$(FW)' not found in $(KDIR): run "make FW=$(FW) linux" in the SDK)
endif

# Architecture and compiler follow the kernel configuration
ifneq ($(shell grep -x 'CONFIG_ARM64=y' $(KDIR)/.config),)
ARCH          ?= arm64
CROSS_COMPILE ?= aarch64-linux-gnu-
else
ARCH          ?= arm
CROSS_COMPILE ?= arm-linux-gnueabihf-
endif

KMAKE = $(MAKE) -C $(KDIR) M=$(CURDIR) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE)

all:
	$(KMAKE) modules

install: all
	$(KMAKE) INSTALL_MOD_PATH=$(SDK)/output/$(FW)/linux-install/modules INSTALL_MOD_STRIP=1 modules_install

clean:
	$(KMAKE) clean

.PHONY: all install clean
