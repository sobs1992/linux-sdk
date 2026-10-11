# Несколько плат: BeagleBone Black и Raspberry Pi

SDK, сделанный под одну плату, почти всегда содержит «зашитые» допущения. Перед
добавлением новых плат полезно честно их перечислить.

## Что было зашито под OGA

| Место | Было | Стало |
|---|---|---|
| Makefile | `ARCH=arm64`, `arch/arm64/boot/Image` | `LINUX_ARCH`, `LINUX_IMAGE` в конфиге |
| Makefile | `CROSS_COMPILE ?= aarch64-linux-gnu-` | `CROSS_COMPILE` в конфиге + проверка `check-cc` |
| TF-A | цель всегда, BL31 всегда передаётся | только при `TFA_PLAT`/`UBOOT_BL31` |
| U-Boot | один `UBOOT_IMAGE` | список `UBOOT_IMAGES` (BBB: `MLO u-boot.img`) |
| mkimage.sh | обязательный загрузчик с сектора 64, отдельный код для RK legacy | общий список `IMAGE_RAW` (`файл@сектор`) |
| mkimage.sh | dtb всегда с каталогом | `IMAGE_DTB_LAYOUT`: `tree`, `flat`, `both` |
| mkimage.sh | — | `IMAGE_BOOT_FILES` (`путь[:имя]`) для файлов в BOOT |
| Buildroot | external дерево OGA | общее `board/common/buildroot` |
| fstab | `/dev/mmcblk0p1 /boot` в post-build | `LABEL=BOOT` из `mkimage.sh` |
| Блобы | — | компонент `bootfw` (URL + sha256) |

### Регрессионная проверка

После такого рефакторинга нужно доказать, что OGA не сломалась. Самый строгий
способ — сравнить загрузочную область нового образа с той, что **уже загрузилась
на железе**:

```bash
cp output/oga/images/bootloader.bin /tmp/old-boot-area.bin   # сохранено до рефакторинга
make FW=oga image
dd if=output/oga/images/oga.img bs=512 skip=64 count=$((32768-64)) status=none \
  | cmp - /tmp/old-boot-area.bin && echo "boot area identical"
```

Результат — побайтовое совпадение. Изменился только rootfs (fstab и busybox), и это
изменение осознанное.

## BeagleBone Black

### Как он грузится

ROM AM335x перебирает носители в порядке, который задают выводы SYSBOOT. У BBB по
умолчанию **eMMC раньше SD**. Кнопка S2 (у слота SD) при включении меняет порядок:
SD первой.

ROM ищет на карте **активный FAT-раздел** и файл `MLO` в его корне — это U-Boot SPL
с заголовком TI. SPL инициализирует DDR и загружает с того же раздела `u-boot.img`.
Есть и «сырой» режим (MLO по смещению 128 КиБ), но файловый проще и отлично ложится
в нашу разметку.

Проверка в собранном U-Boot:

```text
CONFIG_SPL_FS_FAT=y
CONFIG_SYS_MMCSD_FS_BOOT=y
CONFIG_SPL_FS_LOAD_PAYLOAD_NAME="u-boot.img"
CONFIG_CMD_BOOTZ=y                 ← нужен для zImage
```

### Выбор dtb

U-Boot читает EEPROM платы и в скрипте `findfdt` (`include/configs/am335x_evm.h`)
ставит `fdtfile=am335x-boneblack.dtb` — **без каталога**. Поэтому
`IMAGE_DTB_LAYOUT := flat`.

### Конфиг

{{include configs/bbb_defconfig make}}

Ядро — `omap2plus_defconfig` (в нём уже есть всё для AM335x: CPSW Ethernet, MMC,
HDMI через tilcdc + tda998x модулями), фрагмент добавляет только `LOCALVERSION`.
Консоль — `ttyS0` (разъём J1).

## Raspberry Pi: другая модель загрузки

У Raspberry Pi загрузку начинает **GPU**, а не ARM:

| | Pi 1 / Zero | Pi 4 / 400 |
|---|---|---|
| Первая стадия | ROM GPU читает `bootcode.bin` с FAT | загрузчик в EEPROM на плате |
| Прошивка GPU | `start.elf` + `fixup.dat` | `start4.elf` + `fixup4.dat` |
| Конфиг | `config.txt` | `config.txt` |
| Что запускается на ARM | `kernel=` из config.txt | `kernel=` из config.txt |

Сырые сектора не используются вообще: всё — файлы на FAT. Прошивка GPU закрытая,
её берём с `github.com/raspberrypi/firmware` (тег `1.20260915`) и проверяем по
sha256:

{{include board/common/rpi-firmware.sha256 text}}

{{include scripts/fetch-files.sh}}

Хеши посчитаны один раз при добавлении платы. Если файл в кэше испорчен или upstream
подменил его по тому же тегу, сборка остановится.

### U-Boot вместо прямой загрузки ядра

