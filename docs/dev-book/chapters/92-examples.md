# Указатель примеров

Все файлы лежат в `docs/dev-book/examples/`.

| Файл | Что это | Платы | Глава |
|---|---|---|---|
| `app/hello/` | минимальная программа + Makefile с `?=` и `DESTDIR` | все | 4, 6 |
| `app/cmake-demo/` | CMake-проект для toolchain-файла Buildroot | все | 4 |
| `app/gpio-blink/gpio-blink.c` | мигание GPIO через `/dev/gpiochipN` (uAPI v2) | BBB, RPi | 5 |
| `app/oga-pad/oga-pad.c` | evdev + framebuffer + поворот экрана | OGA | 5 |
| `app/serial-echo/serial-echo.c` | эхо по UART (termios, raw) | OGA (`ttyS1`), все | 5 |
| `package/sdk-hello/` | пакет Buildroot: `generic-package`, `SITE_METHOD=local`, init-скрипт | все | 6 |
| `kmod/module.mk` | сборка модулей против ядра SDK | все | 7 |
| `kmod/hello/` | модуль с параметром | все | 7 |
| `kmod/sdkchar/` | misc-устройство `/dev/sdkchar` | все | 7 |
| `kmod/padlog/` | input handler: лог нажатий | OGA, все с клавиатурой | 7 |
| `kmod/sdk-gpio-led/` | платформенный драйвер по device tree, `devm_*`, workqueue | BBB, RPi | 7, 8 |
| `dts/bbb-sdk-led.dtso` | overlay: P9_12 с pinmux | BBB | 8 |
| `dts/rpi-sdk-led.dtso` | overlay: GPIO17 | RPi 1, 4, 400 | 8 |
| `dts/oga-i2c-eeprom.dtso` | overlay: EEPROM на I2C1 разъёма P2 | OGA | 8 |
| `dts/build-overlay.sh` | сборка `.dtso` → `.dtbo` с заголовками ядра | все | 8 |
| `uboot/cmd/sdkinfo.c` | своя команда U-Boot + фрагменты Kconfig/Makefile | все | 9 |

## Что и как проверено

| Проверка | Результат |
|---|---|
| Программы `app/*` тулчейнами Buildroot `oga`, `bbb`, `rpi1`, `rpi4` (`-Wall -Wextra`) | собраны, предупреждений нет |
| `cmake-demo` с toolchain-файлом каждой прошивки | собран |
| Модули `kmod/*` против ядер `oga`, `bbb`, `rpi1`, `rpi4` | 16 сборок, предупреждений нет |
| Установка модуля через `modules_install` с `O=` и `M=` | ставится в `updates/`, `depmod` отрабатывает |
| Overlay: `fdtoverlay` на dtb BBB, RPi 1 B+/B rev2, RPi 4 B, 400 | узел `sdk-led` на месте |
| Overlay OGA: на dtb, собранный с `-@` | узел `eeprom@50` на месте; на dtb SDK — `FDT_ERR_BADOFFSET` |
| `DTC_FLAGS=-@` при сборке dtb ядра OGA | `__symbols__` появляется |
| Команда `sdkinfo` в U-Boot для OGA и RPi 1 | собрана, предупреждений нет |
| Пакет `sdk-hello` в отдельной сборке Buildroot с тулчейном OGA | собран и установлен; `-rebuild` подхватывает правки, обычный `make` — нет |
| Запуск на железе | **не выполнялся** |
