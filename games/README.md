# Игры: карта GO Ultra и образ

`scripts/games-image.py` раскладывает игры манифеста `games/games.manifest` по
каталогам `/games`: на карту игр или в полный образ.

## Карта игр (GO Ultra)

У GO Ultra игры лежат на SD-карте с разделом exFAT `GAMES` (README, «Игры: SD-карта
(exFAT)»). `--card` кладёт их на смонтированную карту: карта вставлена в ПК или
открыта приставкой по USB-C (bare_app, «USB-диск»):

```sh
scripts/games-image.py --card /media/$USER/GAMES --board root@192.168.7.2   # все игры
scripts/games-image.py --card /media/$USER/GAMES --reuse --games pirates    # одна заново
scripts/games-image.py --card /media/$USER/GAMES --reuse                    # только сверить
```

Игры сначала собираются в `<work>/games` (`work` манифеста, на диске с местом), потом
`rsync -rt` переносит на карту то, что изменилось по размеру или времени. Поэтому
повторный запуск с `--reuse` быстрый. Без `--reuse` `<work>` собирается заново. Каталоги
на карте, которых нет в манифесте, не трогаются. Лишние файлы в каталоге игры
остаются; `--delete` их удаляет, в том числе положенные туда руками. Перед
копированием скрипт сверяет, хватит ли места.

Файлы строк `data` (шрифты Daemonica в префиксе Wine) должны лежать на `/data` платы,
не на карте: `--board ХОСТ` копирует их по SSH (`tar` от root). Без `--board` скрипт
только говорит, где они лежат (`<work>/data`).

## Полный образ (GO Advance)

Без `--card` получается образ для прошивки, у которой раздел игр стоит на её же диске
(`IMAGE_DATA_SIZE_MB`, у GO Advance — SD-карта). Скрипт берёт образы прошивки
(`make FW=<fw> image`) и дописывает в них разделы данных, которые иначе создаёт при
первой загрузке `/etc/init.d/S05data`:

| Раздел | Где | Что |
|---|---|---|
| p3 ext4 `data` | `/data` | файлы строк `data` манифеста (шрифты в префиксе Wine и т. п.); потом сохранения и настройки |
| p4 FAT32 `GAMES` | `/games` | каталог на каждую игру манифеста, размер — игры плюс `games_free_mb` |

Разделы стоят там, где их ищет S05data (`IMAGE_DATA_START_MB`, `IMAGE_DATA_SIZE_MB`
из `configs/<fw>_defconfig`), поэтому первая загрузка находит их и оставляет как есть.
Root и loop-устройства не нужны: ext4 собирается `mke2fs -d` под `fakeroot`, FAT32 —
`mkfs.vfat` и `mcopy` (mtools), обложки — Python PIL. Манифест для такого образа
указывает в `[image]` свою прошивку (`fw`) и её образы (`base`, `base_emmc`).

```sh
scripts/games-image.py -m МАНИФЕСТ                       # оба образа
scripts/games-image.py -m МАНИФЕСТ --only sd             # один
scripts/games-image.py -m МАНИФЕСТ --reuse --games doom  # остальные игры из прошлого раза
```

Результат — `<out>/<name>.img` (и `<name>-emmc.img`). Файлы разреженные: раздел
данных пустой. Запись — штатными целями с другим файлом:
`make FW=<fw> flash IMAGE_FILE=<образ> DEV=/dev/sdX`. Запись образа стирает всё, что
было на `/data` и `/games` платы, включая сохранения. Раздел игр в образе не
растягивается до конца карты: если нужно место под игры, копируемые потом, задайте
`games_free_mb` или `games_size_mb`.

## Карта GO Advance

