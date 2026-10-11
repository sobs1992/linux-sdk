# Практикум

## Где держать свой код

Предлагаемая раскладка в репозитории SDK:

```text
apps/                             исходники своих программ (по каталогу на программу)
apps/kmod/                        свои модули ядра вне дерева (+ module.mk)
board/common/buildroot/package/   пакеты для своих программ
board/common/buildroot/rootfs-overlay/
board/<плата>/...                 конфиги и фрагменты плат
src/linux, src/u-boot             правки ядра и загрузчика — в ветке oga, push в свои форки
```

Коммиты в SDK и в сабмодули — отдельные. Порядок, когда менялось ядро:

```bash
cd src/linux && git commit ... && git push mine oga && cd ../..
git add src/linux apps board configs && git commit -m "..." && git push
```

## Чек-лист перед коммитом

| Изменение | Проверить |
|---|---|
| Программа | собрана тулчейном прошивки; `file` показывает нужную архитектуру; работает на плате |
| Пакет | `make rootfs-make BR=<пакет>-rebuild`; файл есть в `rootfs.tar` (`tar -tvf`) |
| Модуль | собран против текущего ядра (`modinfo -F vermagic`); `insmod`/`rmmod` без oops |
| Фрагмент ядра/U-Boot | нет `WARNING` от `kconfig-check.sh` |
| Device tree | `fdtget` на собранном dtb показывает узел; драйвер привязался (`/sys/bus/.../drivers/`) |
| U-Boot | загрузка доходит до `login:`; запасная карта под рукой |
| Образ | `make image` без ошибок; при больших изменениях — полная перепрошивка `make flash` |

## Задания

!!! example "1. Все платы: hello везде"
    Соберите `hello` для каждой из четырёх прошивок и проверьте `file`. Запустите
    BBB-версию на RPi 1 (если есть обе) и объясните ошибку.

!!! example "2. Все платы: пакет и init-скрипт"
    Перенесите `sdk-hello` в `board/common/buildroot/package`, `hello` — в `apps/hello`,
    включите пакет в defconfig одной платы. Убедитесь, что при загрузке в
    `/var/log/messages` появляется строка от `sdk-hello`.

!!! example "3. OGA: игра"
    На основе `oga-pad` сделайте «змейку»: таймер через `poll` с тайм-аутом, движение
    по крестовине, перезапуск по Start. Добавьте звук: `aplay` короткого WAV через
    `system()` или ALSA API.

!!! example "4. OGA: датчик на I2C"
    Подключите к P2 (контакты 7, 8, питание 3,3 В) любой I2C-датчик, найдите его
    `i2cdetect -y 1` (пакет i2c-tools), затем опишите его overlay и найдите драйвер в
    ядре по `compatible`.

!!! example "5. BBB: светодиод по device tree"
    Соберите `sdk-gpio-led` в образ (`make install` + `make image`), подключите светодиод
    к P9_12, примените overlay через `fdtoverlays`. Поменяйте частоту на лету:
    `echo 200 > /sys/module/sdk_gpio_led/parameters/period_ms`.

!!! example "6. BBB или RPi 4: NFS-корень"
    Настройте TFTP + NFS (глава 3) и сделайте цикл «правка драйвера → перезагрузка»
    без извлечения карты.

!!! example "7. RPi 1 / 4: кнопка"
    Подключите кнопку к GPIO27 и GND. В device tree опишите её как `gpio-keys` с
    `linux,code = <KEY_ENTER>` и `bias-pull-up` в pinctrl (или внешним резистором).
    Проверьте `evtest` и модулем `padlog`.

!!! example "8. RPi 400: своя команда U-Boot"
    Добавьте `sdkinfo` во фрагмент U-Boot RPi 4. Задайте `fdtoverlay_addr_r` по
    умолчанию: допишите строку `fdtoverlay_addr_r=0x05700000` в файл окружения платы
    `src/u-boot/board/raspberrypi/rpi/rpi.env` (коммит в ветке `oga`). Проверьте
    `sdkinfo` и `printenv fdtoverlay_addr_r` после `env default -a`.

!!! example "9. SDK: IMAGE_FDTOVERLAYS"
    Реализуйте в `mkimage.sh` переменную `IMAGE_FDTOVERLAYS`: собранные `.dtbo` — в
    BOOT, строка `fdtoverlays` — в `extlinux.conf`. Проверьте на BBB.

!!! example "10. SDK: LINUX_EXT_MODULES"
    Встройте сборку своих модулей в цель `linux` по рецепту главы 7 и убедитесь, что
    после `make linux image` модуль `sdk-gpio-led` загружается сам.
