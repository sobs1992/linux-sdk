# Ядро Linux

## Какой defconfig взять за основу

Есть три пути:

1. **Общий defconfig архитектуры** (`arch/arm64/configs/defconfig`). Включает
   поддержку сотен плат, почти всё — модулями. Большой (`Image` ≈ 40 МиБ, модули
   ≈ 88 МиБ), но гарантированно содержит всё нужное для SoC.
2. **Defconfig семейства SoC** (`omap2plus_defconfig`, `bcm2835_defconfig`). Меньше
   и точнее, есть только для части платформ.
3. **Свой минимальный defconfig.** Самый компактный, но его нужно составить и
   поддерживать — и легко забыть что-нибудь важное.

Для OGA и Raspberry Pi 4 взят общий arm64 `defconfig`, для BBB — `omap2plus_defconfig`,
для Raspberry Pi 1 — `bcm2835_defconfig`. Поверх каждого — короткий фрагмент.
Ужать ядро можно позже, когда всё заработает (упражнение в конце главы).

## Что добавить для OGA

Чтобы понять, чего не хватает, сравниваем то, что использует DTS платы, с тем, что
включено в defconfig. Список `compatible` из DTS:

```bash
grep -h -o 'compatible = "[a-z,0-9-]*"' \
    arch/arm64/boot/dts/rockchip/rk3326-odroid-go*.dts* | sort -u
```

Среди них `elida,kd35t133` (панель rev 1.0/1.1), `elida,kd50t048a` (панель Super),
`adc-joystick` (аналоговый стик), `gpio-keys` (кнопки), `rockchip,rk817` (PMIC,
звук, зарядка). Для каждого ищем драйвер и его опцию:

```bash
grep -rn 'elida,kd35t133' drivers/       # → panel-elida-kd35t133.c
grep -n 'kd35t133' drivers/gpu/drm/panel/Makefile   # → CONFIG_DRM_PANEL_ELIDA_KD35T133
grep -E 'ELIDA|JOYSTICK|KEYBOARD_GPIO' arch/arm64/configs/defconfig
```

Выяснилось, что в arm64 `defconfig` нет драйверов обеих панелей и ADC-джойстика,
а DRM Rockchip включён модулем. Отсюда фрагмент:

{{include board/oga/linux/oga.config}}

### Почему дисплей встроен, а не модулем

Если драйверы DRM — модули, они загрузятся только когда init дойдёт до `mdev` и
`modprobe`. До этого экран чёрный, и если что-то пошло не так раньше, вы ничего не
увидите. Встроенный дисплей показывает лог ядра с первых секунд. Для портативной
консоли без UART это ценнее, чем пара мегабайт размера ядра.

### Случай с панелью

После первой сборки `kconfig-check.sh` напечатал:

```text
WARNING: oga.config: requested CONFIG_DRM_PANEL_ELIDA_KD35T133=y, got: ...=m
WARNING: oga.config: requested CONFIG_DRM_PANEL_SITRONIX_ST7701=y, got: ...=m
WARNING: oga.config: requested CONFIG_BACKLIGHT_PWM=y, got: CONFIG_BACKLIGHT_PWM=m
```

Смотрим зависимости:

```text
config DRM_PANEL_ELIDA_KD35T133
	tristate "Elida KD35T133 panel driver"
	depends on OF
	depends on DRM_MIPI_DSI
	depends on BACKLIGHT_CLASS_DEVICE
```

`BACKLIGHT_CLASS_DEVICE=m` в defconfig ограничивает все три опции до `m`. Добавили во
фрагмент `CONFIG_BACKLIGHT_CLASS_DEVICE=y` — и всё встало как надо. Без
`kconfig-check.sh` это всплыло бы только на железе: «почему экран загорается так
поздно?».

## Сборка

```bash
make -C src/linux O=output/oga/linux ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j16 \
     Image modules rockchip/rk3326-odroid-go2.dtb rockchip/rk3326-odroid-go2-v11.dtb \
     rockchip/rk3326-odroid-go3.dtb
make ... INSTALL_MOD_PATH=output/oga/linux-install/modules INSTALL_MOD_STRIP=1 modules_install
```

Результат в `output/oga/linux-install/`:

```text
Image                         ядро
System.map, .config           для отладки и справки
dtbs/rockchip/*.dtb           три dtb
modules/lib/modules/7.2.9-oga/    модули + modules.dep (depmod)
```

