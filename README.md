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
configs/<fw>_defconfig        конфиг прошивки: компоненты, их конфиги, разметка образа
board/<board>/u-boot/*.config  фрагменты поверх in-tree defconfig U-Boot
board/<board>/linux/*.config   фрагменты поверх in-tree defconfig ядра
board/<board>/buildroot/defconfig   defconfig Buildroot для платы
board/<board>/boot/            файлы для раздела BOOT (config.txt у RPi)
board/common/buildroot/        общий BR2_EXTERNAL "SDK": свои пакеты, overlay, post-build
board/common/rpi-firmware.sha256    хеши блобов прошивки Raspberry Pi
board/oga/rkbin/               блобы и утилиты Rockchip (BL31, loaderimage, trust_merger)
scripts/mkimage.sh             склейка образа (без root: fakeroot + mke2fs -d + mtools)
scripts/fetch-files.sh         загрузка блобов с проверкой sha256
scripts/rk-legacy-pack.sh      упаковка uboot.img/trust.img для SPI miniloader (OGA)
scripts/flash.sh               запись на SD с проверками
scripts/apps-config.sh         приложения из конфига прошивки (APPS) -> настройки Buildroot
scripts/homm3-install.sh       данные Героев III и моды VCMI (HotA, русский) на раздел GAMES (с ПК или по SSH)
src/                           сабмодули компонентов
dl/                            кэш загрузок (общий для всех прошивок)
```

## Конфиг прошивки

Пути — относительно корня SDK. `*_DEFCONFIG` — имя in-tree defconfig'а или путь к
своему файлу (если в значении есть `/`). `$(IMAGES_DIR)` и `$(LINUX_INSTALL)` указывают
на результаты сборки этой прошивки.

| Переменная | Что задаёт |
|---|---|
| `BOARD_DIR`, `CROSS_COMPILE` | каталог платы, кросс-компилятор для TF-A/U-Boot/ядра |
| `TFA_SRC`, `TFA_PLAT` | TF-A (необязательно) |
| `UBOOT_SRC`, `UBOOT_DEFCONFIG`, `UBOOT_FRAGMENTS` | U-Boot |
| `UBOOT_BL31` | `tf-a` или путь к bl31.elf (необязательно) |
| `UBOOT_IMAGES` | файлы из сборки U-Boot, копируемые в `images/` |
| `BOOTFW_NAME`, `BOOTFW_URL`, `BOOTFW_FILES`, `BOOTFW_HASH` | блобы прошивки (необязательно) |
| `LINUX_SRC`, `LINUX_ARCH`, `LINUX_IMAGE` | ядро: `arm`/`arm64`, `zImage`/`Image` |
| `LINUX_DEFCONFIG`, `LINUX_FRAGMENTS`, `LINUX_DTBS`, `LINUX_CMDLINE` | конфиг, dtb, командная строка |
| `LINUX_PATCHES` | каталог патчей ядра `*.patch` (необязательно): ядро собирается из копии закоммиченного `LINUX_SRC` с патчами в `output/<прошивка>/linux-src`, сам подмодуль не меняется |
| `BUILDROOT_SRC`, `BUILDROOT_EXTERNAL`, `BUILDROOT_DEFCONFIG` | rootfs |
| `APPS` | приложения (пакеты из `apps/`) в rootfs; список — `make apps-list` |
| `APPS_AUTOSTART` | какие из `APPS` запускать при загрузке (init-скрипт `S90<пакет>`) |
| `APPS_CONFIG` | опции приложений: `пакет.ОПЦИЯ=значение`, например `bare-app.DEFCONFIG=oga_defconfig` |
| `IMAGE_RAW` | raw-блобы до 16M: `файл@сектор ...` |
| `IMAGE_BOOT_FILES` | файлы в корень BOOT: `путь[:имя] ...` |
| `IMAGE_DTB_LAYOUT` | dtb в BOOT: `tree` (`vendor/x.dtb`), `flat` (`x.dtb`) или `both` — как U-Boot строит `fdtfile` |
| `IMAGE_BOOT_SIZE_MB`, `IMAGE_ROOTFS_FREE_MB`, `IMAGE_DISK_ID` | размеры, идентификатор MBR |
| `IMAGE_DATA_START_MB` | начало раздела данных `/data` (необязательно, см. ниже) |
| `IMAGE_DATA_SIZE_MB` | размер `/data`; если задан, после него раздел игр `/games` до конца карты |

Приложения из `apps/` включаются только через `APPS`. SDK накладывает их на defconfig
Buildroot платы (`output/<fw>/buildroot/defconfig.sdk`), а `rootfs-savedefconfig`
обратно в defconfig платы их не пишет. Если приложение убрали или поменяли его
автозапуск или опции, SDK удаляет его файлы из `target/` и пересобирает пакет.
Сам Buildroot этого не делает, и выключенный автозапуск остался бы в образе.

`.config` компонента пересоздаётся, когда меняется defconfig-файл или фрагмент;
правки из `menuconfig` живут до этого момента, сохраняйте их через `*-savedefconfig`
или переносите во фрагмент.

## Разметка SD (общая)

```
сектор 0        MBR (disk id IMAGE_DISK_ID)
до 16M          raw-блобы загрузчика (IMAGE_RAW), если плате они нужны
16M             p1 FAT32 BOOT (активный): ядро, dtb, extlinux/extlinux.conf, IMAGE_BOOT_FILES
дальше          p2 ext4 rootfs: rootfs.tar + модули ядра; /boot монтируется по LABEL=BOOT
IMAGE_DATA_START_MB  p3 ext4 data на /data, IMAGE_DATA_SIZE_MB или до конца карты (если задан)
дальше          p4 FAT32 GAMES до конца карты, на /games (если задан IMAGE_DATA_SIZE_MB)
```

Разделов данных в образе нет. Их создаёт при загрузке `/etc/init.d/S05data`: добавляет
p3 от `IMAGE_DATA_START_MB` длиной `IMAGE_DATA_SIZE_MB` (без размера — до конца карты)
и форматирует в ext4 с меткой `data`, затем p4 от конца p3 до конца карты и форматирует
в FAT32 с меткой `GAMES`. `/data` — для того, что пишется на плате: сохранения,
настройки, журналы. `/games` — для файлов игр: карту можно вставить в ПК (Windows,
Linux, macOS видят раздел GAMES) и скопировать игры туда. На плате `/games`
монтируется только для чтения, чтобы выключение питания не оставляло FAT «грязной»;
записать с платы: `mount -o remount,rw /games`.

После `make flash` в таблице разделов снова только p1 и p2; скрипт находит на прежних
местах файловые системы `data` и `GAMES` и подключает их без форматирования, поэтому
содержимое обоих разделов переживает перепрошивку. Раздел с другой файловой системой
скрипт не трогает. rootfs должен кончаться раньше начала p3, это проверяет
`mkimage.sh`. Нужны `sfdisk`, `partx`, `blkid` (util-linux), `mke2fs` (e2fsprogs) и
`mkdosfs` (busybox) в rootfs.

Карту со старой разметкой (p3 `data` до конца карты, без p4) скрипт не переразмечает:
`/data` подключается как раньше, `/games` нет. Перенос: сохранить с платы всё нужное
из `/data` (`ssh root@<адрес> 'tar -cf - -C /data .' > data.tar`), затем на плате
`/etc/init.d/S90bare-app stop; umount /data`,
`dd if=/dev/zero of=/dev/mmcblk0p3 bs=1M count=4`, `sfdisk --delete /dev/mmcblk0 3`,
`partx -d --nr 3 /dev/mmcblk0`, `/etc/init.d/S05data start` и вернуть сохранения и
настройки в `/data`, а файлы игр — на `/games`.

`make flash-boot` пишет `images/boot-area.bin`: от первого raw-блоба (или от 16M)
до конца раздела BOOT. MBR и rootfs не трогаются, поэтому на карте должен быть
образ той же прошивки.

Логин `root` без пароля, getty на последовательном порту и на экране (`tty1`).
На платах с Ethernet (BBB, RPi) поднимается DHCP на `eth0` и есть dropbear;
по SSH пустой пароль не пустит, задайте его через `passwd`.

## ODROID-GO Advance (`oga`)

```
16K..32K        окружение U-Boot (saveenv)
сектор 64       u-boot-rockchip.bin: idbloader (TPL с инициализацией DDR + SPL)
сектор 2048     u-boot.itb (U-Boot + BL31 TF-A + dtb), его грузит SPL
сектор 16384    uboot.img  (тот же U-Boot в формате Rockchip)   } для miniloader
сектор 24576    trust.img  (BL31 rkbin в формате Rockchip)       } из SPI-флеша
```

BootROM RK3326 проверяет SPI-флеш раньше SD. У OGA Black Edition во SPI с завода
стоит recovery-загрузчик Hardkernel (DDR-блоб + miniloader rkbin, лог на 1500000),
поэтому образ гибридный (`RK_LEGACY := y`):

- SPI с заводским загрузчиком: BootROM → SPI miniloader → `trust.img` (BL31 rkbin)
  → `uboot.img` (mainline U-Boot) → Linux;
- SPI пустой: BootROM → TPL → SPL → BL31 (mainline TF-A) → U-Boot → Linux,
  полностью открытая цепочка.

U-Boot определяет ревизию платы по SARADC (`rockchip/rk3326-odroid-go2.dtb`,
`-go2-v11.dtb`, `-go3.dtb`). Консоль `ttyS2`, 115200 начиная с U-Boot
(DDR-блоб и miniloader из SPI печатают на 1500000, CP2102 это не читает).
Таблица разделов — MBR: GPT (сектора 2–33) пересекается с окружением U-Boot на 16K.

### Приложения через UART

`scripts/oga-serial.py` работает с платой через консоль (по умолчанию `/dev/ttyUSB0`,
115200; `-p` или `OGA_PORT`): сеть и дополнительные пакеты на плате не нужны.
Файлы идут по консоли как gzip + base64, примерно 7–10 КБ/с, md5 проверяется.
Нужен только pyserial (`apt install python3-serial`). Если консоль на приглашении
логина, скрипт сам входит как root. Порт открывается эксклюзивно, поэтому сначала
закройте на нём `screen`/`picocom`.

```sh
CC=output/oga/buildroot/host/bin/aarch64-buildroot-linux-gnu-gcc
make -C apps/oga-pad CC=$PWD/$CC

scripts/oga-serial.py sh 'uname -a'                 # команда, её вывод и код возврата
scripts/oga-serial.py push app /usr/bin/app         # файл на плату
scripts/oga-serial.py pull /var/log/messages log    # файл с платы
scripts/oga-serial.py run apps/oga-pad/oga-pad      # в /tmp и запустить (-t секунд, по умолчанию 60)
scripts/oga-serial.py run --bg apps/oga-pad/oga-pad # в фоне, вывод в /tmp/oga-pad.log
scripts/oga-serial.py shot screen.png               # снимок /dev/fb0, повёрнут как видит пользователь
scripts/oga-serial.py key right right a f6          # «нажать» кнопки
```

`key` пишет события в evdev-узел `gpio-keys` (`uinput` в ядре нет), программа видит
их как настоящие нажатия. Кнопки: `up down left right a b x y l r f1`…`f6`
(A = `BTN_EAST`, B = `BTN_SOUTH`). Аналоговый стик (`adc-joystick`) не поддерживается.
`/tmp` на плате — tmpfs: после перезагрузки загруженное пропадает.

### GUI-приложение bare_app

`apps/bare_app` — отдельный репозиторий (сабмодуль): приложение на LVGL с DRM-слоями,
кнопками, стиком, батареей и подсветкой. Устройство и сборка описаны в его
`README.md` и `docs/ARCHITECTURE.md`. В образ OGA оно попадает как приложение
`bare-app` из `APPS` в `configs/oga_defconfig`. Остальное задаётся там же:

```make
APPS           := bare-app oga-pad
APPS_AUTOSTART := bare-app                          # /etc/init.d/S90bare-app, лог /var/log/bare_app.log
APPS_CONFIG    := bare-app.DEFCONFIG=oga_defconfig   # состав: Kconfig приложения, имя из
                                                    # apps/bare_app/configs/ или путь
```

```sh
git submodule update --init --recursive apps/bare_app
make FW=oga rootfs-make BR=bare-app-rebuild   # после правок в исходниках apps/bare_app
apps/bare_app/tools/oga.sh run                # собрать и запустить на плате через UART
```

#### Образ с bare_app и играми: по шагам

1. **Исходники.** bare_app и doomgeneric внутри него — вложенные сабмодули:

   ```sh
   git submodule update --init --recursive
   ```

2. **Хост.** Пакеты из «Быстрого старта»; остальное Buildroot проверит сам. Сборка
   занимает около 21 ГБ в `output/oga` и 2,6 ГБ загрузок в `dl/`. VCMI компилируется
   в 4 потока, примерно по 1 ГБ памяти на поток (`VCMI_JOBS`).

3. **Локальные файлы, которых нет в git** (`.gitignore`):
   - `board/common/buildroot/authorized_keys` — ваш открытый SSH-ключ
     (`cp ~/.ssh/id_ed25519.pub board/common/buildroot/authorized_keys`). У root нет
     пароля, а dropbear пустой не пускает, поэтому без ключа по SSH не войти, а данные
     Героев копируются именно по SSH;
   - `board/oga/buildroot/wifi.conf` — сети для `wpa_supplicant`, если плата должна
     подключиться к Wi-Fi сразу. Без него сеть выбирается в bare_app: «Настройки» → Wi-Fi.

     ```text
     network={
     	ssid="МояСеть"
     	psk="пароль"
     }
     ```

4. **Конфиг.** `make oga_defconfig`. В `configs/oga_defconfig` уже включено всё нужное:
   bare_app с автозапуском, Doom с shareware `doom1.wad` (`bare-app.DOOM_WAD=y`), Герои III
   (`bare-app.HOMM3=y`) и патч ядра для звука (`LINUX_PATCHES`, без него звук играет
   вдвое медленнее).

5. **Сборка.** `make`, без `-j`: компоненты собираются по очереди, потоки внутри каждого
   задаёт `JOBS`. Первая сборка долгая (тулчейн, ядро, VCMI). Результат —
   `output/oga/images/oga.img`.

6. **Запись.** Проверьте, что `make info` показывает `Firmware: oga`, затем
   `make flash DEV=/dev/sdX`.

7. **Первая загрузка.** bare_app запускается сам. `/etc/init.d/S05data` создаёт на остатке
   карты разделы `/data` (1 ГБ, ext4: сохранения, настройки) и `/games` (FAT32 `GAMES`:
   файлы игр), см. «Разметка SD»; оба переживают перепрошивку. Wi-Fi и адрес
   платы — в bare_app: «Настройки» → Wi-Fi; проверка входа: `ssh root@<адрес>`.

8. **Doom** работает сразу: `doom1.wad` уже в образе (`/usr/share/games/doom/`). Свой
   IWAD положите с ПК в каталог `doom` раздела GAMES (`GAMES:/doom/doom2.wad`, на плате
   `/games/doom`). bare_app запускает первый найденный там: `doom2.wad`, `plutonia.wad`,
   `tnt.wad`, `doom.wad`, `freedoom2.wad`, `freedoom1.wad`, `doom1.wad` (регистр имени не
   важен); если там пусто — shareware из образа. Настройки и сохранения Doom лежат в
   `/data/doom` и переживают перепрошивку.

9. **Герои III.** Нужна установка Shadow of Death или Complete (подойдёт и с HotA):
   каталог с `Data` (`H3bitmap.lod`, `H3sprite.lod`, `Heroes3.snd`, `VIDEO.VID`), `Maps`
   и `MP3`. Скрипт скачивает моды в `dl/hota/` и копирует всё в `heroes3/` раздела GAMES:
   на карту, вставленную в ПК, или на плату по SSH:

   ```sh
   scripts/homm3-install.sh ~/games/HoMM3 /media/$USER/GAMES   # карта в ПК
   scripts/homm3-install.sh ~/games/HoMM3 <адрес платы>        # по SSH
   ```

   Можно и вручную, в том числе из Windows: на GAMES нужны `heroes3/Data`, `heroes3/Maps`,
   `heroes3/Mp3` и моды в `heroes3/Mods/<id>` (распакованный архив мода, каталог
   переименован в id: `hota`, `russian-translation`). Все моды в `Mods` включаются сами;
   чтобы выключить мод, удалите его каталог. Всё переживает перепрошивку:

   ```text
   /games/heroes3/Data, Maps, Mp3   файлы игры (раздел GAMES)
   /games/heroes3/Mods              моды: hota, russian-translation
   /data/vcmi/Saves             сохранения: Autosave и слоты Slot01..Slot10
   /data/config/vcmi            настройки VCMI (settings.json, modSettings.json)
   /data/cache/vcmi             журнал VCMI_Client_log.txt
   ```

   Язык игры следует языку bare_app («Настройки» → «Язык»); русский перевод работает,
   когда выбран русский.

10. **Обновление после правок:**

    ```sh
    make rootfs-make BR=bare-app-rebuild && make && make flash DEV=/dev/sdX   # bare_app
    make rootfs-make BR=vcmi-dirclean && make && make flash DEV=/dev/sdX      # патчи VCMI
    make rootfs-make BR=sdl2_mixer-dirclean && make ...                       # патчи sdl2_mixer
    make linux && make && make flash DEV=/dev/sdX                             # патчи ядра
    ```

    Патчи пакета Buildroot накладываются только на свежераспакованные исходники, поэтому
    после их правки нужен `-dirclean`, а не `-rebuild`. bare_app можно проверить и без
    перепрошивки: `apps/bare_app/tools/oga.sh run` (через UART).

#### Doom

В меню bare_app есть пункт «Doom», его включает символ `GAME_DOOM` в Kconfig приложения
(в `oga_defconfig` он включён). Сама игра — отдельная программа `/usr/bin/bare_app_doom`
из `apps/bare_app/ports/doom` (doomgeneric, GPLv2). В `bare_app` она не линкуется,
поэтому GPL на него не распространяется. Игра рисует в видеослой DRM, звуковые эффекты
выводит сама через ALSA, музыки нет.
Shareware `doom1.wad` ставит опция пакета (пакет `doom1-wad`):

```make
APPS_CONFIG := bare-app.DEFCONFIG=oga_defconfig bare-app.DOOM_WAD=y
```

Свой IWAD кладут на раздел GAMES в `doom/` (`GAME_DOOM_GAME`, на плате `/games/doom`):
bare_app берёт первый найденный из `doom2.wad`, `plutonia.wad`, `tnt.wad`, `doom.wad`,
`freedoom2.wad`, `freedoom1.wad`, `doom1.wad`, иначе `GAME_DOOM_WAD` (shareware в
образе). Настройки и сохранения — в `/data/doom` (`GAME_DOOM_DIR` в `oga_defconfig`
bare_app).

### Герои III (VCMI)

`APPS_CONFIG += bare-app.HOMM3=y` (включено в `oga_defconfig`) собирает пакет `vcmi`:
клиент [VCMI](https://vcmi.eu/) 1.7.5 с патчами (`board/common/buildroot/package/vcmi`)
без лаунчера и редактора. Ролики игры (Bink, Smacker) показывает ffmpeg, собранный
только с этими декодерами; SDL2_mixer получает свои патчи из `package/vcmi/sdl2_mixer/`.
В меню bare_app появляется пункт «Герои III». Данные игры в образ
не входят. Их копирует скрипт в `heroes3/` раздела GAMES, вместе с модами VCMI, которые
он один раз скачивает в `dl/hota/`:

```sh
scripts/homm3-install.sh ~/games/HoMM3 /media/$USER/GAMES  # карта в ПК; каталог с Data, Maps, MP3
scripts/homm3-install.sh ~/games/HoMM3 192.168.50.61       # на плату по SSH
```

Подойдёт установка Shadow of Death или Complete (в том числе с HotA). Копируются
только файлы, которые читает VCMI (около 330 МБ). bare_app передаёт VCMI каталог игры
`/games/heroes3` (`GAME_HOMM3_GAME`) и каталог данных `/data` (`GAME_HOMM3_DATA`:
сохранения, настройки, журналы). Под bare_app VCMI включает все моды из `Mods` (патч
0006), выключить мод — удалить его каталог. Моды:

- `hota` — Horn of the Abyss для VCMI (около 520 МБ, `--no-hota` без него);
- `russian-translation` — русский перевод оригинальной игры с русскими шрифтами
  (около 70 МБ, `--no-rus` без него). Работает, только когда язык VCMI русский, то
  есть когда русский выбран в bare_app; с HotA заодно включает русские кнопки её
  главного меню.

Повторный запуск копирует файлы заново и заменяет каталоги модов; настройки модов
VCMI остаются в `/data/config/vcmi`.
Сборка VCMI тяжёлая: компилируется в 4 потока (`VCMI_JOBS`), примерно по 1 ГБ памяти
на поток.

## BeagleBone Black (`bbb`)

ROM AM335x грузит `MLO` (U-Boot SPL) с первого активного FAT-раздела, SPL — `u-boot.img`
оттуда же. U-Boot читает модель из EEPROM платы (`am335x-boneblack.dtb` и др.).
Консоль `ttyS0`, 115200 (разъём J1).

BBB грузится сначала с eMMC: чтобы загрузиться с SD, держите кнопку S2 (у слота SD)
при включении питания, либо сотрите загрузчик на eMMC.

## Raspberry Pi 1 (`rpi1`) и 4 / 400 (`rpi4`)

Raspberry Pi не читает raw-сектора: закрытая прошивка GPU (`bootcode.bin`/`start.elf`
у Pi 1, EEPROM + `start4.elf` у Pi 4/400) читает `config.txt` с раздела BOOT и
запускает mainline U-Boot (`kernel=u-boot.bin`). Блобы скачиваются с
github.com/raspberrypi/firmware (тег из `BOOTFW_URL`) и проверяются по
`board/common/rpi-firmware.sha256`.

U-Boot на Pi обязательно нужен device tree от прошивки. Прошивка ищет dtb по своим
именам: у Pi 4/400 они совпадают с mainline (`bcm2711-rpi-400.dtb`, поэтому dtb лежат
и в корне BOOT), у Pi 1 — нет (`bcm2708-rpi-*.dtb`), поэтому mainline dtb скопированы
и под этими именами. Ядру U-Boot отдаёт mainline dtb по модели платы.

Консоль: Pi 1 — `ttyAMA0`, Pi 4/400 — mini-UART `ttyS1` (GPIO14/15), 115200;
у Pi 400 основная консоль — HDMI + встроенная клавиатура.

## Свои изменения в компонентах

```sh
cd src/linux
git checkout oga && git commit ...                    # работа в ветке oga
git remote add mine git@github.com:<you>/linux.git && git push mine oga
cd ../.. && git config -f .gitmodules submodule.src/linux.url git@github.com:<you>/linux.git
git add .gitmodules src/linux && git commit           # SDK пинует новый коммит
```
