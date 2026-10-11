# Общие проверки Linux

Эти проверки одинаковы для всех плат. Большую часть делает `board-check.sh`; здесь —
что за ними стоит и что проверить руками.

## 1. Ядро и командная строка

```text
# uname -r                         7.2.9-<fw>: oga, bbb, rpi1 или rpi4
# cat /proc/device-tree/model      модель из dtb
# cat /proc/cmdline                root=PARTUUID=…-02, консоли, ваши параметры
```

**Норма:** версия заканчивается на имя прошивки, модель — ваша плата и ревизия,
командная строка совпадает с `LINUX_CMDLINE` конфига прошивки.

## 2. Корень и раздел BOOT

```text
# mount | grep -E ' / | /boot '
/dev/root on / type ext4 (rw,…)
/dev/mmcblk0p1 on /boot type vfat (rw,noatime,…)
# ls /boot/extlinux/extlinux.conf
# echo test > /root/t && sync && cat /root/t && rm /root/t
```

**Норма:** корень `ext4` на запись, `/boot` смонтирован (по `LABEL=BOOT`, имя
устройства у RPi 4 может быть `mmcblk1p1`), запись проходит.

## 3. Модули

```text
# ls /lib/modules/$(uname -r)
# lsmod | head
# dmesg | grep -i 'disagrees about version\|Invalid module format'
```

**Норма:** каталог модулей для текущего ядра есть, ошибок формата нет. Если каталога
нет — в rootfs модули другого ядра: пересоберите и запишите образ целиком (`make
linux image`, `make flash`).

## 4. Журнал ядра

```text
# dmesg | grep -n -E 'Oops|BUG:|Call trace|Kernel panic'     должно быть пусто
# dmesg | grep -i -E 'error|fail' | head -30                 изучить каждую строку
```

Строки с `error` не всегда ошибки: драйвер может пробовать несколько вариантов.
Сравнивайте с журналом предыдущей рабочей сборки.

## 5. Консоли

- **UART**: приглашение `login:`, вход `root` без пароля, `Ctrl-C` и `Ctrl-D`
  работают, длинная строка переносится.
- **Экран** (`tty1`): лог загрузки и приглашение на дисплее.

```text
# ps | grep getty                  getty на UART и на tty1
```

## 6. Время

```text
# date
# hwclock -r                       есть, если на плате RTC (OGA, BBB)
```

Без сети и без RTC с батарейкой часы стартуют с 1970 года — это не ошибка.

## 7. Сеть (где есть)

```text
# ip -4 addr                       адрес от DHCP на eth0
# ping -c 3 <адрес ПК>
```

С ПК: `ssh root@<адрес>` (если задан пароль или ключ, вторая книга, глава 2).

## 8. Перезагрузка и выключение

```text
# reboot                           плата должна загрузиться снова
# poweroff                         в журнале UART: "reboot: Power down"
```

Проверьте несколько перезагрузок подряд: проблемы инициализации (SD, DDR) бывают
нестабильными.

## 9. Длительный прогон

Короткая проверка не находит перегрев, утечки и нестабильность питания. Простой
прогон на 30–60 минут:

```text
# for i in 1 2 3 4; do (while :; do :; done) & done     нагрузить все ядра
# while :; do cat /sys/class/thermal/thermal_zone0/temp; sleep 10; done
# dd if=/dev/zero of=/root/big bs=1M count=100 conv=fsync && md5sum /root/big && rm /root/big
# kill %1 %2 %3 %4
```

**Норма:** плата не перезагружается, температура стабилизируется, `dmesg` без новых
ошибок, записанный файл читается.
