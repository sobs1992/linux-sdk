# 7. Инструменты

Все скрипты лежат в `scripts/`; общее для них — `scripts/devlib.py` (пути
`output/`, коды кнопок обеих плат, события evdev, PNG).

## Игры на карту: `games-image.py`

```sh
scripts/games-image.py --card /media/$USER/GAMES --board root@192.168.7.2   # все игры манифеста
scripts/games-image.py --card /media/$USER/GAMES --reuse --games pop        # одну заново
scripts/games-image.py --card /media/$USER/GAMES --reuse                    # только сверить
scripts/games-image.py --card … --delete                                     # убрать лишнее в каталогах игр
scripts/games-image.py -m МАНИФЕСТ [--only sd|emmc]                          # полный образ (GO Advance)
```

Что делает — [5. Добавление игры](05-Adding-a-Game.md#манифест-и-карта-как-это-работает).
Нужны `rsync`, Python 3 с PIL, для обложек из роликов — `ffmpeg`, для `prepare.sh`
отдельных игр — `unrar`, `llvm-mingw` из `output/ogu/buildroot/host`.
Сопутствующие: `game_pictures.py` (картинки из `.lod`/`.wad`/`.exe`/`.bik`),
`homm3-install.sh`, `halflife-install.sh` (только нужные движку файлы, на карту
или по ssh).

## GO Ultra по сети: `ogu-ctl.py`

Работает по USB-сети (`192.168.7.2`; другая приставка — `OGU_HOST=192.168.8.2`,
см. `/etc/units` в [загрузке и диске](02-Boot-and-Disk.md)). Шаги выполняются по
порядку одним заходом на плате:

```sh
scripts/ogu-ctl.py shot:screen.png              # снимок всех слоёв (SIGUSR1 bare_app)
scripts/ogu-ctl.py a wait:2000 down a           # кнопки: up down left right a b x y l r l2 r2 f1..f6; NAME:MS — удержание
scripts/ogu-ctl.py stick:1,0.5,800 shot:s.png   # левый стик X,Y (−1..1) на 800 мс; rstick: — правый
scripts/ogu-ctl.py launch:monkey2 wait:30000 shot:m.png   # игра без меню: имя каталога, название или ключ
scripts/ogu-ctl.py wfmove:238,188 wclick        # курсор Windows-игры в пиксель снимка, клик (wclick:right)
scripts/ogu-ctl.py wkey:ctrl+s wkey:esc         # клавиша Windows-игре именами из [keys]
scripts/ogu-ctl.py quit-game                    # закрыть игру (в т. ч. свёрнутую)
```

Имя для `launch:` — имя каталога игры на `/games` (Wine-игры: `monkey2`, `pop`),
её название (`'launch:DOOM 3 BFG Edition'`, одним аргументом) или id из
`game_def` для игр со своим движком: Герои III — `homm3`, не `heroes3`
(так называется их каталог данных); Doom — `doom`, Half-Life — `halflife`.
Неверное имя — строка `ctl: launch …: no such game` в журнале.

Кнопки пишутся в evdev `gpio-keys`, так что bare_app и игра видят их как
настоящие; стики требуют `scripts/ogu-hold.c` на плате (скрипт сам собирает и
копирует в `/tmp`). `launch`, `quit-game` и `w…` — строки в FIFO
`/tmp/bare_app.ctl` и `/tmp/bare_app_wine.ctl`: курсор встаёт точно, без стика.
Удержание кнопки программно на GO Ultra ограничено (монитор системы открывают
`BARE_APP_SYSMON=full` в окружении).

Автоматический прогон DOOM 3 — `scripts/doom3-test.py` (suite 9/9 PASS в последнем
состоянии).

## GO Advance по UART: `oga-serial.py`

Сеть и пакеты на плате не нужны: консоль `/dev/ttyUSB0`, 115200 (`-p` или
`OGA_PORT`), файлы идут gzip+base64 на 7–10 КБ/с с проверкой md5. Нужен только
pyserial. Порт открывается эксклюзивно — закройте `screen`/`picocom`.

```sh
scripts/oga-serial.py sh 'uname -a'
scripts/oga-serial.py push app /usr/bin/app
scripts/oga-serial.py pull /var/log/bare_app.log log
scripts/oga-serial.py run --bg apps/oga-pad/oga-pad
scripts/oga-serial.py shot screen.png
scripts/oga-serial.py key right right a f6
```

`apps/bare_app/tools/oga.sh run|key|shot|stop` — обёртка для разработки
лаунчера: собирает кросс-тулчейном, копирует изменившиеся бинарники в `/tmp`
платы, запускает. `/tmp` на плате — tmpfs.

## Прошивка и диски

| Команда | Что |
|---|---|
| `make flash DEV=/dev/sdX` | весь образ выбранной прошивки (`make info`!) |
| `make flash-boot DEV=…` | только загрузчик и BOOT, rootfs и данные остаются |
| `make flash-emmc` / `flash-emmc-boot` | eMMC GO Ultra через USB (Vol+ при включении); диск находится по USB-id гаджета U-Boot |
| `make FW=oga flash IMAGE_FILE=lab/images/oga-games.img DEV=…` | образ с играми |
| `usb-disk start|status|stop` (на плате) | раздел игр компьютеру по USB |
| `games-mount rw|ro|devices|stop` (на плате) | запись на карту с платы |

Перед записью загрузчика — бэкап: первые 16 МиБ eMMC (заводской загрузчик GO
Ultra возвращается из них), FIP, `/data`. Всё это уже лежит в `lab/backups/ogu/`.

## Симулятор на ПК

```sh
cd apps/bare_app && cmake -S . -B build-host && cmake --build build-host -j
cd build-host && ctest                      # юнит-тесты, game_smoke с tests/fake_game.c
./bare_app                                  # окно SDL
echo "wait:800 down a wait:3000 f6" | BARE_APP_SHOT=/tmp/s.ppm ./bare_app -p pc-mem
BARE_APP_SIZE=854x480 BARE_APP_SIM_BATTERY=/tmp/bat BARE_APP_SIM_DEVICES=7 ./bare_app -p pc-mem
tools/ppm2png.py /tmp/s.ppm /tmp/s.png
```

Для SDL2-игр на ПК нужен SDL2 2.32 с патчем SDK (`configure --enable-bareapp`) и
`BARE_APP_NATIVE_DIRS`; для Doom — `BARE_APP_DOOM_WAD`; для Half-Life — движок с
`--enable-bare-app` и `BARE_APP_HALFLIFE_*`.

## Что смотреть при проблемах

| Признак | Где искать |
|---|---|
| игры нет в меню | ini не там, нет `exe`; журнал: `native: …: no exe` |
| «Не найдено: путь» | `needs`/`missing()` |
| стартует и закрывается | `/data/logs/<игра>/1.log` — stdout/stderr игры и Wine, код выхода, сообщения ядра |
| чёрный экран, «Загрузка…» | другой видеодрайвер; `SDL_LOGGING = video=debug` |
| рывки | монитор F5 (удерживать): график времени кадра, CPU по кластерам, диск; `BARE_APP_FRAME_STATS=1` в лог |
| Wine | `WINEBARE_FPS=1` — fps и стопы; `WINEDEBUG` как обычно |
| что реально на панели | `/sys/kernel/debug/dri/0/state` (снимок — буферы приложения, не панель) |
| U-Boot встал | шаги печатаются на экран и UART (`Boot 1: mmc0 …`); сторожевой таймер сбросит через 60 с |
