# Программы для конкретных плат

Ядро даёт к железу стандартные интерфейсы: `/dev/input/event*` для кнопок,
`/dev/fb0` для экрана, `/dev/gpiochipN` для GPIO, `/sys/class/leds/` для светодиодов,
`/dev/ttyS*` для UART, ALSA для звука. Ваша программа работает с ними одинаково на
любой плате — отличаются только имена устройств и номера линий.

## Светодиоды: без единой строки кода

Каждый светодиод из device tree — каталог в `/sys/class/leds/`:

| Плата | Светодиоды |
|---|---|
| OGA | `blue:status` (по умолчанию `heartbeat`), `red:charging` |
| BBB | `beaglebone:green:heartbeat`, `…:mmc0`, `…:usr2`, `…:usr3` |
| RPi 1 B+/A+, RPi 4 B | `ACT`, `PWR` |
| RPi 400 | только `PWR` (`led_act` удалён в DTS платы) |

```text
# cd /sys/class/leds/blue:status            (на BBB: beaglebone:green:usr3, на RPi: ACT)
# cat trigger                               [heartbeat] none timer default-on mmc0 ...
# echo none > trigger
# echo 255 > brightness ; echo 0 > brightness
# echo timer > trigger ; echo 100 > delay_on ; echo 900 > delay_off
```

«Триггеры» — это готовые источники событий в ядре: сердцебиение, активность SD,
таймер, нагрузка CPU. Для многих задач индикации свой код вообще не нужен.

## GPIO: BeagleBone Black и Raspberry Pi

Старый интерфейс `/sys/class/gpio/export` устарел. Современный — **символьное
устройство** `/dev/gpiochipN` (опция `GPIO_CDEV`, включена во всех ядрах SDK).
С ним работают утилиты и библиотека **libgpiod**, а можно и напрямую через `ioctl`.

### Утилиты libgpiod

Включите в defconfig платы `BR2_PACKAGE_LIBGPIOD2=y` и `BR2_PACKAGE_LIBGPIOD2_TOOLS=y`
(глава 6), пересоберите rootfs. На плате:

```text
# gpiodetect                         какие есть контроллеры (вывод на RPi 4, примерный)
gpiochip0 [pinctrl-bcm2711] (58 lines)
# gpioinfo gpiochip0 | head          линии и кто их занял
# gpioset -c gpiochip0 17=1          включить GPIO17
```

### Своя программа

{{include docs/dev-book/examples/app/gpio-blink/gpio-blink.c}}

Программа использует только заголовок ядра `linux/gpio.h` (uAPI v2), так что никаких
библиотек в rootfs не требует.

| Плата | Контакт | Контроллер и линия | Команда |
|---|---|---|---|
| RPi 1 / 4 / 400 | гребёнка, контакт 11 | GPIO17 | `gpio-blink /dev/gpiochip0 17` |
| BBB | P9, контакт 12 | GPIO1_28: банк 1, линия 28 | `gpio-blink /dev/gpiochipN 28` |

Схема для проверки: светодиод через резистор 330–1000 Ом между контактом и GND
(у RPi GND — контакт 9, у BBB — P9.1/P9.2).

!!! warning "BBB: номер контроллера и pinmux"
    1. Банку 1 не обязательно соответствует `/dev/gpiochip1`: порядок регистрации
       контроллеров может отличаться. Ищите по адресу банка (`4804c000` у GPIO1) в
       выводе `gpiodetect`.
    2. Каждый вывод AM335x может выполнять несколько функций, и функцию выбирает
       **pinmux**. Если вывод не настроен как GPIO (mode 7), программа отработает без
       ошибок, а на контакте ничего не изменится. Надёжный способ — описать pinmux в
       device tree (overlay в главе 8 так и делает).

!!! note "RPi: функция вывода"
    У BCM2835/2711 контроллер выводов сам переключает вывод в режим GPIO, когда линию
    запрашивают через `/dev/gpiochip0`. Отдельный pinmux не нужен.

## ODROID-GO Advance: кнопки и экран

У OGA нет свободных GPIO, зато есть геймпад и экран. Пример `oga-pad` двигает квадрат
по экрану крестовиной:

{{include docs/dev-book/examples/app/oga-pad/oga-pad.c}}

Три вещи, которые стоит из него вынести.

**Поиск устройства ввода по имени.** Номер `eventN` зависит от порядка инициализации
драйверов. Надёжнее перебрать `/dev/input/event*` и спросить имя через
`EVIOCGNAME`: у кнопок OGA это `gpio-keys`, у стика — `adc-joystick`.

**Коды кнопок.** Они заданы в DTS (`rk3326-odroid-go.dtsi`): крестовина —
`BTN_DPAD_*`, A/B/X/Y — `BTN_EAST`/`BTN_SOUTH`/`BTN_WEST`/`BTN_NORTH`,
F1–F6 — `BTN_TRIGGER_HAPPY1…6`, курки — `BTN_TL`/`BTN_TR`. Стик — оси `ABS_X`/`ABS_Y`
(события `EV_ABS`). Посмотреть всё вживую: `evtest`.

**Поворот экрана.** Панель OGA установлена повёрнутой. Ядро поворачивает только
текстовую консоль (`fbcon=rotate:3` в командной строке; работает, только если в ядре
включён `CONFIG_FRAMEBUFFER_CONSOLE_ROTATION`), а `/dev/fb0` остаётся в родной
портретной ориентации панели. Программа читает текущий поворот консоли из
`/sys/class/graphics/fbcon/rotate`, работает в «экранных» координатах и пересчитывает
каждую точку так же, как fbcon. Ещё одна деталь — `KDSETMODE KD_GRAPHICS`
на `/dev/tty1`: без него мигающий курсор консоли будет рисоваться поверх картинки.

```text
# oga-pad                          (примерный вывод: панель 320×480)
fb0: 320x480, 32 bpp; screen 480x320 (rotate 3)
```

Поворот можно задать и вручную: `oga-pad 1`. Значения те же, что у `fbcon=rotate:` —
0, 1 (90° по часовой), 2, 3 (90° против часовой). Программа поддерживает 32 и 16 бит на точку.

!!! tip "Для настоящих игр"
    Для графики с ускорением используйте SDL2 (`BR2_PACKAGE_SDL2`, бэкенд KMS/DRM).
    SDL сам найдёт геймпад и экран, но поворот панели всё равно придётся учитывать.

## ODROID-GO Advance: UART на разъёме

На разъёме расширения P2 выведен UART1: контакт 2 — RXD, контакт 3 — TXD (так
написано в комментарии DTS платы). В Linux это `/dev/ttyS1`. К нему можно подключить
GPS-модуль, микроконтроллер или второй USB-UART адаптер:

{{include docs/dev-book/examples/app/serial-echo/serial-echo.c}}

```bash
# плата
serial-echo /dev/ttyS1 115200
# ПК, адаптер на P2
picocom -b 115200 --omap crlf /dev/ttyUSB1      # набираете строку — получаете "echo: ..."
```

`cfmakeraw()` переводит порт в «сырой» режим: без эха, без построчного редактирования
и без преобразования `\r`/`\n`. Почти всегда это то, что нужно для обмена с устройствами.

## Звук

ALSA одинакова на всех платах, отличаются карты: RK817 на OGA, HDMI у RPi 4 и BBB.

```text
# aplay -l                         список карт
# amixer                           регуляторы громкости
# speaker-test -t sine -f 440 -l 1
```

На OGA звук выводится на встроенный динамик или в наушники; переключение — регулятором
`amixer` (смотрите список `amixer controls`).
