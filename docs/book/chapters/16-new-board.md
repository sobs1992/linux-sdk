# Своя плата: пошаговый план и упражнения

Эта глава — рабочий план. Пройдите его для любой новой платы: Orange Pi, Rock Pi,
Pine64, своей разработки на известном SoC.

## Шаг 1. Собрать факты

Ответьте на вопросы, **по возможности из исходников**, а не из форумов.

| Вопрос | Где искать |
|---|---|
| Есть ли плата в mainline U-Boot? | `ls src/u-boot/configs | grep -i <плата>`, `doc/board/<vendor>/` |
| Как BootROM находит загрузчик и в каком порядке носителей? | документация SoC, `doc/board/<vendor>/*.rst` в U-Boot |
| Нужен ли TF-A / BL31? | `ls src/tf-a/plat/<vendor>/`, `CONFIG_SPL_ATF` в defconfig U-Boot |
| Какие файлы выдаёт сборка U-Boot? | `ls output/<fw>/u-boot/` после первой сборки, `binman` в `*-u-boot.dtsi` |
| Куда писать загрузчик (сектора или файлы на FAT)? | `CONFIG_SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR`, `SPL_FS_*`, документация |
| Как U-Boot строит `fdtfile`? | `grep -rn fdtfile board/<vendor>/ include/configs/<плата>.h` |
| Где DTS в ядре? | `ls src/linux/arch/arm*/boot/dts/<vendor>/ | grep <плата>` |
| Какая консоль и скорость? | `stdout-path` в DTS, `CONFIG_BAUDRATE` в U-Boot |
| Какой defconfig ядра взять? | `ls arch/arm*/configs/`, проверить `CONFIG_ARCH_<SOC>=y` |
| Что-то уже стоит во флеше / eMMC? | осмотреть плату, вендорские скрипты, тест «без SD» |
| Есть ли закрытые блобы (DDR, прошивка GPU)? | документация, `binman` (`rockchip-tpl`, `ddr-*`) |

## Шаг 2. Создать файлы платы

```text
configs/<fw>_defconfig
board/<плата>/linux/<плата>.config       # хотя бы LOCALVERSION
board/<плата>/u-boot/<плата>.config      # при необходимости
board/<плата>/buildroot/defconfig        # скопируйте ближайший и поменяйте CPU и getty
board/<плата>/boot/...                   # если загрузчику нужны файлы (config.txt и т. п.)
```

Шаблон конфига прошивки:

```make
BOARD_DIR     := board/myboard
CROSS_COMPILE := aarch64-linux-gnu-

# TFA_SRC  := src/tf-a          # если нужен BL31
# TFA_PLAT := <plat>

UBOOT_SRC       := src/u-boot
UBOOT_DEFCONFIG := myboard_defconfig
UBOOT_IMAGES    := u-boot-xxx.bin
# UBOOT_BL31    := tf-a

LINUX_SRC       := src/linux
LINUX_ARCH      := arm64
LINUX_IMAGE     := Image
LINUX_DEFCONFIG := defconfig
LINUX_FRAGMENTS := $(BOARD_DIR)/linux/myboard.config
LINUX_DTBS      := vendor/myboard.dtb
LINUX_CMDLINE   := rootwait rw console=tty1 console=ttyS0,115200n8

BUILDROOT_SRC       := src/buildroot
BUILDROOT_EXTERNAL  := board/common/buildroot
BUILDROOT_DEFCONFIG := $(BOARD_DIR)/buildroot/defconfig

IMAGE_NAME           := myboard
IMAGE_RAW            := $(IMAGES_DIR)/u-boot-xxx.bin@<сектор>
IMAGE_BOOT_FILES     :=
IMAGE_DTB_LAYOUT     := tree
IMAGE_BOOT_SIZE_MB   := 128
IMAGE_ROOTFS_FREE_MB := 256
IMAGE_DISK_ID        := 0x<8 hex>
```