`CONFIG_LOCALVERSION="-oga"` делает версию `7.2.9-oga`, а
`# CONFIG_LOCALVERSION_AUTO is not set` убирает автоматический хвост `+` или
`-gXXXXXXX` от git. Версия важна: модули лежат в `/lib/modules/$(uname -r)`, и если
версия собранного ядра не совпадает с каталогом модулей, `modprobe` их не найдёт.

!!! warning "Ловушка: пересборка ядра без пересборки образа"
    Модули попадают в rootfs только в `make image`. Если пересобрали ядро с другими
    опциями, но записали на карту только раздел BOOT, модули в rootfs останутся
    старыми. Самый надёжный путь — `make linux image` и полная перезапись карты.

## Командная строка ядра

```text
rootwait rw console=ttyS2,115200n8 console=tty1 fbcon=rotate:3 consoleblank=0
```

| Параметр | Зачем |
|---|---|
| `root=PARTUUID=...-02` | добавляет `mkimage.sh`: rootfs — второй раздел этого диска |
| `rootwait` | ждать, пока появится устройство (SD инициализируется не мгновенно) |
| `rw` | монтировать сразу на запись |
| `console=ttyS2,...` | лог и консоль на UART |
| `console=tty1` | и на экран |
| `fbcon=rotate:3` | панель OGA физически повёрнута — поворачиваем текстовую консоль на 90° против часовой |
| `consoleblank=0` | не гасить экран по таймауту |

!!! warning "Ловушка: `fbcon=rotate` без поддержки в ядре"
    Параметр `fbcon=rotate:N` работает, только если в ядре включён
    `CONFIG_FRAMEBUFFER_CONSOLE_ROTATION`. В arm64 `defconfig` он выключен, и ядро
    **молча игнорирует** параметр. В первой версии SDK так и было: в командной строке
    стояло `fbcon=rotate:3`, а консоль оставалась в родной портретной ориентации
    панели. Теперь опция включена во фрагменте OGA.

    Значения: 0 — без поворота, 1 — 90° по часовой, 2 — 180°, 3 — 90° против часовой.
    Без параметра fbcon берёт подсказку от DRM: у панели OGA в DTS
    `rotation = <270>`, DRM превращает это в `FB_ROTATE_CW`, то есть `rotate:1`. Но на
    консоли с ней картинка **вверх ногами**: правильная ориентация — `rotate:3`,
    проверено на Black Edition. Поэтому параметр задан явно. Урок: подсказка из
    DTS — это гипотеза, окончательный ответ даёт только железо. Текущий поворот виден
    в `/sys/class/graphics/fbcon/rotate`, и его можно менять на лету:
    `echo 3 > /sys/class/graphics/fbcon/rotate`.

Сообщения ядра идут на все устройства из `console=`, а `/dev/console` — то, куда
пишет и откуда читает init, — это **последний** `console=`. Поэтому порядок имеет
значение: последним ставим UART, чтобы сообщения init и аварийная консоль были там,
куда подключён кабель.

## Устройства ввода

После загрузки кнопки и стик «не реагировали в консоли». При этом лог ядра
говорил, что всё на месте:

```text
input: adc-joystick as /devices/platform/adc-joystick/input/input0
input: gpio-keys as /devices/platform/gpio-keys/input/input1
```

Дело в том, что это **геймпад**: драйвер `gpio-keys` по DTS генерирует коды
`BTN_SOUTH`, `BTN_DPAD_UP` и т. п., а не клавиши клавиатуры. Текстовая консоль
понимает только клавиатуру. Проверка — утилитой `evtest`, которая есть в rootfs:

```bash
evtest /dev/input/event1     # нажимайте кнопки — события печатаются
```

Игры и эмуляторы (SDL и другие) читают `/dev/input/event*` и видят геймпад как есть.

!!! example "Упражнение: уменьшить ядро"
    На работающей OGA выполните `lsmod > /boot/lsmod.txt` (после того как
    погоняли всё железо: звук, зарядку, USB). На ПК:
    `make -C src/linux O=output/oga/linux ARCH=arm64 LSMOD=lsmod.txt localmodconfig`
    отключит все модули, которые не загружены. Затем `make linux-savedefconfig`,
    сохраните результат как `board/oga/linux/oga_defconfig` и укажите
    `LINUX_DEFCONFIG := $(BOARD_DIR)/linux/oga_defconfig`. Сравните размер `Image` и
    модулей до и после.
