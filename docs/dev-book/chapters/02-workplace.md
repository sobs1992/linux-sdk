# Рабочее место

## Консоль UART

UART — главный инструмент: он работает, когда не работает ничего другое. Все платы
используют уровни **3,3 В**: адаптер на 5 В может повредить SoC.

| Плата | Устройство в Linux | Где контакты | Скорость |
|---|---|---|---|
| OGA | `ttyS2` (UART2) | отладочный UART, к которому подключён адаптер | 115200 |
| BBB | `ttyS0` (UART0) | разъём J1: 1 — GND, 4 — RX, 5 — TX | 115200 |
| RPi 1 | `ttyAMA0` (PL011) | гребёнка: 6 — GND, 8 — TXD (GPIO14), 10 — RXD (GPIO15) | 115200 |
| RPi 4/400 | `ttyS1` (mini-UART) | те же контакты 6, 8, 10 | 115200 |

TX адаптера соединяется с RX платы и наоборот. На ПК:

```bash
picocom -b 115200 /dev/ttyUSB0          # выход: Ctrl-A Ctrl-X
screen /dev/ttyUSB0 115200              # выход: Ctrl-A K
```

!!! warning "Ловушка: скорость по умолчанию"
    `screen /dev/ttyUSB0` без скорости открывает порт на 9600 бод. Всегда указывайте
    `115200`. И не оставляйте отсоединённую сессию `screen`: она держит порт, и
    другие программы получат «Device or resource busy».

Логин везде — `root` без пароля. На экране (OGA, HDMI у BBB и RPi) тоже есть
приглашение на `tty1`.

## Сеть

### BeagleBone Black, Raspberry Pi 1 B/B+, Raspberry Pi 4/400

На этих платах в rootfs уже настроен DHCP на `eth0` (`BR2_SYSTEM_DHCP="eth0"`) и
стоит SSH-сервер dropbear. Подключите кабель к той же сети, что и ПК, и узнайте
адрес через UART:

```text
# ip -4 addr show eth0
    inet 192.168.1.57/24 ...
```

У Raspberry Pi 1 B/B+ Ethernet висит на USB (чип SMSC LAN9512/9514), у RPi 1 A/A+
и Zero Ethernet нет вовсе — для них подходят USB-Ethernet адаптер (Zero — через
OTG-переходник) или UART.

### ODROID-GO Advance

**Wi-Fi (Black Edition).** Чип ESP8089 на SDIO; драйвер собирается вместе с ядром
внешним модулем, в rootfs есть прошивка, `wpa_supplicant`, `iw` и dropbear. Скрипт
`/etc/init.d/S41wifi` при загрузке ждёт `wlan0` и запускает `wpa_supplicant` и
DHCP-клиент в фоне. Сеть добавляется так:

```text
# wpa_passphrase "MySSID" "password" >> /etc/wpa_supplicant.conf
# /etc/init.d/S41wifi restart
# ip -4 addr show wlan0                       (через 5–10 с)
```

Настройка хранится в rootfs и пропадёт после перепрошивки. Чтобы сети были в каждом
образе, запишите их в `board/oga/buildroot/wifi.conf` на ПК:

```bash
wpa_passphrase "MySSID" "password" | grep -v '#psk' >> board/oga/buildroot/wifi.conf
make rootfs image
```

Файл в `.gitignore` (в нём пароли), при сборке `board/oga/buildroot/post-build.sh`
дописывает его в `/etc/wpa_supplicant.conf` образа. Блоков `network={…}` может быть
несколько: подключится та сеть, что доступна. `grep -v '#psk'` убирает строку с
паролем открытым текстом; в `psk=` остаётся производный ключ — он тоже даёт доступ
к сети, так что файл не публикуйте.

!!! note "Если сетей не видно"
    Драйвер берёт частоту кварца из `/etc/modprobe.d/esp8089.conf` (`crystal=1`,
    26 МГц, как у ROCKNIX). Если `wlan0` есть, а `wpa_cli scan_results` пуст,
    попробуйте `crystal=0` или `crystal=2` и перезагрузку.

**Без Wi-Fi (rev 1.0 или BE без настроенной сети)** — варианты:

1. **USB-Ethernet адаптер** в USB-разъём. Драйверы популярных чипов уже есть в ядре
   модулями (`CONFIG_USB_RTL8152`, `USB_NET_AX88179_178A`, `USB_NET_AX8817X`,
   `USB_NET_CDCETHER`), mdev подгрузит модуль при подключении. Интерфейс появится как
   `eth0`. DHCP у OGA по умолчанию не настроен — поднимите вручную командой
   `udhcpc -i eth0` или добавьте в `board/oga/buildroot/defconfig` строку
   `BR2_SYSTEM_DHCP="eth0"` (тогда без адаптера загрузка будет ждать сеть ~15 секунд).

