# Правки ядра и device tree

## Порядок работы с исходниками ядра

```bash
cd src/linux
git switch oga                         # все правки — в ветке oga
$EDITOR drivers/...                    # правка
cd ../..
make FW=rpi4 linux                     # инкрементальная сборка: секунды–минуты
make FW=rpi4 image                     # образ с новыми модулями
make FW=rpi4 flash-boot DEV=/dev/sdX   # или TFTP (глава 3)
```

Когда работает:

```bash
cd src/linux
git add -p && git commit -s -m "drivers: ..."
git format-patch -1                    # патч для отправки upstream или в другой проект
```

!!! warning "Ловушка: относительный `O=`"
    Если запускаете make ядра руками, путь в `O=` должен быть **абсолютным**:
    `make -C src/linux O=output/oga/linux ...` трактует `O` относительно `src/linux` и
    создаст `src/linux/output/...` — и ещё пожалуется, что `.config` не найден.
    Цели SDK (`make linux` и др.) всегда передают абсолютные пути.

## Опции ядра

`make linux-menuconfig` меняет `.config`, но при следующей смене фрагмента изменения
пропадут (первая книга, глава 6). Перенесите их во фрагмент. Чтобы понять, что именно
поменялось, есть `scripts/diffconfig`:

```bash
cp output/oga/linux/.config /tmp/before
make FW=oga linux-menuconfig
src/linux/scripts/diffconfig /tmp/before output/oga/linux/.config
#  USB_CONFIGFS m -> y
# +USB_CONFIGFS_F_HID y
```

Перепишите строки в формат фрагмента (`CONFIG_USB_CONFIGFS=y`) в
`board/oga/linux/oga.config` и пересоберите: `kconfig-check.sh` сразу скажет, если
какая-то опция не встала из-за зависимостей.

## Свой драйвер в дереве ядра

Модуль из главы 7 можно перенести в дерево — тогда он собирается вместе с ядром,
выбирается в menuconfig и может быть встроенным (`=y`).

```bash
cp docs/dev-book/examples/kmod/sdk-gpio-led/sdk-gpio-led.c src/linux/drivers/misc/
```

В `drivers/misc/Kconfig`:

```text
config SDK_GPIO_LED
	tristate "OdroidLinux SDK example GPIO LED driver"
	depends on GPIOLIB && OF
	help
	  Blinks a GPIO described by an "sdk,gpio-led" device tree node.
```

В `drivers/misc/Makefile`:

```make
obj-$(CONFIG_SDK_GPIO_LED)	+= sdk-gpio-led.o
```

И во фрагмент платы — `CONFIG_SDK_GPIO_LED=m` (или `=y`). Дальше `make linux image`.

## Device tree: два способа

Устройство, которое ядро не может обнаружить само (светодиод на GPIO, датчик на I2C,
дисплей на SPI), описывается в device tree. Есть два пути:

| | Правка `.dts` платы | Overlay (`.dtbo`) |
|---|---|---|
| Где | `src/linux/arch/.../dts/...`, коммит в ветке `oga` | отдельный файл, накладывается при загрузке |
| Когда применяется | при сборке dtb | U-Boot перед стартом ядра (`fdtoverlays` в extlinux) |
| Плюсы | просто, видно в git ядра | не трогает ядро; можно включать и выключать на карте |
| Минусы | меняет dtb для всех | нужны `__symbols__` в базовом dtb |

### Правка `.dts`

Например, для Raspberry Pi 4 — в конец `arch/arm/boot/dts/broadcom/bcm2711-rpi-4-b.dts`
(arm64-dts Pi 4 подключает этот файл из `arch/arm`):

```dts
/ {
	sdk-led {
		compatible = "sdk,gpio-led";
		led-gpios = <&gpio 17 GPIO_ACTIVE_HIGH>;
	};
};
```

`make linux image`, и после загрузки:

```text
# ls /proc/device-tree/sdk-led/
compatible  led-gpios  name
# ls /sys/bus/platform/drivers/sdk-gpio-led/
bind  sdk-led  uevent  unbind              <- драйвер привязался к узлу
```

### Overlay

Overlay — это фрагмент device tree с пометкой `/plugin/`, который ссылается на узлы
базового dtb **по меткам** (`&gpio`, `&am33xx_pinmux`, `&i2c1`). Чтобы метки можно
было найти, базовый dtb должен содержать таблицу `__symbols__`.

| Плата | `__symbols__` в dtb SDK | Что сделать |
|---|---|---|
| BBB | есть | ничего |
| RPi 1, RPi 4/400 | есть | ничего |
| OGA | **нет** | собрать ядро с `DTC_FLAGS=-@` |

Проверка: `fdtget -l output/oga/linux-install/dtbs/rockchip/rk3326-odroid-go2-v11.dtb / | grep __symbols__`.
Для OGA добавьте в `configs/oga_defconfig`:

```make
LINUX_MAKE_ARGS := DTC_FLAGS=-@
```

Это проверено: с `DTC_FLAGS=-@` в dtb появляется `__symbols__`, без него — нет.

#### BeagleBone Black: светодиод на P9_12 с pinmux

{{include docs/dev-book/examples/dts/bbb-sdk-led.dtso dts}}

Обратите внимание на **pinmux**: на AM335x каждый вывод (pad) выполняет одну из
восьми функций. `AM33XX_PADCONF(AM335X_PIN_GPMC_BEN1, PIN_OUTPUT, MUX_MODE7)` говорит
контроллеру выводов: pad `gpmc_be1n` (это P9_12) — в режим 7 (GPIO), на выход. Драйвер
`pinctrl-single` применит настройку, когда к узлу `sdk-led` привяжется драйвер
(`pinctrl-names = "default"`).

