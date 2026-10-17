################################################################################
#
# esp8089-firmware
#
################################################################################

# Single files from armbian/firmware (the whole repository is huge)
ESP8089_FIRMWARE_VERSION = 490722a3c9181d6fee6ad75682aaba4afd9d4b24
ESP8089_FIRMWARE_SITE = https://raw.githubusercontent.com/armbian/firmware/$(ESP8089_FIRMWARE_VERSION)
ESP8089_FIRMWARE_FILES = eagle_fw_ate_config_v19.bin eagle_fw_first_init_v19.bin \
	eagle_fw_second_init_v19.bin
ESP8089_FIRMWARE_SOURCE = $(firstword $(ESP8089_FIRMWARE_FILES))
ESP8089_FIRMWARE_EXTRA_DOWNLOADS = $(wordlist 2,$(words $(ESP8089_FIRMWARE_FILES)),$(ESP8089_FIRMWARE_FILES))
ESP8089_FIRMWARE_LICENSE = Apache-2.0

define ESP8089_FIRMWARE_EXTRACT_CMDS
	$(foreach f,$(ESP8089_FIRMWARE_FILES),cp $(ESP8089_FIRMWARE_DL_DIR)/$(f) $(@D)/ &&) true
endef

define ESP8089_FIRMWARE_INSTALL_TARGET_CMDS
	$(foreach f,$(ESP8089_FIRMWARE_FILES),\
		$(INSTALL) -D -m 0644 $(@D)/$(f) $(TARGET_DIR)/lib/firmware/$(f) &&) true
endef

$(eval $(generic-package))
