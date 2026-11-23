include $(sort $(wildcard $(BR2_EXTERNAL_SDK_PATH)/package/*/*.mk))

# Realtek RTL8851BU Bluetooth (the TP-Link Archer TX10UB Nano...): not in
# Buildroot's Realtek 88xx list (rtl_bt/rtl88*). linux-firmware's recipe
# reads the list when it runs, after this.
ifeq ($(BR2_PACKAGE_LINUX_FIRMWARE_RTL_88XX_BT),y)
LINUX_FIRMWARE_FILES += rtl_bt/rtl8851bu_fw.bin
endif
