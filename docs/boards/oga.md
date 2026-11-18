# ODROID-GO Advance (`oga`)

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

## Быстрая загрузка

От кнопки до меню bare_app около 5 с (было 14.7): загрузчики 2.6 с, ядро 1.3 с,
init 1.0 с, bare_app 0.2 с. Время меряется по счётчику таймера ARM, который идёт
с включения: `cntvct_el0 / 24 МГц` минус время ядра — это загрузчики.

- U-Boot: `CONFIG_BOOTDELAY=0` (2 с ожидания клавиши). Остановить его: держать
  Enter в UART с момента включения.
- Ядро (`board/oga/linux/oga.config`): только платформа Rockchip, без ACPI, UEFI,
  PCI, MTD и т. п. — Image 22.6 МБ вместо 42.6, U-Boot читает его с карты на ~17 МБ/с;
  `quiet` (синхронная консоль 115200 стоила ~2 с). Звук, кнопка питания и батарея
  RK817 встроены, а не модулями.
- init: модули загружаются в фоне (`S03mdev` вместо `S10mdev`, который ждал
  драйвер Wi-Fi 3–4 с), bare_app стартует сразу после `S05data` (`S06bare-app`).

## Аппаратный кодер H.264

Трансляция bare_app кодирует H.264 на VPU PX30 через свой драйвер
`board/oga/linux/rk-vepu-h264` (V4L2 mem2mem, `/dev/video0`; подробности — в его
README). Hantro в ядре выключен: он берёт тот же узел VPU, а его JPEG-кодер и
декодеры здесь не нужны. Кадр 960×640 кодируется за 8–9 мс; стрим Heroes III
в этом размере идёт на 30 кадрах/с при ~10% CPU (OpenH264 давал 19 кадров/с
при ~35%). `BARE_APP_STREAM_SW=1` возвращает программный кодер.

## Часы

Время хранит RTC в PMIC RK817 (`rk808-rtc`, встроен в ядро), он идёт от батареи и точен
(120 с за 120 с, в отличие от RK817 на GO Ultra без кварца). Ядро берёт время из него при
загрузке (`rtc0`). Выставляет его bare_app: «Настройки → Система → Дата и время» через
`/usr/sbin/rtc-clock set "YYYY-MM-DD hh:mm"` (`board/oga/buildroot/rootfs-overlay`);
пояса нет, хранится показываемое время как UTC. Пока время не выставлено (после замены
батареи — 2017 год), часы в строке статуса не показываются.

## Приложения через UART

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

## GUI-приложение bare_app

`apps/bare_app` — отдельный репозиторий (сабмодуль): приложение на LVGL с DRM-слоями,
кнопками, стиком, батареей и подсветкой. Устройство и сборка описаны в его
`README.md` и `docs/ARCHITECTURE.md`. В образ OGA оно попадает как приложение
`bare-app` из `APPS` в `configs/oga_defconfig`. Остальное задаётся там же:

```make
APPS           := bare-app oga-pad
APPS_AUTOSTART := bare-app                          # /etc/init.d/S90bare-app (GO Advance: S06), лог /var/log/bare_app.log
APPS_CONFIG    := bare-app.DEFCONFIG=oga_defconfig   # состав: Kconfig приложения, имя из
                                                    # apps/bare_app/configs/ или путь
```

```sh
git submodule update --init --recursive apps/bare_app
make FW=oga rootfs-make BR=bare-app-rebuild   # после правок в исходниках apps/bare_app
apps/bare_app/tools/oga.sh run                # собрать и запустить на плате через UART
```

### Образ с bare_app и играми: по шагам

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
   (`bare-app.HOMM3=y`) и патчи ядра платы (`LINUX_PATCHES`, `board/oga/linux/patches`:
   делители I2S — без этого звук играет вдвое медленнее, перезагрузка через RK817, опрос
   стика раз в 10 мс).

5. **Сборка.** `make`, без `-j`: компоненты собираются по очереди, потоки внутри каждого
   задаёт `JOBS`. Первая сборка долгая (тулчейн, ядро, VCMI). Результат —
   `output/oga/images/oga.img`.

6. **Запись.** Проверьте, что `make info` показывает `Firmware: oga`, затем
   `make flash DEV=/dev/sdX`.

7. **Первая загрузка.** bare_app запускается сам. `/etc/init.d/S05data` создаёт на остатке
   карты разделы `/data` (1 ГБ, ext4: сохранения, настройки) и `/games` (FAT32 `GAMES`:
   файлы игр), см. [sd-layout.md](../sd-layout.md); оба переживают перепрошивку. Wi-Fi и адрес
   платы — в bare_app: «Настройки» → Wi-Fi; проверка входа: `ssh root@<адрес>`.

8. **Doom** работает сразу: `doom1.wad` уже в образе (`/usr/share/games/doom/`). Свой
   IWAD положите с ПК в каталог `doom` раздела GAMES (`GAMES:/doom/doom2.wad`, на плате
   `/games/doom`). bare_app запускает первый найденный там (порядок имён — в разделе
   «Doom» ниже); если там пусто — shareware из образа. Настройки и сохранения Doom лежат в
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

### Doom

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

## Герои III (VCMI)

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