`games/oga.manifest` — игры GO Ultra, которые тянет GO Advance (RTCW, Fallout 1 и 2,
«Как достать соседа» 1 и 2, Serious Sam 1 и 2, Syberia), с теми же источниками и своими
настройками из `games/<игра>/overlay-oga` (экран 480×320, один стик; Fallout —
`FALLOUT_SCREEN` и `FALLOUT_BAR` для `fallout/prepare.sh`; Serious Sam —
`SSAM_LAYOUT=oga` для `serioussam/controls.py`: стик смотрит, крестовина ходит, ~27–30 fps;
Syberia — с `wine.ini` GO Ultra: стик — курсор, вступительный ролик на OGA чёрный —
F1 пропускает). Раздел `GAMES` у OGA — p4 его единственной
SD-карты, поэтому `--card` указывает на сам `<work>/games`, а на плату игры идут по
ssh (`tar`, `/games` перемонтируется на запись). Подробности и что не перенесено —
[docs/boards/oga.md](../docs/boards/oga.md), «Игры с GO Ultra».

## Данные проекта вне git: `lab/`

Всё, что не входит в git и не нужно самой сборке (Buildroot живёт на ext4 в
`output/`), лежит в одном месте — `/media/D/OdroidLab`, а в корне SDK на него
указывает ссылка `lab` (в `.gitignore`; на новом ПК:
`ln -s /media/D/OdroidLab lab`):

| Каталог | Что |
|---|---|
| `lab/games/` | игры манифеста (кроме Steam: они остаются в библиотеке Steam, `steam` в `[image]`) |
| `lab/redist/` | DLL (`SysWOW64/`) и шрифты (`Fonts/`) из Windows, которые манифест кладёт к играм |
| `lab/images/` | собранные образы с играми (`out`, `work` манифеста) |
| `lab/backups/<плата>/` | снятые с плат бэкапы: eMMC, загрузочная область, FIP, /data, карта игр |
| `lab/wip/` | исходники и сборки на время работы (box64, innoextract, RTCW, sdk-dl…) |

Пути в манифесте — относительно SDK (`lab/games/...`) или через `${steam}`, без
`/media/...` разделов Windows.

## Манифест

`games.manifest` — ini-файл. В `[image]`: прошивка (`fw`), промежуточные файлы
(`work`, нужно место на размер игр), для образа — образы прошивки (`base`,
`base_emmc`), куда класть результат (`out`, `name`) и запас места на `/games`. Дальше по секции на игру:

| Ключ | Что |
|---|---|
| `dir` | каталог на `/games` (по умолчанию имя секции) |
| `install` | `copy` — `source` целиком без `exclude`; `homm3`, `halflife` — `scripts/<x>-install.sh` (только нужное движку, `options` — его ключи); `none` — только файлы ниже |
| `source` | игра на этом компьютере |
| `exclude` | шаблон того, что не копировать (путь от `source` или имя), можно несколько строк |
| `file` | `SRC [-> DST]`: ещё файл в каталог игры, можно несколько |
| `overlay` | каталог SDK, который кладётся поверх игры (`wine.ini`, настройки) |
| `run` | программа после копирования, с `GAME_DIR`, `SOURCE`, `SDK_DIR`, `DATA_DIR` |
| `data` | `SRC -> DST`: файлы на `/data` (путь от `/data`), можно несколько |
| `cover` | картинка для главного экрана bare_app: файл, `АРХИВ:ЗАПИСЬ` из `.lod`/`.wad` игры, `ПРОГРАММА.exe:icon` (её самый большой значок) или `ВИДЕО.bik:СЕКУНДЫ` (кадр ролика, ffmpeg); обрезается в квадрат (`cover_crop`: `center`, `top`, `bottom`, `left`, `right`, `fit`), 240×240, `cover.png` в каталоге игры |
| `cover_back` | картинка-фон для значка: размывается и затемняется, `cover` кладётся на неё целиком с тенью |

Пути без `/` в начале — от корня SDK; в `file`, `data`, `cover` работают шаблоны.

## Раскладка

У всех игр одна схема, отступления — только где у игры нет такого действия или её
меню требуют другого (Prince of Persia, Shade: меню щёлкаются мышью, поэтому A —
левый клик). F1 во всех играх открывает главное меню игры (в «Героях» — системные
опции), сворачивает игру F5.

Экшены и шутеры (DOOM 3, RTCW, Serious Sam, Half-Life, Doom, Shade, Knights of the
Temple, Prince of Persia, «Корсары»):

