# Правки в U-Boot

Загрузчик менять страшнее всего: сломанный U-Boot — и плата не дойдёт до Linux.
Поэтому сначала о том, как безопасно проверять изменения на каждой плате.

## Какой U-Boot на самом деле работает

| Плата | Откуда берётся U-Boot | Что пересобрать и записать |
|---|---|---|
| OGA, заводской SPI | `uboot.img` с сектора 16384 (U-Boot proper, без SPL) | `make uboot image` + `flash-boot` |
| OGA, пустой SPI | idbloader (TPL+SPL) с сектора 64 + FIT с сектора 2048 | то же |
| BBB | файлы `MLO` и `u-boot.img` на разделе BOOT | `make uboot`, скопировать два файла на FAT |
| RPi 1, RPi 4/400 | файл `u-boot.bin` на разделе BOOT (его запускает прошивка GPU) | `make uboot`, скопировать файл на FAT |

!!! warning "OGA: правки в SPL и TPL не видны с заводским SPI"
    На Black Edition с заводским загрузчиком во SPI DDR инициализирует блоб Rockchip, а
    SPL не запускается вовсе — работает только U-Boot proper из `uboot.img`. Правка в
    `arch/arm/mach-rockchip/` для SPL или в драйвере DDR на такой консоли ничего не
    изменит. Проверить, что вообще работает SPL, можно по логу: строки
    `U-Boot SPL 2026.07` при загрузке нет.

## Как восстановиться, если U-Boot сломан

| Плата | Восстановление |
|---|---|
| OGA | SD-карта съёмная, SPI мы не трогаем: `make flash-boot` старого образа через картридер |
| BBB | без кнопки S2 плата загрузится с eMMC; карту исправить на ПК (вернуть `MLO`, `u-boot.img`) |
| RPi | вернуть `u-boot.bin` на карте; в крайнем случае `config.txt`: `kernel=zImage`/`Image` — прошивка загрузит ядро напрямую |

!!! tip "Держите запасную карту"
    Самая дешёвая страховка при работе с загрузчиком — вторая SD-карта с заведомо
    рабочим образом.

## Окружение

U-Boot хранит переменные (`bootcmd`, `bootdelay`, адреса, ваши настройки) в
«окружении»:

| Плата | Где хранится | Когда сбрасывается |
|---|---|---|
| OGA | сырая область MMC, 16–32 КиБ от начала карты | `make flash` (образ пишет туда нули) |
| BBB, RPi | файл `uboot.env` на разделе BOOT | `make flash`, `make flash-boot` (перезаписывают BOOT) |

```text
=> printenv                       всё окружение
=> printenv fdtfile board_name
=> setenv bootdelay 5
=> saveenv                        записать
=> env default -a; saveenv        вернуть значения по умолчанию
```

Пока `saveenv` не вызывали, U-Boot при старте пишет `Loading Environment from ...
*** Warning - bad CRC, using default environment`. Это нормально.

Значения по умолчанию лучше задавать не в сохранённом окружении, а в конфиге — тогда
они переживут перепрошивку. Например, во фрагмент `board/oga/u-boot/oga.config`:

```text
CONFIG_BOOTDELAY=5
```

## Полезные команды

```text
=> bootflow scan -l          что U-Boot нашёл для загрузки (SD, сеть...)
=> bootflow scan -lb         найти и загрузить первое
=> mmc list ; mmc dev 0 ; mmc info
=> ls mmc 0:1 /              файлы на разделе BOOT
=> load mmc 0:1 ${kernel_addr_r} /Image
=> md.l ${fdt_addr_r} 10     дамп памяти
=> fdt addr ${fdt_addr_r}; fdt print /chosen
=> gpio status -a            линии GPIO
=> i2c bus ; i2c dev 1 ; i2c probe
=> dm tree                   устройства в модели драйверов U-Boot
=> bdinfo                    память, адреса
```

На OGA есть ещё `led list` и `led <имя> on|off` (`CMD_LED`) и `sf probe` для SPI-флеша.

