# OdroidLinux SDK

SDK для ARM-плат на mainline-компонентах:

| Компонент | Каталог | Версия | Upstream |
|---|---|---|---|
| TF-A (BL31) | `src/tf-a` | v2.15.0 | github.com/ARM-software/arm-trusted-firmware |
| U-Boot | `src/u-boot` | v2026.07 | source.denx.de/u-boot/u-boot |
| Linux | `src/linux` | v7.2.9 | git.kernel.org stable |
| Buildroot | `src/buildroot` | 2026.08 | gitlab.com/buildroot.org/buildroot |

Каждый компонент — отдельный git-сабмодуль (локальная ветка `oga`), собирается
отдельно и out-of-tree в `output/<прошивка>/`, исходники не загрязняются.
Исходники общие для всех плат, различаются только конфиги.

## Платы

| Прошивка | Плата | SoC | Загрузка |
|---|---|---|---|
| `oga` | ODROID-GO Advance / Black Edition / Super | RK3326, A35, arm64 | idbloader + u-boot.itb (+ RK legacy для SPI) |
| `bbb` | BeagleBone Black / Green (+ Wireless) | AM335x, A8, armhf | ROM → MLO → u-boot.img с FAT |
| `rpi1` | Raspberry Pi 1 A/A+/B/B+, Zero, Zero W, CM1 | BCM2835, ARM1176, armhf | GPU firmware → U-Boot |
| `rpi4` | Raspberry Pi 4 B, Raspberry Pi 400, CM4 | BCM2711, A72, arm64 | EEPROM + GPU firmware → U-Boot |

Везде дальше одинаково: U-Boot сам выбирает dtb по модели платы и грузит
`extlinux/extlinux.conf` с раздела BOOT, ядро монтирует rootfs по
`root=PARTUUID=<disk id>-02`.

## Быстрый старт

```sh
sudo apt install mtools gcc-aarch64-linux-gnu gcc-arm-linux-gnueabihf
make rpi4_defconfig              # выбрать прошивку configs/rpi4_defconfig
make                             # все компоненты + образ
make flash DEV=/dev/sdX          # записать output/rpi4/images/rpi4.img на SD
```

Отдельные компоненты:

```sh
make uboot            # (TF-A +) U-Boot  -> images/
make bootfw           # блобы прошивки (RPi) -> images/
make linux            # ядро, dtbs, модули -> output/<fw>/linux-install/
make rootfs           # Buildroot        -> images/rootfs.tar
make image            # только склейка .img из уже собранного
make flash-boot DEV=/dev/sdX    # перезаписать загрузчик и раздел BOOT, rootfs не трогать
make FW=bbb linux     # собрать для другой прошивки, не меняя выбранную
make help             # все цели
```

Для каждого компонента есть `-menuconfig`, `-savedefconfig`, `-configure`, `-clean`
(`uboot-`, `linux-`, `rootfs-`). `make rootfs-make BR=busybox-menuconfig` вызывает
любую цель Buildroot, `make rootfs-sdk` собирает кросс-тулчейн с sysroot для приложений.

## Структура

```
configs/<fw>_defconfig        конфиг прошивки: компоненты, их конфиги, разметка образа
board/<board>/u-boot/*.config  фрагменты поверх in-tree defconfig U-Boot
board/<board>/linux/*.config   фрагменты поверх in-tree defconfig ядра
board/<board>/buildroot/defconfig   defconfig Buildroot для платы
board/<board>/boot/            файлы для раздела BOOT (config.txt у RPi)
board/common/buildroot/        общий BR2_EXTERNAL "SDK": свои пакеты, overlay, post-build
board/common/rpi-firmware.sha256    хеши блобов прошивки Raspberry Pi
board/oga/rkbin/               блобы и утилиты Rockchip (BL31, loaderimage, trust_merger)
scripts/mkimage.sh             склейка образа (без root: fakeroot + mke2fs -d + mtools)
scripts/fetch-files.sh         загрузка блобов с проверкой sha256
scripts/rk-legacy-pack.sh      упаковка uboot.img/trust.img для SPI miniloader (OGA)
scripts/flash.sh               запись на SD с проверками
src/                           сабмодули компонентов
dl/                            кэш загрузок (общий для всех прошивок)
```

## Конфиг прошивки

Пути — относительно корня SDK. `*_DEFCONFIG` — имя in-tree defconfig'а или путь к
своему файлу (если в значении есть `/`). `$(IMAGES_DIR)` и `$(LINUX_INSTALL)` указывают
на результаты сборки этой прошивки.

