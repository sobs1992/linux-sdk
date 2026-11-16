# Конфиг прошивки

Пути — относительно корня SDK. `*_DEFCONFIG` — имя in-tree defconfig'а или путь к
своему файлу (если в значении есть `/`). `$(IMAGES_DIR)` и `$(LINUX_INSTALL)` указывают
на результаты сборки этой прошивки.

| Переменная | Что задаёт |
|---|---|
| `BOARD_DIR`, `CROSS_COMPILE` | каталог платы (по умолчанию `board/<fw>`), кросс-компилятор для TF-A/U-Boot/ядра |
| `TFA_SRC`, `TFA_PLAT`, `TFA_MAKE_ARGS` | TF-A: исходники (`src/tf-a`), платформа — только у плат с TF-A |
| `UBOOT_SRC`, `UBOOT_DEFCONFIG`, `UBOOT_FRAGMENTS`, `UBOOT_MAKE_ARGS` | U-Boot: исходники (`src/u-boot`), defconfig, фрагменты |
| `UBOOT_PATCHES` | каталог патчей U-Boot `*.patch` (необязательно): как `LINUX_PATCHES`, копия в `output/<прошивка>/u-boot-src` |
| `UBOOT_BL31` | `tf-a` или путь к bl31.elf (необязательно) |
| `UBOOT_IMAGES` | файлы из сборки U-Boot, копируемые в `images/` |
| `RK_LEGACY`, `RKBIN_DIR`, `RK_TRUST_BL31` | Rockchip: `uboot.img`/`trust.img` для SPI miniloader (OGA) |
| `AML_FIP_NAME`, `AML_FIP_URL`, `AML_FIP_FILES`, `AML_FIP_HASH` | Amlogic: блобы BL2/BL30/BL31 для FIP (GO Ultra), скачиваются и проверяются |
| `BOOTFW_NAME`, `BOOTFW_URL`, `BOOTFW_FILES`, `BOOTFW_HASH` | блобы прошивки, копируемые на BOOT (Raspberry Pi) |
| `LINUX_SRC`, `LINUX_ARCH`, `LINUX_IMAGE`, `LINUX_MAKE_ARGS` | ядро: исходники (`src/linux`), `arm`/`arm64` (`arm64`), `zImage`/`Image` (`Image`) |
| `LINUX_DEFCONFIG`, `LINUX_FRAGMENTS`, `LINUX_DTBS`, `LINUX_CMDLINE` | конфиг, dtb, командная строка |
| `LINUX_PATCHES` | каталог патчей ядра `*.patch` (необязательно): ядро собирается из копии закоммиченного `LINUX_SRC` с патчами в `output/<прошивка>/linux-src`, сам подмодуль не меняется |
| `LINUX_EXT_MODULES` | внешние модули (каталоги с `Kbuild`), собираются и ставятся вместе с ядром |
| `BUILDROOT_SRC`, `BUILDROOT_EXTERNAL`, `BUILDROOT_DEFCONFIG`, `BUILDROOT_MAKE_ARGS` | rootfs: `src/buildroot`, `board/common/buildroot`, `$(BOARD_DIR)/buildroot/defconfig` |
| `APPS` | приложения (пакеты из `apps/`) в rootfs; список — `make apps-list` |
| `APPS_AUTOSTART` | какие из `APPS` запускать при загрузке (init-скрипт `S<порядок><пакет>`, у bare_app порядок — опция `INIT_ORDER`, по умолчанию 90) |
| `APPS_CONFIG` | опции приложений: `пакет.ОПЦИЯ=значение`, например `bare-app.DEFCONFIG=oga_defconfig` |
| `IMAGE_NAME` | имя образа `images/<имя>.img` (по умолчанию `<fw>`) |
| `IMAGE_RAW` | raw-блобы до 16M: `файл@сектор ...` |
| `IMAGE_MBR_CODE` | файл с 440 байтами загрузочного кода сектора 0 (GO Ultra) |
| `IMAGE_BOOT_FILES` | файлы в корень BOOT: `путь[:имя] ...` |
| `IMAGE_DTB_LAYOUT` | dtb в BOOT: `tree` (`vendor/x.dtb`, по умолчанию), `flat` (`x.dtb`) или `both` — как U-Boot строит `fdtfile` |
| `IMAGE_BOOT_SIZE_MB`, `IMAGE_ROOTFS_FREE_MB`, `IMAGE_DISK_ID` | размеры (свободного места в rootfs по умолчанию 256), идентификатор MBR |
| `IMAGE_DATA_START_MB` | начало раздела данных `/data` (необязательно, см. [sd-layout.md](sd-layout.md)) |
| `IMAGE_DATA_SIZE_MB` | размер `/data`; если задан, после него раздел игр `/games` до конца карты |
| `IMAGE_EMMC_DISK_ID`, `EMMC_UMS_USB_ID` | второй образ той же разметки для eMMC (`images/<имя>-emmc.img`) и USB-id, под которым U-Boot показывает eMMC компьютеру (`make flash-emmc`) |

Значения в скобках — умолчания Makefile: конфиг платы задаёт только то, что
отличается (см. шапку `configs/oga_defconfig`).

Приложения из `apps/` включаются только через `APPS`. SDK накладывает их на defconfig
Buildroot платы (`output/<fw>/buildroot/defconfig.sdk`), а `rootfs-savedefconfig`
обратно в defconfig платы их не пишет. Если приложение убрали или поменяли его
автозапуск или опции, SDK удаляет его файлы из `target/` и пересобирает пакет; то же
с любым пакетом, который после перенастройки ушёл из `.config` (выключенная опция
`bare-app.WINE=y` убирает Wine). Сам Buildroot этого не делает, и выключенный
автозапуск или движок остался бы в образе инкрементальной сборки. Файл берётся
только у пакета, который один его ставил (`packages-file-list.txt` Buildroot).

`.config` компонента пересоздаётся, когда меняется defconfig-файл или фрагмент;
правки из `menuconfig` живут до этого момента, сохраняйте их через `*-savedefconfig`
или переносите во фрагмент.