## Пример: своя команда

Команда `sdkinfo` печатает то, что U-Boot выяснил о плате: имя, выбранный для ядра
dtb и объём памяти. Это хороший шаблон для любой своей диагностики.

{{include docs/dev-book/examples/uboot/cmd/sdkinfo.c c}}

`U_BOOT_CMD(имя, макс. аргументов, повторять по Enter, функция, кратко, подробно)`
регистрирует команду. `gd` — глобальные данные U-Boot, в том числе размер RAM.

Подключение — в `src/u-boot` (ветка `oga`):

```bash
cp docs/dev-book/examples/uboot/cmd/sdkinfo.c src/u-boot/cmd/
```

В `cmd/Kconfig` (например, перед `config CMD_SLEEP`):

{{include docs/dev-book/examples/uboot/cmd/Kconfig.snippet text}}

В `cmd/Makefile`:

{{include docs/dev-book/examples/uboot/cmd/Makefile.snippet make}}

Включить для платы — строка во фрагменте U-Boot (у OGA он уже есть, для других плат
создайте `board/<плата>/u-boot/<плата>.config` и укажите его в `UBOOT_FRAGMENTS`):

```text
CONFIG_CMD_SDKINFO=y
```

```bash
make FW=oga uboot image && make FW=oga flash-boot DEV=/dev/sdX
```

Вывод (примерный; имя платы и dtb у каждой свои):

```text
=> help sdkinfo
sdkinfo - show board info collected by U-Boot
=> sdkinfo
board:     <имя из таблицы go2.c>
fdtfile:   rockchip/rk3326-odroid-go2-v11.dtb
RAM:       1022 MiB
bootdelay: 2
```

На BBB `board_name` берётся из EEPROM платы (`A335BNLT` у BeagleBone Black), на
Raspberry Pi — из таблицы ревизий в `board/raspberrypi/rpi/rpi.c`.

!!! note "Что проверено"
    Команда собрана для OGA (`odroid-go2_defconfig` + фрагмент SDK, aarch64) и для
    RPi 1 (`rpi_defconfig`, arm) без предупреждений; строка справки есть в
    `u-boot.bin`. На железе не запускалась.

## Пример: меню с запасным ядром

Когда экспериментируете с ядром, полезно держать на карте **заведомо рабочее** ядро и
выбирать при загрузке. U-Boot понимает меню в `extlinux.conf`:

```text
menu title OdroidLinux boot
timeout 50
default stable

label stable
	menu label Stable kernel
	kernel /Image
	fdtdir /
	append root=PARTUUID=4f474131-02 rootwait rw console=ttyS2,115200n8 console=tty1 fbcon=rotate:3

label test
	menu label Test kernel
	kernel /Image-test
	fdtdir /
	append root=PARTUUID=4f474131-02 rootwait rw console=ttyS2,115200n8 earlycon ignore_loglevel
```

`timeout` задаётся в десятых долях секунды. Меню показывается на консоли UART: пункты
пронумерованы, выбор — вводом номера. Новое ядро копируйте на BOOT как `Image-test` — и если оно не
загрузится, следующая загрузка по умолчанию пойдёт со стабильным.

!!! warning "Модули"
    Оба ядра используют одни и те же `/lib/modules` в rootfs. Если версия тестового
    ядра другая (например, сменили `LOCALVERSION`), его модули нужно доложить в rootfs
    отдельно.

## Отладка самого U-Boot

- `CONFIG_LOG=y` и команда `log level 7` — подробный лог подсистем.
- `#define DEBUG` в начале `.c`-файла включает `debug()` в этом файле.
- Если U-Boot падает раньше консоли, помогает **debug UART** (`CONFIG_DEBUG_UART=y`):
  он работает с первой инструкции. У OGA он уже включён (первая книга, глава 7).
- `bdinfo` и `dm tree` показывают, что U-Boot думает о памяти и устройствах.
