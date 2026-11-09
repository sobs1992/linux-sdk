# Игры полного образа

`scripts/games-image.py` собирает образ, в котором уже есть игры: берёт образы
прошивки (`make FW=ogu image` → `output/ogu/images/ogu.img`, `ogu-emmc.img`) и
дописывает в них разделы данных, которые иначе создаёт при первой загрузке
`/etc/init.d/S05data`:

| Раздел | Где | Что |
|---|---|---|
| p3 ext4 `data` | `/data` | файлы строк `data` манифеста (шрифты в префиксе Wine и т. п.); потом сохранения и настройки |
| p4 FAT32 `GAMES` | `/games` | каталог на каждую игру манифеста, размер — игры плюс `games_free_mb` |

Разделы стоят там, где их ищет S05data (`IMAGE_DATA_START_MB`, `IMAGE_DATA_SIZE_MB`
из `configs/<fw>_defconfig`), поэтому первая загрузка находит их и оставляет как есть.
Root и loop-устройства не нужны: ext4 собирается `mke2fs -d` под `fakeroot`, FAT32 —
`mkfs.vfat` и `mcopy` (mtools), обложки — Python PIL.

```sh
make FW=ogu image                              # образы прошивки
scripts/games-image.py                         # games/games.manifest, оба образа
scripts/games-image.py --only emmc             # только для eMMC
scripts/games-image.py --reuse --games pirates # остальные игры из прошлого раза
```

Результат — `<out>/<name>.img` и `<name>-emmc.img` (по умолчанию
`/media/D/ogu-images/ogu-games*.img`). Файлы разреженные: раздел данных пустой.
Запись — штатными целями с другим файлом:

```sh
make FW=ogu flash IMAGE_FILE=/media/D/ogu-images/ogu-games.img DEV=/dev/sdX
make FW=ogu flash-emmc IMAGE_EMMC_FILE=/media/D/ogu-images/ogu-games-emmc.img   # Vol+ при включении
```

Запись образа стирает всё, что было на `/data` и `/games` платы (сохранения тоже).
Раздел игр в образе не растягивается до конца карты: если нужно место для игр,
копируемых потом, задайте `games_free_mb` или `games_size_mb`.

## Манифест

`games.manifest` — ini-файл. В `[image]`: прошивка (`fw`), её образы (`base`,
`base_emmc`), куда класть результат (`out`, `name`) и промежуточные файлы (`work`,
нужно место на 1–2 размера игр), запас места на `/games`. Дальше по секции на игру:

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
| `cover` | картинка для главного экрана bare_app: файл, `АРХИВ:ЗАПИСЬ` из `.lod`/`.wad` игры или `ПРОГРАММА.exe:icon` (её самый большой значок); обрезается в квадрат (`cover_crop`: `center`, `top`, `bottom`, `left`, `right`, `fit`), 240×240, `cover.png` в каталоге игры |
| `cover_back` | картинка-фон для значка: размывается и затемняется, `cover` кладётся на неё целиком с тенью |

Пути без `/` в начале — от корня SDK; в `file`, `data`, `cover` работают шаблоны.

## Игры

- **heroes3** — Heroes III: `Data`, `Maps`, `MP3` установки и моды VCMI (HotA,
  русский перевод) через `scripts/homm3-install.sh`.
- **hota** — та же установка Heroes III: Horn of the Abyss целиком, оригинальная
  игра (HotA 1.8 + HD-мод) под Wine: `hota/overlay/wine.ini` — экран 854×600 на весь
  дисплей (по ширине 1:1, по высоте 600 → 480), L1 включает и выключает лупу 1:1,
  правый стик прокручивает карту, крестовина ходит героем; `hota/prepare.sh` ставит
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

Doom (shareware `doom1.wad`) уже есть в rootfs; полный `doom.wad`/`doom2.wad` можно
добавить секцией с `install = none` и `file = .../doom2.wad`, `dir = doom`.