Прошивка умеет грузить ядро сама (`kernel=zImage`, `cmdline.txt`). Но мы запускаем
mainline U-Boot (`kernel=u-boot.bin`), чтобы цепочка была одинаковой на всех платах:
U-Boot выбирает dtb по модели и грузит `extlinux.conf`.

{{include board/rpi4/boot/config.txt text}}

### Ловушка: U-Boot на Pi не стартует без device tree от прошивки

В `board/raspberrypi/rpi/rpi.c`:

```c
int board_fdt_blob_setup(void **fdtp)
{
	if (fdt_magic(fw_dtb_pointer) != FDT_MAGIC)
		return -ENXIO;
	*fdtp = (void *)fw_dtb_pointer;
	return 0;
}
```

А в `lib/fdtdec.c` ошибку игнорируют, только если это `-EEXIST`:

```c
ret = board_fdt_blob_setup(&blob);
if (ret) {
	if (ret != -EEXIST)
		return ret;          /* -ENXIO → U-Boot не стартует */
```

То есть если прошивка GPU **не передала** U-Boot device tree, U-Boot остановится
на самом раннем этапе. Прошивка же передаёт dtb, только если найдёт его в корне FAT
**под своим именем**:

| Плата | Имя, которое ищет прошивка | Имя в mainline |
|---|---|---|
| Pi 4 B / Pi 400 | `bcm2711-rpi-4-b.dtb`, `bcm2711-rpi-400.dtb` | то же |
| Pi 1 B rev 2, A | `bcm2708-rpi-b.dtb` | `bcm2835-rpi-b-rev2.dtb` |
| Pi 1 B+, A+ | `bcm2708-rpi-b-plus.dtb` | `bcm2835-rpi-b-plus.dtb` |
| Zero / Zero W | `bcm2708-rpi-zero(-w).dtb` | `bcm2835-rpi-zero(-w).dtb` |

Отсюда два разных решения:

- **Pi 4/400:** U-Boot для arm64 строит `fdtfile` с каталогом (`broadcom/...`), а
  прошивке dtb нужен в корне. `IMAGE_DTB_LAYOUT := both` кладёт и туда, и туда.
- **Pi 1:** U-Boot для arm32 строит `fdtfile` без каталога (`flat`), а для прошивки
  mainline-dtb копируются ещё и под «старыми» именами через `IMAGE_BOOT_FILES`:

{{include configs/rpi1_defconfig 42-52 make}}

Каталог в `fdtfile` определяет одна строка в `rpi.c`:

```c
#ifdef CONFIG_ARM64
#define DTB_DIR "broadcom/"
#else
#define DTB_DIR ""
#endif
```

!!! tip "Совет"
    Узнавать такие вещи надёжнее всего из кода загрузчика, а не из чужих инструкций:
    `grep -n 'fdtfile\|DTB_DIR' board/<vendor>/<board>/*.c include/configs/<board>.h`.

### Консоль

| Плата | Консоль на GPIO14/15 | Замечание |
|---|---|---|
| Pi 1 | `ttyAMA0` (PL011) | `stdout-path = "serial0:115200n8"` |
| Pi 4/400 | `ttyS1` (mini-UART) | `stdout-path = "serial1:115200n8"`; частота mini-UART зависит от частоты ядра GPU — `enable_uart=1` её фиксирует |

У Pi 400 главная консоль — HDMI и встроенная клавиатура. Для этого во фрагменте
ядра встроены HDMI (VC4), PCIe, xHCI (контроллер USB VL805 висит на PCIe) и HID:

{{include board/rpi4/linux/rpi4.config}}

`CONFIG_SOUND=y` появился после предупреждения `kconfig-check.sh` (глава 2): без него
VC4 оставался модулем.

## Сборка нескольких плат

Тулчейны для arm32 нужно поставить отдельно:

```bash
sudo apt install gcc-arm-linux-gnueabihf
make FW=bbb uboot linux rootfs image
make FW=rpi1 uboot bootfw linux rootfs image
make FW=rpi4 uboot bootfw linux rootfs image
```

!!! danger "По одной"
    Не запускайте несколько сборок Buildroot параллельно на машине с 14–16 ГБ ОЗУ.
    Подробности — в главе 14.

## Проверка образов

```bash
for f in rpi1 rpi4; do mdir -b -i output/$f/image-work/boot.vfat ::/; done
```

```text
rpi1: bcm2708-rpi-b.dtb bcm2708-rpi-b-plus.dtb ... bcm2835-rpi-zero-w.dtb bootcode.bin
      config.txt extlinux/ fixup.dat LICENCE.broadcom start.elf u-boot.bin zImage
rpi4: bcm2711-rpi-400.dtb bcm2711-rpi-4-b.dtb bcm2711-rpi-cm4-io.dtb broadcom/ config.txt
      extlinux/ fixup4.dat Image LICENCE.broadcom start4.elf u-boot.bin
```

!!! note "Статус"
    На момент написания образы BBB, RPi 1 и RPi 4/400 собраны и проверены по
    содержимому, но на железе ещё не запускались. Первые запуски — хорошее упражнение
    на методику главы 11.
