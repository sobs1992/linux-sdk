# esp8089

Wi-Fi driver for the Espressif ESP8089 on SDIO (ODROID-GO Advance Black
Edition). Mainline Linux has the device tree node (`esp,esp8089`) but no
driver, so it is built here as an external module by `make linux`
(`LINUX_EXT_MODULES` in configs/oga_defconfig).

Source: `008-esp-8089-wifi.patch` from ROCKNIX
(https://github.com/ROCKNIX/distribution,
projects/ROCKNIX/devices/RK3326/patches/linux), which carries the Espressif
v1.9 driver (via https://github.com/al177/esp8089) ported to Linux 7.x.
Only the driver files are taken; `Kbuild` is ours.

The chip firmware (`eagle_fw_*_v19.bin`) is installed into the rootfs by the
Buildroot package `esp8089-firmware`.