| Кнопка | Действие |
|---|---|
| левый / правый стик | ходьба / обзор, камера |
| R1 | огонь, удар |
| L1 | перезарядка, блок |
| A | действие (и выбор в меню) |
| B | прыжок (и назад в меню) |
| X | присесть |
| Y | особое: фонарик, бомба, рывок, перемотка |
| L2 / R2 | прошлое / следующее оружие |
| крестовина | своё у игры: ходьба, второй режим огня, оружие |
| F1 | меню, пропуск |
| F2 / F3 | быстрая загрузка / быстрое сохранение |
| F4 | карта, журнал, инвентарь (PDA, ИНЕРТАН) |

Игры с мышью (Monkey Island, Syberia, Daemonica, Neighbours, Fallout, Герои III / HotA,
Pirates!):

| Кнопка | Действие |
|---|---|
| левый стик | курсор |
| правый стик, крестовина | прокрутка карты, камера, ходьба |
| A | левый клик |
| B | назад (Esc) |
| Y | правый клик |
| X | главная клавиша игры: Enter, инвентарь, «да» |
| L1 | лупа (где есть) |
| F1 | меню (Esc; HotA — системные опции, O) |
| F2 / F3 | загрузка / сохранение |
| F4 | карта, журнал, персонаж, конец хода |

Гонка NFSU и The Bard's Tale (свой геймпад XInput, игра рисует его кнопки) — как задумано
игрой.

Нажатия стиков (L3/R3) у консоли нет: бег — левый стик до упора (Doom, DOOM 3, RTCW;
Serious Sam бегает всегда). Кнопки, которые игре не нужны, в `wine.ini` — `none`
(иначе bare_app шлёт значения по умолчанию: Shift, Ctrl, PgUp...).

Исключения из схемы (аудит управления 2026-11-20, `docs/game-controls-audit-2026-11-20.md`):

| Игра | Отличие | Почему |
|---|---|---|
| Half-Life | L1 — второй режим огня, крестовина ↑ — перезарядка | второй огонь у 6 видов оружия и нужен на ходу; перезарядка автоматическая |
| RTCW | Y — бинокль | бег — стиком до упора |
| Fallout | F2/F3 — быстрые загрузка/запись sfall (F7/F6), первая запись спрашивает слот | — |
| Fallout 2 | F2/F3 — экраны загрузки/записи, L1 — Enter (запись: F3, L1, L1) | F6/F7 в этой сборке FE не отвечают |
| Pirates! | F2/F3 — быстрые загрузка/запись (Shift+L/S, только в море), F4 — карта, L2 — статус, R2 — экран записи | — |
| Корсары | A — пробел+Enter (и в меню, и в диалогах); F2/F3 — сабля, ускорение времени | у игры нет быстрой записи |
| HotA, Герои III (GO Ultra) | L2 — «ждать» / след. город, R2 — книга заклинаний | громкость — кнопками громкости консоли |
| Daemonica | F4 — дневник, R2 — справка | — |
| Prince of Persia, Shade | A — левый клик (меню щёлкаются мышью), R1 дублирует удар | — |
| Fallout, Shade | `esc_delay = 30`: B/F1 первые 30 с ничего не делают | Esc в главном меню закрывает игру без вопроса |

## Игры

Описание каждой игры (`wine.ini`, `game.ini`) лежит на карте в каталоге игры — из
`games/<id>/overlay` или `apps/bare_app/ports/wine/wine.ini`; в rootfs только движки.
bare_app показывает лишь игры, файлы которых есть, и сам перестраивает меню, когда
карта или каталоги игр меняются: после `games-image.py` перезагружать плату не нужно.

- **heroes3** — Heroes III: `Data`, `Maps`, `MP3` установки и моды VCMI (HotA,
  русский перевод) через `scripts/homm3-install.sh`.
- **hota** — та же установка Heroes III: Horn of the Abyss целиком, оригинальная
  игра (HotA 1.8 + HD-мод) под Wine: `hota/overlay/wine.ini` — экран 854×600 на весь
  дисплей (по ширине 1:1, по высоте 600 → 480), управление как у VCMI на GO Ultra
  (лупа на L1, крестовина и правый стик прокручивают карту или двигают лупу, у края
  экрана карта крутится, только пока стик толкает туда; F1 — системные опции, F5
  сворачивает, L2 — «ждать» в бою, R2 — книга заклинаний, как у VCMI на GO Ultra); `hota/prepare.sh` ставит
  HD-моду разрешение 854×600 и вывод через GDI; обложка — рог из значка exe на фоне
  из `H3bitmap.lod` (`cover_back`).
