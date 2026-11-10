################################################################################
#
# meson-venc-firmware
#
################################################################################

# firmware/h264_enc.bin of Amlogic's media_modules (amlogic-4.9.269 branch):
# a package ("PACK") of three microcodes, ga_h264_enc_cabac the first one.
# After the package header (256 bytes), the entry header (256) and the
# firmware header (512) come its 24576 bytes; the same ones as in
# video_ucode.bin of that branch.
MESON_VENC_FIRMWARE_VERSION = 60561618f2bf154c1438d3c790b625ff01f215c3
MESON_VENC_FIRMWARE_SITE = https://raw.githubusercontent.com/CoreELEC/media_modules-aml/$(MESON_VENC_FIRMWARE_VERSION)/firmware
MESON_VENC_FIRMWARE_SOURCE = h264_enc.bin
MESON_VENC_FIRMWARE_LICENSE = Amlogic proprietary (binary microcode)
MESON_VENC_FIRMWARE_UCODE = g12a_h264_enc_cabac.bin
MESON_VENC_FIRMWARE_UCODE_SHA256 = b3f1c3c8e3d26b1b1a549ce51627ad9313c7f57d96fa23fdbc6484d976d2deab

define MESON_VENC_FIRMWARE_EXTRACT_CMDS
	test "`dd if=$(MESON_VENC_FIRMWARE_DL_DIR)/$(MESON_VENC_FIRMWARE_SOURCE) bs=1 skip=256 count=21 status=none`" = ga_h264_enc_cabac.bin
	dd if=$(MESON_VENC_FIRMWARE_DL_DIR)/$(MESON_VENC_FIRMWARE_SOURCE) \
		of=$(@D)/$(MESON_VENC_FIRMWARE_UCODE) bs=1024 skip=1 count=24 status=none
	echo "$(MESON_VENC_FIRMWARE_UCODE_SHA256)  $(@D)/$(MESON_VENC_FIRMWARE_UCODE)" | sha256sum -c -
endef

define MESON_VENC_FIRMWARE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/$(MESON_VENC_FIRMWARE_UCODE) \
		$(TARGET_DIR)/lib/firmware/meson/venc/$(MESON_VENC_FIRMWARE_UCODE)
endef

$(eval $(generic-package))
