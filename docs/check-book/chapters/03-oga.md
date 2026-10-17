# ODROID-GO Advance

Плата: RK3326, 4 × Cortex-A35, 1 ГБ. Консоль — `ttyS2`, 115200. Прошивка `oga`.

## 1. Загрузка — проверено на железе

Журнал UART Black Edition с заводским загрузчиком во SPI:

```text
<короткий мусор: DDR-блоб и miniloader на 1,5 Мбод>
U-Boot 2026.07 (…)
Model: ODROID-GO Advance
DRAM:  1 GiB (total 1022 MiB)
** Booting bootflow 'mmc@ff370000.bootdev.part_1' with extlinux
Retrieving file: /Image
Retrieving file: /rockchip/rk3326-odroid-go2-v11.dtb
Starting kernel ...
[    0.000000] Machine model: ODROID-GO Advance Black Edition
…
odroid-go login:
```

| Проверка | Норма |
|---|---|
| Выбор dtb | BE → `rk3326-odroid-go2-v11.dtb`; rev 1.0 → `rk3326-odroid-go2.dtb`; Super → `rk3326-odroid-go3.dtb` |
| Синий светодиод | загорается в U-Boot, в Linux мигает (`heartbeat`) |
| Безобидные строки | `Loading Boot0000 'mmc 0' failed`, `mmc0: error -110 whilst initialising SD card` (вторая попытка успешна) |

## 2. Экран — проверено на железе

```text
# cat /sys/class/graphics/fbcon/rotate          3
# cat /sys/class/graphics/fb0/virtual_size
# ls /sys/class/backlight/
# cd /sys/class/backlight/* && cat max_brightness
# echo 10 > brightness ; echo $(cat max_brightness) > brightness
```

**Норма:** лог и приглашение на экране, текст читается в альбомной ориентации
(`fbcon=rotate:3`), яркость меняется.

!!! note "Ориентация"
    Правильная ориентация на Black Edition — `rotate:3`; подсказка из DTS
    (`rotation = <270>`) дала бы перевёрнутую картинку. Без
    `CONFIG_FRAMEBUFFER_CONSOLE_ROTATION` параметр игнорируется (он включён во
    фрагменте OGA).

## 3. Кнопки — проверено на железе

```text
# evtest                     выбрать gpio-keys
```

Нажмите **каждую** кнопку и отметьте в протоколе событие `EV_KEY … value 1`
(нажатие) и `value 0` (отпускание):

| Кнопки | Коды |
|---|---|
| Крестовина | `BTN_DPAD_UP`, `_DOWN`, `_LEFT`, `_RIGHT` |
| A, B, X, Y | `BTN_EAST`, `BTN_SOUTH`, `BTN_WEST`, `BTN_NORTH` (соответствие надписям проверьте по событиям) |
| F1–F6 | `BTN_TRIGGER_HAPPY1` … `BTN_TRIGGER_HAPPY6` |
| Курки | `BTN_TL`, `BTN_TR` |
| Вторые курки (только Black Edition) | `BTN_TL2`, `BTN_TR2` |

Итого 16 кнопок у rev 1.0, 18 у Black Edition. Кнопка питания — отдельное устройство
`rk805 pwrkey` (`KEY_POWER`).

## 4. Стик — проверено на железе

```text
# evtest                     выбрать adc-joystick
```

**Норма:** при отклонении меняются `ABS_X` и `ABS_Y`, в покое значения возвращаются к
центру, крайние положения дают значения у границ диапазона (диапазон evtest печатает
в начале: `Min`, `Max`). Запишите в протокол центр и крайние значения: при износе стика
центр «уплывает».

## 5. Демонстрация: oga-pad

```text
# oga-pad
```

Квадрат в центре экрана, крестовина двигает его в ту же сторону, куда нажата,
A/B/X/Y меняют цвет, F6 — выход. Проверяет сразу ввод, framebuffer и поворот.

## 6. Звук — ожидаемо

```text
# aplay -l                    карта на кодеке RK817
# amixer                      регуляторы громкости
# speaker-test -t sine -f 440 -l 1
```

Проверьте динамик и наушники отдельно. Вставка наушников — событие на входном
устройстве `rk817_int Headphones` (`evtest`, `SW_HEADPHONE_INSERT`). Если тишина —
ищите в `amixer contents` переключатель выхода и громкость, отключённую по умолчанию.