## Шаг 3. Собирать по частям и проверять каждую

```bash
make myboard_defconfig
make info                      # пути и версии верные?
make uboot                     # нет ли предупреждений binman о missing blobs?
make linux                     # нет ли WARNING от kconfig-check?
make rootfs                    # долго: тулчейн
make image                     # не перекрываются ли блобы?
```

После каждой команды — проверки из глав 7, 8 и 10: `dumpimage`, `grep` по
`.config`, `mdir`, `debugfs`, `cmp` по секторам.

## Шаг 4. Первый запуск

1. UART подключён, скорость верная, захват в файл запущен **до** включения.
2. Записали образ (`make flash`), вставили, включили.
3. Смотрим, до какой стадии дошли: ничего / мусор / SPL / U-Boot / ядро / init.
4. Если ничего или мусор — методика главы 11.

| Где остановилось | Что проверить |
|---|---|
| Тишина | скорость UART, правильные ли TX/RX, тест «без SD», не грузится ли что-то из флеша/eMMC |
| Мусор | скорость; кто печатает (наш код или чужой загрузчик) |
| SPL, но не U-Boot | сектор FIT (`SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR`), есть ли BL31 в FIT |
| U-Boot, но не ядро | `fdtfile` и раскладка dtb, `bootflow scan -l`, есть ли `bootz` для zImage |
| Ядро, но паника на root | `root=PARTUUID`, драйвер SD встроен (`=y`)?, `rootwait` |
| init, но нет консоли | getty на правильном порту, `console=` последним указан UART |

!!! tip "Полезные команды в консоли U-Boot"
    `bootflow scan -l` — что U-Boot нашёл для загрузки; `printenv fdtfile` — какой dtb
    он выберет; `mmc list`, `ls mmc 0:1 /` — видит ли он карту и файлы;
    `bdinfo` — память; `dm tree` — устройства.

## Упражнения

!!! example "1. Минимальное ядро для OGA"
    Глава 8: `localmodconfig`, свой defconfig-файл, сравнение размеров.

!!! example "2. Цель image-xz"
    Глава 6: сжатие образа отдельной целью без лишней работы.

!!! example "3. Свой пакет Buildroot"
    Глава 9: `hello` как `generic-package` в общем external-дереве.

!!! example "4. USB-гаджет Ethernet на OGA"
    У OGA есть USB OTG (DWC2). Включите в ядре `CONFIG_USB_CONFIGFS_ECM` (или `g_ether`),
    добавьте в overlay скрипт `/etc/init.d/S40usbnet`, который настраивает гаджет и
    адрес `192.168.7.2`, и включите dropbear. Цель — `ssh root@192.168.7.2` по кабелю USB.

!!! example "5. Запуск BBB или Raspberry Pi на железе"
    Пройдите шаг 4 этой главы для одной из новых плат. Запишите, на какой стадии
    что увидели, и что пришлось исправить.

!!! example "6. Перейти на свежий U-Boot"
    Глава 15: rebase ветки `oga` на новый релиз, проверка `SPL_PAD_TO` и
    `SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR`, проверка на OGA.

!!! example "7. Внешний тулчейн"
    Сделайте копию конфига прошивки `rpi4` с Buildroot-тулчейном Bootlin
    (`BR2_TOOLCHAIN_EXTERNAL=y`, `BR2_TOOLCHAIN_EXTERNAL_BOOTLIN=y`,
    `BR2_TOOLCHAIN_EXTERNAL_BOOTLIN_AARCH64_GLIBC_STABLE=y`). Сравните время сборки
    и размер `output/<fw>/buildroot`.

!!! example "8. Без SPI-загрузчика"
    (Только если готовы к риску и есть бэкап.) Сохраните SPI OGA, сотрите заголовок
    (глава 11) и проверьте, что тот же образ грузится по полностью открытой цепочке:
    в логе должен появиться `out` от TPL и `U-Boot SPL 2026.07`.
