# Справочник переменных конфига прошивки

Пути — относительно корня SDK или абсолютные. В значениях можно использовать
`$(BOARD_DIR)`, `$(IMAGES_DIR)` (`output/<fw>/images`) и `$(LINUX_INSTALL)`
(`output/<fw>/linux-install`).

## Общие

| Переменная | Обязательна | Значение |
|---|---|---|
| `BOARD_DIR` | да | каталог платы, например `board/oga` |
| `CROSS_COMPILE` | да | префикс тулчейна для TF-A, U-Boot, ядра |

## TF-A

| Переменная | Обязательна | Значение |
|---|---|---|
| `TFA_SRC` | если нужен TF-A | `src/tf-a` |
| `TFA_PLAT` | если нужен TF-A | платформа TF-A, например `px30` |
| `TFA_MAKE_ARGS` | нет | доп. аргументы make TF-A |

## U-Boot

| Переменная | Обязательна | Значение |
|---|---|---|
| `UBOOT_SRC` | да | `src/u-boot` |
| `UBOOT_DEFCONFIG` | да | имя in-tree defconfig или путь к файлу |
| `UBOOT_FRAGMENTS` | нет | список фрагментов |
| `UBOOT_BL31` | нет | `tf-a` или путь к `bl31.elf` |
| `UBOOT_IMAGES` | да | файлы из каталога сборки → `images/` |
| `UBOOT_MAKE_ARGS` | нет | доп. аргументы make U-Boot |

## Rockchip legacy (OGA)

| Переменная | Значение |
|---|---|
| `RK_LEGACY` | `y` — собрать `uboot.img` и `trust.img` для SPI miniloader |
| `RKBIN_DIR` | каталог с `tools/loaderimage`, `tools/trust_merger` |
| `RK_TRUST_BL31` | BL31 для `trust.img` |

## Блобы прошивки

| Переменная | Значение |
|---|---|
| `BOOTFW_NAME` | имя каталога в кэше `dl/` |
| `BOOTFW_URL` | базовый URL, к нему дописывается имя файла |
| `BOOTFW_FILES` | список файлов |
| `BOOTFW_HASH` | файл в формате `sha256sum` |

## Linux

| Переменная | Обязательна | Значение |
|---|---|---|
| `LINUX_SRC` | да | `src/linux` |
| `LINUX_ARCH` | нет (`arm64`) | `arm` или `arm64` |
| `LINUX_IMAGE` | нет (`Image`) | `Image` или `zImage` |
| `LINUX_DEFCONFIG` | да | имя in-tree defconfig или путь |
| `LINUX_FRAGMENTS` | нет | список фрагментов |
| `LINUX_DTBS` | да | dtb относительно `arch/<arch>/boot/dts/` |
| `LINUX_EXT_MODULES` | нет | каталоги внешних модулей (с `Kbuild`); собираются и ставятся в `updates/` вместе с ядром |
| `LINUX_CMDLINE` | да | командная строка; `root=PARTUUID=…` добавляется автоматически |
| `LINUX_MAKE_ARGS` | нет | доп. аргументы make ядра |

## Buildroot

| Переменная | Обязательна | Значение |
|---|---|---|
| `BUILDROOT_SRC` | да | `src/buildroot` |
| `BUILDROOT_EXTERNAL` | да | `board/common/buildroot` |
| `BUILDROOT_DEFCONFIG` | да | путь к defconfig платы |
| `BUILDROOT_MAKE_ARGS` | нет | доп. аргументы make Buildroot |

## Образ

| Переменная | Обязательна | Значение |
|---|---|---|
| `IMAGE_NAME` | да | имя файла `images/<name>.img` |
| `IMAGE_RAW` | нет | `файл@сектор …`, всё должно кончаться до 16 МиБ |
| `IMAGE_BOOT_FILES` | нет | `путь[:имя] …` — в корень раздела BOOT |
| `IMAGE_DTB_LAYOUT` | нет (`tree`) | `tree`, `flat`, `both` |
| `IMAGE_BOOT_SIZE_MB` | да | размер раздела BOOT |
| `IMAGE_ROOTFS_FREE_MB` | да | свободное место в rootfs сверх содержимого |
| `IMAGE_DISK_ID` | да | идентификатор MBR, `0x` + 8 hex-цифр |

## Переменные командной строки

| Переменная | Значение |
|---|---|
| `FW` | прошивка для одной команды |
| `JOBS` | потоков для TF-A, U-Boot, ядра (по умолчанию `nproc`) |
| `DEV` | устройство для `flash`, `flash-boot` |
| `BR` | цель Buildroot для `rootfs-make` |
| `OUTPUT_DIR`, `DL_DIR` | каталоги результатов и кэша |
