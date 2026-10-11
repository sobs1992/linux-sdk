# Методика

## Перед записью карты

```bash
make info                      # строка Firmware: — та ли плата выбрана?
make FW=<fw> image             # образ собран из текущих компонентов
sfdisk -l output/<fw>/images/<fw>.img
mtype -i output/<fw>/image-work/boot.vfat ::/extlinux/extlinux.conf
```

Проверьте в `extlinux.conf` командную строку ядра: консоль и параметры, которые вы
меняли (например, `fbcon=rotate:3` для OGA). Это дешевле, чем выяснять на плате.

## Запись

```bash
lsblk                                   # какое устройство — карта
make FW=<fw> flash DEV=/dev/sdX         # весь образ
```

`make flash` пишет образ **выбранной** прошивки; `FW=` задаёт её явно.

## Журнал загрузки

Подключите UART (глава 2 второй книги) и запишите загрузку в файл **с момента
включения** — потом его можно сравнить с ожидаемым:

```bash
stty -F /dev/ttyUSB0 115200 raw -echo cs8 -cstopb -parenb -crtscts
timeout 120 cat /dev/ttyUSB0 | tee boot-<fw>-$(date +%F).log
```

Или `picocom -b 115200 --logfile boot.log /dev/ttyUSB0`.

!!! warning "Один читатель на порт"
    Пока `cat` или `screen` держат порт, второй процесс получит часть данных или
    ошибку «Device or resource busy». После записи журнала закройте захват.

## Стадии загрузки

Первая проверка на любой плате — до какой стадии дошла загрузка:

| Стадия | Признак в журнале UART | Если не дошли |
|---|---|---|
| Загрузчик ROM/прошивки | у OGA — короткий мусор (1,5 Мбод), у RPi — ничего, у BBB — `CCCC` при отсутствии загрузчика | плата не видит карту/загрузчик |
| U-Boot | `U-Boot 2026.07 (…)` | книга 1, глава 11 |
| Выбор dtb | `Retrieving file: /…dtb` | книга 2, глава 9 |
| Ядро | `Starting kernel …`, затем `Linux version 7.2.9-<fw>` | `earlycon` в командной строке |
| Корень | `VFS: Mounted root (ext4 filesystem)` | `root=PARTUUID`, драйвер SD |
| init | `Run /sbin/init as init process` | rootfs |
| Вход | `<hostname> login:` | getty, консоль |

## Автоматическая проверка

Скрипт `board-check.sh` за несколько секунд проходит по всем подсистемам и печатает
строки `OK`, `WARN`, `FAIL`, `INFO`. Он рассчитан на busybox и не требует пакетов.

Скрипт входит в прошивку всех плат: он лежит в общем overlay
`board/common/buildroot/rootfs-overlay/usr/bin/board-check.sh` и после `make rootfs`
оказывается в `/usr/bin/`. Если на карте старый образ без него, скопируйте вручную:

```bash
scp board/common/buildroot/rootfs-overlay/usr/bin/board-check.sh root@board:/usr/bin/
```

Изменили скрипт — пересоберите rootfs и образ (`make rootfs image`): overlay
копируется заново при каждой сборке rootfs.

Запуск на плате (от root):

```text
# board-check.sh | tee /root/check-$(date +%F).txt
```

Код возврата — число строк `FAIL`. Строки `WARN` требуют внимания, но могут быть
нормой: например, «нет /dev/fb0» у BBB без монитора.

!!! note "Как проверен скрипт"
    Синтаксис — `dash` и `busybox sh`. Запуск — на ПК в окружении из одних апплетов
    busybox (строки про `/boot` и запись в `/root` там ожидаемо `FAIL`). На платах
    скрипт ещё не запускался.

## Протокол

Каждую проверку записывайте: дата, плата и её ревизия, коммит SDK, результат,
примечание. Шаблон — в приложении A. Без протокола через месяц невозможно сказать,
работал ли звук на RPi 1 и с каким ядром.

```bash
git -C ~/linux-sdk describe --always --dirty     # версия SDK для протокола
```