| Переменная | Что задаёт |
|---|---|
| `BOARD_DIR`, `CROSS_COMPILE` | каталог платы, кросс-компилятор для TF-A/U-Boot/ядра |
| `TFA_SRC`, `TFA_PLAT` | TF-A (необязательно) |
| `UBOOT_SRC`, `UBOOT_DEFCONFIG`, `UBOOT_FRAGMENTS` | U-Boot |
| `UBOOT_BL31` | `tf-a` или путь к bl31.elf (необязательно) |
| `UBOOT_IMAGES` | файлы из сборки U-Boot, копируемые в `images/` |
| `BOOTFW_NAME`, `BOOTFW_URL`, `BOOTFW_FILES`, `BOOTFW_HASH` | блобы прошивки (необязательно) |
| `LINUX_SRC`, `LINUX_ARCH`, `LINUX_IMAGE` | ядро: `arm`/`arm64`, `zImage`/`Image` |
| `LINUX_DEFCONFIG`, `LINUX_FRAGMENTS`, `LINUX_DTBS`, `LINUX_CMDLINE` | конфиг, dtb, командная строка |
| `BUILDROOT_SRC`, `BUILDROOT_EXTERNAL`, `BUILDROOT_DEFCONFIG` | rootfs |
| `IMAGE_RAW` | raw-блобы до 16M: `файл@сектор ...` |
| `IMAGE_BOOT_FILES` | файлы в корень BOOT: `путь[:имя] ...` |
| `IMAGE_DTB_LAYOUT` | dtb в BOOT: `tree` (`vendor/x.dtb`), `flat` (`x.dtb`) или `both` — как U-Boot строит `fdtfile` |
| `IMAGE_BOOT_SIZE_MB`, `IMAGE_ROOTFS_FREE_MB`, `IMAGE_DISK_ID` | размеры, идентификатор MBR |

`.config` компонента пересоздаётся, когда меняется defconfig-файл или фрагмент;
правки из `menuconfig` живут до этого момента, сохраняйте их через `*-savedefconfig`
или переносите во фрагмент.

## Разметка SD (общая)

```
сектор 0        MBR (disk id IMAGE_DISK_ID)
до 16M          raw-блобы загрузчика (IMAGE_RAW), если плате они нужны
16M             p1 FAT32 BOOT (активный): ядро, dtb, extlinux/extlinux.conf, IMAGE_BOOT_FILES
дальше          p2 ext4 rootfs: rootfs.tar + модули ядра; /boot монтируется по LABEL=BOOT
```

`make flash-boot` пишет `images/boot-area.bin`: от первого raw-блоба (или от 16M)
до конца раздела BOOT. MBR и rootfs не трогаются, поэтому на карте должен быть
образ той же прошивки.

Логин `root` без пароля, getty на последовательном порту и на экране (`tty1`).
На платах с Ethernet (BBB, RPi) поднимается DHCP на `eth0` и есть dropbear;
по SSH пустой пароль не пустит, задайте его через `passwd`.

## ODROID-GO Advance (`oga`)

```
16K..32K        окружение U-Boot (saveenv)
сектор 64       u-boot-rockchip.bin: idbloader (TPL с инициализацией DDR + SPL)
сектор 2048     u-boot.itb (U-Boot + BL31 TF-A + dtb), его грузит SPL
сектор 16384    uboot.img  (тот же U-Boot в формате Rockchip)   } для miniloader
сектор 24576    trust.img  (BL31 rkbin в формате Rockchip)       } из SPI-флеша
```

BootROM RK3326 проверяет SPI-флеш раньше SD. У OGA Black Edition во SPI с завода
стоит recovery-загрузчик Hardkernel (DDR-блоб + miniloader rkbin, лог на 1500000),
поэтому образ гибридный (`RK_LEGACY := y`):

- SPI с заводским загрузчиком: BootROM → SPI miniloader → `trust.img` (BL31 rkbin)
  → `uboot.img` (mainline U-Boot) → Linux;
- SPI пустой: BootROM → TPL → SPL → BL31 (mainline TF-A) → U-Boot → Linux,
  полностью открытая цепочка.

U-Boot определяет ревизию платы по SARADC (`rockchip/rk3326-odroid-go2.dtb`,
`-go2-v11.dtb`, `-go3.dtb`). Консоль `ttyS2`, 115200 начиная с U-Boot
(DDR-блоб и miniloader из SPI печатают на 1500000, CP2102 это не читает).
Таблица разделов — MBR: GPT (сектора 2–33) пересекается с окружением U-Boot на 16K.

## BeagleBone Black (`bbb`)

ROM AM335x грузит `MLO` (U-Boot SPL) с первого активного FAT-раздела, SPL — `u-boot.img`
оттуда же. U-Boot читает модель из EEPROM платы (`am335x-boneblack.dtb` и др.).
Консоль `ttyS0`, 115200 (разъём J1).

BBB грузится сначала с eMMC: чтобы загрузиться с SD, держите кнопку S2 (у слота SD)
при включении питания, либо сотрите загрузчик на eMMC.

## Raspberry Pi 1 (`rpi1`) и 4 / 400 (`rpi4`)

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

## Свои изменения в компонентах

```sh
cd src/linux
git checkout oga && git commit ...                    # работа в ветке oga
git remote add mine git@github.com:<you>/linux.git && git push mine oga
cd ../.. && git config -f .gitmodules submodule.src/linux.url git@github.com:<you>/linux.git
git add .gitmodules src/linux && git commit           # SDK пинует новый коммит
```