- **halflife** — Half-Life из Steam через `scripts/halflife-install.sh`.
- **pirates** — Sid Meier's Pirates! (Wine): `wine.ini` — пример из bare_app
  (`apps/bare_app/ports/wine/wine.ini`).
- **daemonica** — Daemonica (Wine): `daemonica/overlay/wine.ini` — раскладка кнопок
  (правый стик крутит камеру), `daemonica/prepare.sh` ставит режим 800×600 в
  `Data/daemonica.cfg` и перекладывает диалоги под крупный шрифт
  (`daemonica_dialog.py`: правит `daemonica.wrs`, проверка движка — `wrscheck.py`,
  упаковка — `lzss_pack.py`, формат — `wrs.py`). OpenAL берётся из `SysWOW64`
  Windows, шрифты Arial и Palatino — из её `Fonts` в префикс Wine на `/data`.

- **monkey1** … **monkey5** — пять глав Tales of Monkey Island (GOG, Wine), каждая
  своей игрой, без общего `Launcher.exe` GOG: в издание уже положены русские
  файлы «Буки» (озвучка, шрифт, надписи), русский текст есть в его архивах; язык
  движок берёт из реестра — строки `reg` в `wine.ini` (`Language=russian`).
  Сглаживание выключено (`NoMultisample=1`, патч Wine 0021: 19 → 39 fps), сцену
  на качестве 1–6, которую эта версия не выводит на экран, показывает патч 0022
  (`WINE_D3D9_SHOW_LOST_SCENE=1`). D3DX 9.41 берётся из `SysWOW64` Windows,
  обложка главы 1 — значок GOG; подробности — `monkey1/README.md`.

- **templar** — Knights of the Temple: Infernal Crusade, русское издание 1С (Wine):
  `templar/overlay/wine.ini` — раскладка консольных версий (крестовина — оружие,
  правый стик — камера), `gamma = 1.6` для тёмных подземелий; нужен Mesa-патч 0005
  (`PAN_MMAP_WINDOW`, 6 → 60 fps). Обложка — кадр ролика `bd_05.bik` (через ffmpeg).

- **pop** — Prince of Persia: The Sands of Time, GOG (Wine), по-русски (текст, речь и
  ролики русского издания: `prepare.sh` накладывает `pop1_rus_full.exe` из `${installers}`,
  меню PC-версии английские), `prepare.sh` также собирает
  `poplaunch.exe` (запуск без лаунчера GOG), в `overlay/` — `wine.ini` (левый стик —
  W A S D, правый — мышь: камера и кинжал-указатель меню, `mouse = relative`) и
  готовый профиль «prince»; около 30 fps; подробности — `pop/README.md`.

- **fallout**, **fallout2** — Fallout 1 и 2, русские «Fixed Edition» (sfall, hi-res
  патч; Wine): из `FalloutFE.tar.xz`/`Fallout2FE.tar.xz` Kron4ek'а только
  `game_info/data`. `fallout/prepare.sh` (общий) ставит 854×480 — пиксель в пиксель;
  ролики MVE требуют `BOX64_DYNAREC_BIGBLOCK=0`, запуск — патча wowbox64 0004;
  записываемы `data/savegame`, `data/maps`, `data/proto`, `data/scripts`;
  подробности — `fallout/README.md`.
- **shade** — Shade: Wrath of Angels («Гнев ангелов», 1С; Wine): `prepare.sh` ставит
  854×480 и снимает инверсию мыши; левый стик — W A S D, правый — камера
  (`mouse = relative`); 60–70 fps; `shade/README.md`.
