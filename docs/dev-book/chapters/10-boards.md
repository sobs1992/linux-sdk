# Особенности плат: сводка для разработчика

## Сравнение

| | OGA | BBB | RPi 1 | RPi 4 / 400 |
|---|---|---|---|---|
| CPU | 4 × Cortex-A35, arm64 | 1 × Cortex-A8, arm | 1 × ARM1176, armv6 | 4 × Cortex-A72, arm64 |
| Тулчейн программ | `aarch64-buildroot-linux-gnu-` | `arm-buildroot-linux-gnueabihf-` (A8) | `arm-buildroot-linux-gnueabihf-` (ARMv6) | `aarch64-buildroot-linux-gnu-` |
| Ядро / vermagic | `Image`, SMP preempt | `zImage`, SMP, modversions, ARMv6 | `zImage`, ARMv6, без SMP | `Image`, SMP preempt |
| Консоль | `ttyS2` | `ttyS0` (J1) | `ttyAMA0` | `ttyS1` (mini-UART) |
| Сеть | нет (USB-Ethernet) | Ethernet | Ethernet на USB (B/B+) | Ethernet |
| Загрузка по сети | нет | да | да (`usb start`) | да |
| Окружение U-Boot | MMC, 16 КиБ | `uboot.env` на FAT | `uboot.env` на FAT | `uboot.env` на FAT |
| `__symbols__` в dtb | нет (`DTC_FLAGS=-@`) | есть | есть | есть |
| `fdtoverlay_addr_r` | есть | есть | нет | нет |
| `/proc/config.gz` | есть | есть | нет | есть |
| Dynamic debug | нет | нет | есть | нет |

## ODROID-GO Advance

- **Загрузчик.** С заводским SPI работает только U-Boot proper из `uboot.img`;
  TPL/SPL не запускаются (глава 9). Правки в SPL проверяйте, только если стёрли SPI.
- **Экран** повёрнут: framebuffer в родной (портретной) ориентации панели, консоль
  повёрнута `fbcon=rotate:3` (нужен `CONFIG_FRAMEBUFFER_CONSOLE_ROTATION`, он включён
  во фрагменте OGA). Учитывайте это в графике (пример `oga-pad`).
- **Ввод**: `gpio-keys` (D-pad, A/B/X/Y, F1–F6, курки), `adc-joystick` (стик, `ABS_X/Y`),
  `rk805 pwrkey` (кнопка питания).
- **Разъём P2**: UART1 (`ttyS1`, контакты 2 — RXD, 3 — TXD; 4, 5 — CTS, RTS) и I2C1
  (контакты 7 — SCL, 8 — SDA, 400 кГц). Свободных GPIO нет.
- **Звук** — кодек PMIC RK817, модулем; **зарядка** — `CHARGER_RK817`, модулем
  (`/sys/class/power_supply/`).
- **Светодиоды** — `blue:status` (PWM) и `red:charging`.
- **Wi-Fi** (только Black Edition): ESP8089 на SDIO. Драйвера в mainline нет, он
  собирается внешним модулем из `board/oga/linux/esp8089` (`LINUX_EXT_MODULES`),
  прошивка — пакет `esp8089-firmware`. Настройка и запуск — глава 2. У rev 1.0 сети
  нет: USB-Ethernet адаптер (драйверы RTL8152, AX88179, CDC модулями), UART (`lrzsz`)
  или картридер.
- **Overlay**: в dtb SDK нет `__symbols__`, нужен `LINUX_MAKE_ARGS := DTC_FLAGS=-@`.
- **USB OTG**: контроллер DWC2 включён в двухрежимной конфигурации, configfs-гаджеты
  (ECM, NCM, ACM) собраны модулями. Работает ли гаджет через разъём OGA, не проверено.

## BeagleBone Black

- **Порядок загрузки**: eMMC раньше SD. Для загрузки с SD держите S2 при включении
  питания (или сотрите загрузчик на eMMC).
- **U-Boot** — файлы `MLO` и `u-boot.img` на FAT. Обновлять можно просто копированием.
- **Pinmux**: почти все выводы P8/P9 многофункциональные. Чтобы вывод стал GPIO, I2C,
  UART или PWM, нужен узел pinctrl в device tree (пример — overlay для P9_12).
- **GPIO**: четыре банка по 32 линии (`GPIO1_28` = банк 1, линия 28). Номер
  `/dev/gpiochipN` не обязан совпадать с номером банка — сверяйтесь с `gpiodetect`.
- **Ядро** из `omap2plus_defconfig`: базовая архитектура ARMv6 (ради старых OMAP2) и
  `MODVERSIONS`. Модули — строго от того же ядра.
- **HDMI** — tilcdc + TDA998x, модулями.
- **USB**: порт USB0 (mini-USB) — OTG на контроллере MUSB (модулем), configfs-гаджеты
  собраны: можно сделать сеть по USB-кабелю.
- **PRU** (два 200-МГц микроконтроллера реального времени) в этой книге не
  рассматриваются: для них нужен отдельный тулчейн и `remoteproc`.

## Raspberry Pi 1 / Zero

- **ARMv6, одно ядро.** Тулчейн RPi 1 не взаимозаменяем с тулчейном BBB, хотя префикс
  одинаковый.
- **Загрузка**: прошивка GPU → `u-boot.bin` → extlinux. Прошивке нужен dtb со «старым»
  именем `bcm2708-rpi-*.dtb`; SDK кладёт копии mainline dtb под этими именами.
- **Ethernet** (только B/B+) висит на USB: в U-Boot сначала `usb start`, в ядре драйвер
  `USB_NET_SMSC95XX` встроен (годится для NFS-корня).
- **Overlay** U-Boot применяет (нужен `fdtoverlay_addr_r`); в самом ядре
  `CONFIG_OF_OVERLAY` выключен — во время работы overlay не загрузить.
- **Отладка**: `DYNAMIC_DEBUG` включён, `/proc/config.gz` — нет.
- **Zero / Zero W**: USB OTG (DWC2) — можно сделать USB-гаджет (`USB_ETH` модулем).
- **GPIO17** — контакт 11 гребёнки; GPIO-контроллер — `/dev/gpiochip0`.

## Raspberry Pi 4 / 400

- **Загрузка**: EEPROM → `start4.elf` (читает `config.txt`) → `u-boot.bin` (64 бита,
  `arm_64bit=1`) → extlinux. Прошивке нужен `bcm2711-rpi-*.dtb` в корне BOOT, U-Boot —
  в `broadcom/` (`IMAGE_DTB_LAYOUT := both`).
- **Консоль на GPIO14/15** — mini-UART (`ttyS1`): его частота зависит от частоты ядра
  VideoCore, поэтому в `config.txt` стоит `enable_uart=1`.
- **Pi 400**: светодиода ACT нет (удалён в DTS), только PWR. Клавиатура — USB через
  контроллер VL805 на PCIe; PCIe, xHCI и HID встроены в ядро фрагментом SDK, чтобы
  клавиатура работала на `tty1` сразу.
- **Память U-Boot**: ядро грузится с `0x80000`, следующая занятая область —
  `scriptaddr=0x05400000`, то есть под `Image` около 83 МиБ (сейчас он ≈ 41 МиБ).
- **Overlay**: задайте `fdtoverlay_addr_r` (глава 8).
- **NFS-корень**: GENET и PHY встроены фрагментом SDK — можно грузиться по сети.
- **HDMI-звук** — через VC4 (встроен).
