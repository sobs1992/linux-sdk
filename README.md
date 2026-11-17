# OdroidLinux SDK

SDK для ARM-плат на mainline-компонентах:

| Компонент | Каталог | Версия | Upstream |
|---|---|---|---|
| TF-A (BL31) | `src/tf-a` | v2.15.0 | github.com/ARM-software/arm-trusted-firmware |
| U-Boot | `src/u-boot` | v2026.07 | source.denx.de/u-boot/u-boot |
| Linux | `src/linux` | v7.2.9 | git.kernel.org stable |
| Buildroot | `src/buildroot` | 2026.08 | gitlab.com/buildroot.org/buildroot |

Каждый компонент — отдельный git-сабмодуль (локальная ветка `oga`), собирается
отдельно и out-of-tree в `output/<прошивка>/`, исходники не загрязняются.
Исходники общие для всех плат, различаются только конфиги.

## Платы

| Прошивка | Плата | SoC | Загрузка |
|---|---|---|---|
| `oga` | ODROID-GO Advance / Black Edition / Super | RK3326, A35, arm64 | idbloader + u-boot.itb (+ RK legacy для SPI) |
| `ogu` | ODROID-GO Ultra | S922X, A73 + A53, arm64 | FIP (BL2/BL31 Amlogic + mainline U-Boot) с сектора 1 SD |
| `bbb` | BeagleBone Black / Green (+ Wireless) | AM335x, A8, armhf | ROM → MLO → u-boot.img с FAT |
| `rpi1` | Raspberry Pi 1 A/A+/B/B+, Zero, Zero W, CM1 | BCM2835, ARM1176, armhf | GPU firmware → U-Boot |
| `rpi4` | Raspberry Pi 4 B, Raspberry Pi 400, CM4 | BCM2711, A72, arm64 | EEPROM + GPU firmware → U-Boot |

Везде дальше одинаково: U-Boot сам выбирает dtb по модели платы и грузит
`extlinux/extlinux.conf` с раздела BOOT, ядро монтирует rootfs по
`root=PARTUUID=<disk id>-02`.

## Быстрый старт

```sh
sudo apt install mtools gcc-aarch64-linux-gnu gcc-arm-linux-gnueabihf
make rpi4_defconfig              # выбрать прошивку configs/rpi4_defconfig
make                             # все компоненты + образ
make flash DEV=/dev/sdX          # записать output/rpi4/images/rpi4.img на SD
```

Отдельные компоненты:

```sh
make uboot            # (TF-A +) U-Boot  -> images/
make bootfw           # блобы прошивки (RPi) -> images/
make linux            # ядро, dtbs, модули -> output/<fw>/linux-install/
make rootfs           # Buildroot        -> images/rootfs.tar
make image            # только склейка .img из уже собранного
make flash-boot DEV=/dev/sdX    # перезаписать загрузчик и раздел BOOT, rootfs не трогать
make FW=bbb linux     # собрать для другой прошивки, не меняя выбранную
make help             # все цели
```

Для каждого компонента есть `-menuconfig`, `-savedefconfig`, `-configure`, `-clean`
(`uboot-`, `linux-`, `rootfs-`). `make rootfs-make BR=busybox-menuconfig` вызывает
любую цель Buildroot, `make rootfs-sdk` собирает кросс-тулчейн с sysroot для приложений.

## Выбор прошивки

`make <fw>_defconfig` записывает имя прошивки в файл `output/.fw`. Все последующие
команды без `FW=` берут прошивку оттуда: подключают `configs/<fw>_defconfig` и работают
с каталогом `output/<fw>/`. Поэтому `make flash` пишет образ **выбранной** прошивки.

`FW=<fw>` в командной строке действует только на эту команду и выбор в `output/.fw`
не меняет. У каждой прошивки свой каталог, образы разных плат лежат рядом:

```text
output/oga/images/oga.img
output/ogu/images/ogu.img  (и ogu-emmc.img для eMMC)
output/bbb/images/bbb.img
output/rpi1/images/rpi1.img
output/rpi4/images/rpi4.img
```

```sh
make info                                       # какая прошивка выбрана (строка Firmware:)
make FW=rpi4 flash DEV=/dev/sdX                 # записать rpi4 разово, выбор не меняется
make rpi4_defconfig && make flash DEV=/dev/sdX  # переключиться на rpi4 насовсем
```

Перед `make flash` проверяйте `make info`, чтобы не записать на карту образ другой платы.

## Структура

