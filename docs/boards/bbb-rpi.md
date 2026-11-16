# BeagleBone Black и Raspberry Pi

# BeagleBone Black (`bbb`)

ROM AM335x грузит `MLO` (U-Boot SPL) с первого активного FAT-раздела, SPL — `u-boot.img`
оттуда же. U-Boot читает модель из EEPROM платы (`am335x-boneblack.dtb` и др.).
Консоль `ttyS0`, 115200 (разъём J1).

BBB грузится сначала с eMMC: чтобы загрузиться с SD, держите кнопку S2 (у слота SD)
при включении питания, либо сотрите загрузчик на eMMC.

# Raspberry Pi 1 (`rpi1`) и 4 / 400 (`rpi4`)

Raspberry Pi не читает raw-сектора: закрытая прошивка GPU (`bootcode.bin`/`start.elf`
у Pi 1, EEPROM + `start4.elf` у Pi 4/400) читает `config.txt` с раздела BOOT и
запускает mainline U-Boot (`kernel=u-boot.bin`). Блобы скачиваются с
github.com/raspberrypi/firmware (тег из `BOOTFW_URL`) и проверяются по
`board/common/rpi-firmware.sha256`.

U-Boot на Pi обязательно нужен device tree от прошивки. Прошивка ищет dtb по своим
именам: у Pi 4/400 они совпадают с mainline (`bcm2711-rpi-400.dtb`, поэтому dtb лежат
и в корне BOOT), у Pi 1 — нет (`bcm2708-rpi-*.dtb`), поэтому mainline dtb скопированы
и под этими именами. Ядру U-Boot отдаёт mainline dtb по модели платы.

Консоль: Pi 1 — `ttyAMA0`, Pi 4/400 — mini-UART `ttyS1` (GPIO14/15), 115200;
у Pi 400 основная консоль — HDMI + встроенная клавиатура.
