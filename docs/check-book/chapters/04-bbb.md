# BeagleBone Black

Плата: AM335x, 1 × Cortex-A8, 512 МБ, eMMC 4 ГБ. Консоль — `ttyS0`, разъём J1
(1 — GND, 4 — RX, 5 — TX), 115200. Прошивка `bbb`. Все результаты — **ожидаемые**.

## 1. Загрузка с SD

BBB по умолчанию грузится с eMMC. Чтобы загрузиться с карты: снять питание, зажать
**S2** (кнопка у слота SD), подать питание, отпустить через 2–3 секунды.

```text
U-Boot SPL 2026.07 (…)
Trying to boot from MMC1
U-Boot 2026.07 (…)
Model: TI AM335x BeagleBone Black
…
Retrieving file: /zImage
Retrieving file: /am335x-boneblack.dtb
Starting kernel ...
Linux version 7.2.9-bbb …
beaglebone login:
```

| Проверка | Норма |
|---|---|
| Загрузились с SD, а не с eMMC | дата сборки в строке `U-Boot 2026.07 (…)` совпадает с вашей сборкой; ядро `7.2.9-bbb` |
| dtb | `am335x-boneblack.dtb` (у Green — `am335x-bonegreen.dtb`) |
| eMMC видна | `ls /dev/mmcblk1*` — **ничего туда не пишите** |

Если в журнале только символы `CCCC…` — ROM не нашёл загрузчик ни на eMMC, ни на SD и
ждёт загрузки по UART: проверьте карту (`MLO` в корне активного FAT-раздела).

## 2. EEPROM платы

```text
# hexdump -C /sys/bus/i2c/devices/0-0050/eeprom | head -2
```

**Норма:** в первых байтах читается `A335BNLT` и ревизия платы. Драйвер `at24` —
модуль, файл появляется после его загрузки (mdev делает это сам).

## 3. Ethernet

```text
# ip -4 addr show eth0        адрес от DHCP
# ping -c 3 <адрес ПК>
```

Светодиоды на разъёме RJ45 горят. С ПК — `ssh root@<адрес>` (после настройки пароля или
ключа).

## 4. Светодиоды USR0–USR3

```text
# ls /sys/class/leds/
beaglebone:green:heartbeat  beaglebone:green:mmc0  beaglebone:green:usr2  beaglebone:green:usr3
# cd /sys/class/leds/beaglebone:green:usr3
# echo none > trigger; echo 1 > brightness; echo 0 > brightness
```

**Норма:** USR0 мигает «сердцебиением», USR1 — при обращениях к SD, USR2/USR3 включаются
вручную.

## 5. HDMI

Подключите монитор **до** включения.

```text
# lsmod | grep -E 'tilcdc|tda998x'
# ls /dev/fb0
```

**Норма:** на мониторе лог и приглашение `tty1`, USB-клавиатура вводит текст.

## 6. USB

Флешка в разъём USB-A: `dmesg | tail`, `mount /dev/sda1 /mnt`.

## 7. Кнопка POWER

```text
# evtest                         устройство кнопки от PMIC TPS65217
```

Короткое нажатие — событие `KEY_POWER`.

## 8. GPIO: P9_12

Светодиод с резистором между P9_12 и GND (P9_1). Номер контроллера банка 1 — по
адресу `4804c000` (`board-check.sh` печатает соответствие, или `gpiodetect`):

```text
# gpio-blink /dev/gpiochipN 28 10 500
```

**Норма:** светодиод мигает 10 раз. Если программа отработала, а светодиод не мигает —
вывод не переведён в режим GPIO: примените overlay `bbb-sdk-led.dtso` с pinmux
(вторая книга, глава 8).

## 9. I2C2 на P9_19/P9_20

```text
# i2cdetect -y -r 2             пакет i2c-tools
```

Адреса `0x54`–`0x57` описаны в DTS как EEPROM плат расширения: при наличии драйвера
`at24` они показываются как `UU`.

## 10. АЦП

```text
# cat /sys/bus/iio/devices/iio:device0/in_voltage0_raw      AIN0 = P9_39
```

!!! danger "Только 1,8 В"
    Входы АЦП AM335x рассчитаны на 0–1,8 В. Подача 3,3 В повредит процессор.
    Опорное напряжение — VDD_ADC (P9_32), земля — GNDA_ADC (P9_34).

## 11. Часы и частота

```text
# hwclock -r                     RTC AM335x (rtc-omap); батарейки нет — время не сохраняется без питания
# cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
```

## Не работает по известным причинам

| Что | Почему |
|---|---|
| Wi-Fi/BT у BeagleBone Black Wireless | нет прошивки чипа WL18xx в rootfs |
| PRU | не настроены в SDK |
| Загрузка без кнопки S2 | ROM выбирает eMMC, если там есть загрузчик |