```
Makefile                      оркестратор: цели сборки, умолчания конфигов, склейка образа
configs/<fw>_defconfig        конфиг прошивки: компоненты, их конфиги, приложения, разметка образа
board/<board>/u-boot/*.config  фрагменты поверх in-tree defconfig U-Boot
board/<board>/u-boot/patches/  патчи U-Boot платы (UBOOT_PATCHES)
board/<board>/linux/*.config   фрагменты поверх in-tree defconfig ядра
board/<board>/linux/patches/   патчи ядра платы (LINUX_PATCHES)
board/<board>/linux/<module>/  внешние модули ядра (LINUX_EXT_MODULES: esp8089, rk-vepu-h264, meson-venc)
board/<board>/buildroot/       defconfig Buildroot платы, её overlay, post-build.sh
board/<board>/boot/            файлы для раздела BOOT (config.txt у RPi, boot.ini у GO Ultra)
board/<board>/fip/, rkbin/     хеши блобов Amlogic (GO Ultra); блобы и утилиты Rockchip (OGA)
board/common/buildroot/        общий BR2_EXTERNAL "SDK": пакеты (package/), overlay, post-build
board/common/buildroot/package/<pkg>/   пакет: .mk, Config.in, .hash, патчи, его game.ini
board/common/rpi-firmware.sha256    хеши блобов прошивки Raspberry Pi
apps/bare_app/                 GUI-приложение bare_app (сабмодуль, свой README и docs/)
apps/oga-pad/                  пример приложения
games/                         манифест игр карты GO Ultra, их wine.ini и правки (games/README.md)
scripts/mkimage.sh             склейка образа (без root: fakeroot + mke2fs -d + mtools)
scripts/flash.sh               запись на SD с проверками
scripts/fetch-files.sh         загрузка блобов с проверкой sha256
scripts/kconfig-check.sh       предупреждения о строках фрагмента, не попавших в .config
scripts/apps-config.sh         приложения из конфига прошивки (APPS) -> настройки Buildroot, чистка target/
scripts/rk-legacy-pack.sh      упаковка uboot.img/trust.img для SPI miniloader (OGA)
scripts/amlogic-fip.sh         сборка FIP из блобов Amlogic и U-Boot (GO Ultra)
scripts/usb-disk.sh            найти eMMC, показанную U-Boot как USB-диск (make flash-emmc)
scripts/homm3-install.sh       данные Героев III и моды VCMI (HotA, русский) на раздел GAMES (с ПК или по SSH)
scripts/halflife-install.sh    файлы Half-Life (valve, valve_russian) на раздел GAMES (с ПК или по SSH)
scripts/games-image.py         карта игр или полный образ с играми по манифесту (games/games.manifest)
scripts/game_pictures.py       обложки игр из .lod/.wad/.exe/.bik (для games-image.py)
scripts/devlib.py              общее для инструментов плат: пути output/, коды кнопок, события, PNG
scripts/oga-serial.py          плата по UART: команды, файлы, кнопки, снимок (GO Advance)
scripts/ogu-ctl.py             плата по ssh: кнопки, снимок, запуск игры, клики (GO Ultra)
scripts/doom3-test.py          автоматический прогон DOOM 3 BFG на GO Ultra
scripts/ogu-hold.c             удержание кнопок на плате (вспомогательная программа)
docs/                          документация (ниже), книги (book, dev-book, check-book) и их PDF
src/                           сабмодули компонентов
dl/                            кэш загрузок (общий для всех прошивок)
lab/                           ссылка на данные проекта вне git (игры, образы), см. games/README.md
output/<fw>/                   результаты сборки прошивки
```

## Документация

| Файл | О чём |
|---|---|
| [docs/config.md](docs/config.md) | переменные конфига прошивки, приложения `APPS` |
| [docs/sd-layout.md](docs/sd-layout.md) | разметка карты, разделы `/data` и `/games`, карта игр, USB-диск |
| [docs/adding-a-board.md](docs/adding-a-board.md) | как добавить плату: чек-лист файлов |
| [docs/adding-a-game.md](docs/adding-a-game.md) | как добавить игру или программу: три пути и где что лежит |
| [docs/patches.md](docs/patches.md) | где лежат патчи ядра, U-Boot и пакетов, как их менять и что пересобирается |
| [docs/boards/oga.md](docs/boards/oga.md) | ODROID-GO Advance: загрузка, быстрая загрузка, кодер H.264, UART, bare_app, Doom, Герои III |
| [docs/boards/ogu.md](docs/boards/ogu.md) | ODROID-GO Ultra: FIP, eMMC, карта игр exFAT, быстрая загрузка, гибернация, часы, USB-сеть, Half-Life, RTCW |
| [docs/boards/bbb-rpi.md](docs/boards/bbb-rpi.md) | BeagleBone Black, Raspberry Pi 1 и 4 |
| [docs/architecture-review-2026-11-16.md](docs/architecture-review-2026-11-16.md) | обзор архитектуры и журнал переделок ноября 2026 |
| [docs/wiki/Home.md](docs/wiki/Home.md) | вики: устройство проекта со схемами и снимками экрана, как добавить игру, нюансы, инструменты; HTML — `docs/wiki/build-html.py` → `docs/wiki/html/` |
| [apps/bare_app/README.md](apps/bare_app/README.md), [docs/ARCHITECTURE.md](apps/bare_app/docs/ARCHITECTURE.md), [docs/GAMES.md](apps/bare_app/docs/GAMES.md) | bare_app: что умеет, как устроено, как добавить игру в приложение |
| [games/README.md](games/README.md) | карта игр GO Ultra, манифест, данные проекта в `lab/` |
| `docs/book`, `docs/dev-book`, `docs/check-book` | книги: как SDK устроен, разработка на нём, проверка плат (`docs/book/build.py` собирает PDF) |

Как собрать первую прошивку — «Быстрый старт» выше; сборка идёт по компонентам,
`make help` перечисляет цели.