2. **Передача файлов по UART** (раздел ниже).
3. **Картридер**: вынуть карту и скопировать файлы прямо в rootfs.

### SSH без пароля

С пустым паролем dropbear не пустит. Два варианта:

- задать пароль на плате: `passwd` (хранится в rootfs и пропадёт после перепрошивки);
- положить свой **публичный** ключ в `board/common/buildroot/authorized_keys` — тогда
  доступ будет в каждом образе любой платы:

```bash
cp ~/.ssh/id_ed25519.pub board/common/buildroot/authorized_keys
make rootfs image
```

Файл в `.gitignore` (ключ личный), общий `post-build.sh` кладёт его в
`/root/.ssh/authorized_keys` с нужными dropbear правами (700 на каталог, 600 на файл).

!!! note "Ключ хоста"
    Dropbear создаёт ключ хоста при первом запуске и хранит его в rootfs. После
    перепрошивки ключ новый, и `ssh` выдаст `REMOTE HOST IDENTIFICATION HAS CHANGED`.
    Уберите старую запись: `ssh-keygen -R <адрес>`.

После этого:

```bash
scp hello root@192.168.1.57:/usr/bin/
ssh root@192.168.1.57 hello
```

## Передача файлов по UART

Когда сети нет, небольшие файлы (программы, модули) можно передавать по той же
консоли протоколом ZMODEM. Нужен пакет `lrzsz` в rootfs
(`BR2_PACKAGE_LRZSZ=y` в defconfig платы) и `lrzsz` + `picocom` на ПК.

```bash
picocom -b 115200 --send-cmd "sz -vv" --receive-cmd "rz -vv" /dev/ttyUSB0
# на плате:
# cd /tmp && rz
# в picocom: Ctrl-A Ctrl-S, ввести имя файла на ПК
```

Скорость — около 10 КиБ/с на 115200 бод: модуль ядра на 10–20 КиБ приходит за пару
секунд, а ядро на 40 МиБ — уже нет.

## Картридер

Раздел BOOT — FAT, его монтирует любой ПК. Rootfs — ext4, её тоже можно смонтировать:

```bash
lsblk                                        # найти карту, пусть это sdX
sudo mount /dev/sdX2 /mnt
sudo cp hello /mnt/usr/bin/ && sync
sudo umount /mnt
```

!!! danger "Опасно"
    Не перепутайте устройство. И всегда `umount` перед извлечением: ext4 с
    неотмонтированного раздела может потерять последние записи.

## Тулчейн для своих программ

Buildroot уже собрал кросс-компилятор с библиотеками rootfs. Его можно брать прямо
из каталога сборки:

| Прошивка | Префикс | Где |
|---|---|---|
| `oga` | `aarch64-buildroot-linux-gnu-` | `output/oga/buildroot/host/bin/` |
| `bbb` | `arm-buildroot-linux-gnueabihf-` | `output/bbb/buildroot/host/bin/` |
| `rpi1` | `arm-buildroot-linux-gnueabihf-` | `output/rpi1/buildroot/host/bin/` |
| `rpi4` | `aarch64-buildroot-linux-gnu-` | `output/rpi4/buildroot/host/bin/` |

```bash
export PATH=$HOME/linux-sdk/output/bbb/buildroot/host/bin:$PATH
arm-buildroot-linux-gnueabihf-gcc -O2 -o hello hello.c
```

!!! warning "Ловушка: у BBB и RPi 1 одинаковый префикс, но разные тулчейны"
    Оба называются `arm-buildroot-linux-gnueabihf-gcc`, но тулчейн BBB настроен на
    Cortex-A8 + NEON (ARMv7), а RPi 1 — на ARM1176 (ARMv6). Программа, собранная для
    BBB, на RPi 1 упадёт с `Illegal instruction`. Следите, чей `host/bin` стоит в `PATH`.

Для работы вне дерева SDK или на другой машине есть переносимый вариант:
`make FW=<fw> rootfs-sdk` (первая книга, глава 9). В нём же лежит toolchain-файл для
CMake: `share/buildroot/toolchainfile.cmake`.

Обычный системный кросс-компилятор (`aarch64-linux-gnu-gcc` из apt) годится для ядра
и U-Boot, но **не для программ**: его glibc и библиотеки отличаются от тех, что в
rootfs, и программа может не запуститься с ошибкой про версию glibc.