- **nfsu** — Need for Speed: Underground 1.4 с widescreen fix (Wine): `prepare.sh`
  кладёт русские файлы из `rus/` архива поверх игры и переносит профили в `save/`
  каталога игры; в `overlay/save` — готовый профиль «player» (имя с консоли не
  набрать); левый стик — аналоговый руль через геймпад Wine (`stick = pad`, патч
  0026); ~43 fps в гонке; `nfsu/README.md`.
- **syberia** — Syberia, русское издание 1.0 (Wine, Direct3D 7, ролики Bink): как
  установлено, без правок; 800×600 целиком, 30 fps; стик — курсор, A/B — кнопки
  мыши; `syberia/README.md`.
- **corsairs** — «Корсары: Пираты Карибского моря» (Storm, Direct3D 8, ролики WMV
  через GStreamer; Wine): `prepare.sh` кладёт русскую озвучку и ролики (то, что
  делает `sound_video_on.bat`), снимает Intel Fix (полное море, fps тот же) и
  переписывает управление в `options` под геймпад (левый стик — W A S D);
  ~50 fps; `corsairs/README.md`.
- **bardstale** — The Bard's Tale (ремастер GOG; Wine, XInput): `prepare.sh` ставит
  русский язык в миниманифест GOG (`goggame-*.info`), текст русский, речь
  английская (русской в издании нет); профиль с `settings.bin`, где включён
  геймпад; 60 fps; `bardstale/README.md`.
- **ssam1**, **ssam2** — Serious Sam: The First / The Second Encounter (1.05/1.07,
  русские .gro) под Serious Engine 1.10 (пакет `serious-engine`,
  `bare-app.SERIOUSSAM=y`): `serioussam/prepare.sh` пишет управление геймпада
  (`controls.py`) и пункт «Помощь в прицеливании»; ~60 fps; `serioussam/README.md`.

- **doom3** — DOOM 3 BFG Edition (GOG) под RBDOOM-3-BFG: `base/` без
  сетевых карт, все три кампании (с Resurrection of Evil и The Lost Mission) —
  6,4 ГБ; `doom3/overlay/game.ini` — пункт меню (движок в rootfs).
- **rtcw** — Return to Castle Wolfenstein под iortcw (одиночная игра): из `Main/`
  установки только `pak0.pk3`, `sp_pak*.pk3` патча 1.41 и `z_*.pk3` перевода в
  `rtcw/main/`; движок и `gamepad.cfg` — в rootfs (пакет `iortcw`), пункт меню —
  `rtcw/overlay/game.ini`. Обложка — значок exe.
- **ut2004** — Unreal Tournament 2004, поставленный на ПК Linux-установщиком DVD
  (`linux-installer.sh`: английский, версия 3186, x86_64 `System/ut2004-bin`, CD-ключ
  в `System/cdkey`, ~5,3 ГБ) в `/home/sobs/Documents/UT2004`: копируется целиком без
  файлов установщика, исходников SDL/OpenAL, x86_64 SDL 1.2/OpenAL игры и
  `UT2004.exe` (`exclude`); исполняет Box64
  (пакеты `box64`, `sdl12-compat`, стартер `ut2004`: `bare-app.UT2004=y`). В
  `ut2004/overlay/` — `game.ini` (стики — джойстик игры, кнопки — клавиши) и
  `bare_app/UT2004.ini`, `User.ini` — настройки, которые стартер накладывает на
  `Default*.ini` при первом запуске. Обложка — логотип установщика
  (`cover = game:Help/UT2004Logo.bmp`). **Нужен CD-ключ своей копии** в
  `System/cdkey` (без него игра выходит сразу после запуска рендера).
- **neighbours**, **neighbours2** — Neighbours from Hell 1 и 2 (Wine): игра 800×600,
  показываются верхние 480 строк 1:1 (`rows = 480` в `wine.ini`), интерфейс
  перекладывает `neighbours*/prepare.sh`; подробности в `apps/bare_app/README.md`.
- **doom** — Doom: shareware `doom1.wad` уже в rootfs, секция ставит только обложку
  (`TITLEPIC` из wad собранного образа `output/ogu`).

Doom (shareware `doom1.wad`) уже есть в rootfs; полный `doom.wad`/`doom2.wad` можно
добавить секцией с `install = none` и `file = .../doom2.wad`, `dir = doom`.