## 7. Питание — ожидаемо

```text
# ls /sys/class/power_supply/
# cat /sys/class/power_supply/*/status /sys/class/power_supply/*/capacity
```

**Норма:** при подключённом питании USB-C статус `Charging`, без него `Discharging`,
ёмкость в процентах меняется со временем. Драйвер зарядки RK817 — модуль
(`lsmod | grep rk817`). Красный светодиод `red:charging` горит при зарядке.

## 8. Часы — ожидаемо

```text
# hwclock -r                  RTC в PMIC RK817 (rk808-rtc)
# date -s "2026-10-11 12:00" && hwclock -w
```

Выключите питание на минуту, включите: `hwclock -r` должен показать время, ушедшее
вперёд на эту минуту (пока батарея не разряжена).

## 9. USB — ожидаемо

Вставьте флешку в USB-разъём:

```text
# dmesg | tail                sd 0:0:0:0: [sda] … Attached SCSI removable disk
# mount /dev/sda1 /mnt && ls /mnt && umount /mnt
```

Сеть через USB-Ethernet адаптер: появится `eth0`, `udhcpc -i eth0` получит адрес.

## 10. Разъём расширения P2 — ожидаемо

**UART1, петля.** Соедините перемычкой контакт 2 (RXD) и 3 (TXD):

```text
# stty -F /dev/ttyS1 115200 raw -echo
# cat /dev/ttyS1 &
# echo hello > /dev/ttyS1            должно напечататься hello
# kill %1
```

**I2C1** (контакты 7 — SCL, 8 — SDA). Нужен пакет `i2c-tools`:

```text
# i2cdetect -y 1                     без устройств — все "--"
```

С подключённым датчиком появится его адрес.

## 11. Датчики и частота — ожидаемо

```text
# cat /sys/class/thermal/thermal_zone*/type /sys/class/thermal/thermal_zone*/temp
# cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
```

Под нагрузкой (глава 2, прогон) частота растёт, температура не уходит за 80 °C.

## 12. Wi-Fi (только Black Edition) — проверено на железе

```text
# lsmod | grep esp8089
esp8089                73728  0
# dmesg | grep mmc1 | tail -1
mmc1: new high speed SDIO card at address 0001
# wpa_passphrase "MySSID" "password" >> /etc/wpa_supplicant.conf
# /etc/init.d/S41wifi restart
# wpa_cli -i wlan0 status | grep -E "^(wpa_state|key_mgmt|ip_address)="
key_mgmt=WPA2-PSK
wpa_state=COMPLETED
ip_address=10.117.40.169
# iw dev wlan0 link | grep bitrate
        rx bitrate: 52.0 MBit/s MCS 5
        tx bitrate: 72.2 MBit/s MCS 7 short GI
# ping -c 4 8.8.8.8 | tail -1
round-trip min/avg/max = 13.781/35.661/44.287 ms
```

С ПК в той же сети, с ключом из `board/common/buildroot/authorized_keys`:

```text
$ ssh root@10.117.40.169 uname -r
7.2.9-oga
```

Модуль `esp8089` загружается сам (mdev), прошивка `eagle_fw_*_v19.bin` грузится,
появляется `wlan0`, после настройки адрес приходит по DHCP. Только 2.4 ГГц: сети
5 ГГц чип не видит. На rev 1.0 чипа нет — `wlan0` не появится.

| Симптом | Причина и что делать |
|---|---|
| `wlan0` есть, `wpa_cli scan_results` пуст | не та частота кварца: `crystal=0` или `=2` в `/etc/modprobe.d/esp8089.conf`, перезагрузка |
| `AP is in CSA process, reject auth` | точка объявляет смену канала (элементы 37/60 в маяке, `wpa_cli bss <bssid>`). Если отсчёт застыл, это баг роутера (встречено у ASUS RT-AX57 на автоканале): mac80211 к такой точке не подключается, телефоны подключаются. Лечится на роутере — перезагрузка или фиксированный канал 2.4 ГГц |
| `deferred probe pending: … supplier wifi-pwrseq not ready` | ядро без `CONFIG_RESET_GPIO=y`: SDIO-контроллер не стартует |

## Не работает по известным причинам

| Что | Почему |
|---|---|
| USB-гаджет через OTG | не проверялся; разъём может быть разведён только как хост |