#### Raspberry Pi 1 / 4 / 400: GPIO17

{{include docs/dev-book/examples/dts/rpi-sdk-led.dtso dts}}

#### ODROID-GO Advance: EEPROM на I2C разъёма P2

{{include docs/dev-book/examples/dts/oga-i2c-eeprom.dtso dts}}

Драйвер `at24` (модулем в ядре OGA) создаст файл `/sys/bus/i2c/devices/1-0050/eeprom`,
который читается и пишется как обычный файл. Без overlay то же устройство можно
«объявить» и вручную: `echo 24c32 0x50 > /sys/bus/i2c/devices/i2c-1/new_device`.

#### Сборка overlay

{{include docs/dev-book/examples/dts/build-overlay.sh}}

```bash
docs/dev-book/examples/dts/build-overlay.sh src/linux \
    docs/dev-book/examples/dts/bbb-sdk-led.dtso bbb-sdk-led.dtbo
```

Препроцессор C нужен, чтобы раскрыть `#include` и макросы (`GPIO_ACTIVE_HIGH`,
`AM33XX_PADCONF`), а `dtc -@` сохраняет ссылки на метки для применения позже.

#### Проверка на ПК

Ещё до платы overlay можно наложить на настоящий dtb утилитой `fdtoverlay`:

```bash
fdtoverlay -i output/bbb/linux-install/dtbs/ti/omap/am335x-boneblack.dtb \
           -o /tmp/merged.dtb bbb-sdk-led.dtbo
fdtget /tmp/merged.dtb /sdk-led compatible          # sdk,gpio-led
```

Так проверены все три overlay из этой главы: BBB-overlay — на `am335x-boneblack.dtb`,
RPi-overlay — на dtb RPi 1 B+, B rev2, 4 B и 400, OGA-overlay — на dtb Black Edition,
собранный с `-@`. Если наложить на OGA обычный dtb SDK, `fdtoverlay` ответит
`FDT_ERR_BADOFFSET` — меток нет.

#### Применение при загрузке

U-Boot применяет overlay, перечисленные в строке `fdtoverlays` метки extlinux.
`mkimage.sh` генерирует `extlinux.conf` без неё, поэтому:

1. Положите `.dtbo` в BOOT, например через конфиг прошивки:
   `IMAGE_BOOT_FILES += $(SDK_DIR)/bbb-sdk-led.dtbo` (или скопируйте на карту руками).
2. Добавьте строку в `extlinux/extlinux.conf` на карте:

```text
label linux
	kernel /zImage
	fdtdir /
	fdtoverlays /bbb-sdk-led.dtbo
	append root=PARTUUID=42424231-02 ...
```

U-Boot загружает overlay по адресу из переменной `fdtoverlay_addr_r`:

| Плата | `fdtoverlay_addr_r` в окружении U-Boot |
|---|---|
| OGA | есть (`0x01f00000`) |
| BBB | есть (`0x89000000`) |
| RPi 1, RPi 4 | **нет** — U-Boot напишет `Invalid fdtoverlay_addr_r` и пропустит overlay |

Для Raspberry Pi задайте адрес сами, например сразу после области dtb
(`fdt_addr_r=0x05600000`, под неё отведён 1 МиБ):

```text
U-Boot> setenv fdtoverlay_addr_r 0x05700000
U-Boot> saveenv
```

`0x05700000` совпадает с `ramdisk_addr_r`, но initrd SDK не использует.

!!! tip "Сделать это частью SDK"
    Хороший следующий шаг для SDK — переменная `IMAGE_FDTOVERLAYS` в конфиге
    прошивки, по которой `mkimage.sh` кладёт `.dtbo` в BOOT и дописывает строку
    `fdtoverlays` в `extlinux.conf`. Изменение — десяток строк в `mkimage.sh`.

## Отладка ядра

| Что | Как |
|---|---|
| Лог с самого начала, даже до драйвера UART | добавить `earlycon` в `LINUX_CMDLINE`: ядро возьмёт порт и тип из `stdout-path` (работает на всех четырёх платах) |
| Все сообщения на консоль | `ignore_loglevel` в командной строке или `dmesg -n 8` |
| Почему не привязался драйвер | `cat /sys/kernel/debug/devices_deferred` (после `mount -t debugfs none /sys/kernel/debug`) |
| Сообщения `pr_debug`/`dev_dbg` | `CONFIG_DYNAMIC_DEBUG=y` (включён только в ядре RPi 1, остальным — во фрагмент), затем `echo 'module sdk_gpio_led +p' > /sys/kernel/debug/dynamic_debug/control` |
| Какие опции у работающего ядра | `zcat /proc/config.gz` (OGA, BBB, RPi 4; в ядре RPi 1 нет `IKCONFIG_PROC`) |
| Расшифровать oops | `scripts/decode_stacktrace.sh output/<fw>/linux/vmlinux src/linux < oops.txt` |

!!! note "earlycon"
    Ранняя консоль нужна, когда ядро падает до того, как поднялся настоящий драйвер
    UART: без неё на экране после `Starting kernel ...` — тишина. Для всех плат SDK
    достаточно слова `earlycon`: в их DTS есть `stdout-path`, а драйверы UART
    (`8250` для Rockchip и AM335x, `pl011` для RPi 1, `bcm2835aux` для RPi 4)
    объявляют раннюю консоль.
