# Как добавить игру или программу

Игры запускает bare_app; каждая — отдельный процесс, который отдаёт кадры и получает
геймпад по протоколу `apps/bare_app/src/games/game_ipc.h`. Есть три пути, от простого к
сложному; подробности с примерами кода — `apps/bare_app/docs/GAMES.md`.

| Путь | Что нужно | Код bare_app | Пересборка |
|---|---|---|---|
| **Windows-игра под Wine** (GO Ultra) | каталог игры на карте игр с `wine.ini` (образец `apps/bare_app/ports/wine/wine.ini`); в проекте — `games/<id>/overlay/wine.ini`, при необходимости `games/<id>/prepare.sh`, секция в `games/games.manifest`, строка в `games/README.md` | нет | нет |
| **SDL2-игра** (готовая программа; и Linux-игра x86_64 на SDL 1.2 под Box64, как UT2004) | `game.ini` (формат — `apps/bare_app/docs/game.ini`) в каталоге игры на `/games`: в SDK — `games/<id>/overlay/game.ini`, его кладёт на карту `games-image.py`; если движок — пакет Buildroot: пакет в `board/common/buildroot/package/<pkg>/` (только движок), опция `BR2_PACKAGE_BARE_APP_<GAME>` в `package/bare-app/Config.in` (`select` пакета), `bare-app.<GAME>=y` в `APPS_CONFIG` прошивки, секция в манифесте с файлами игры и `overlay`. `/usr/share/bare_app/games/<id>.ini` — только для игры, целиком лежащей в образе | нет | пакет и rootfs (только движок; описание — на карте) |
| **Игра со своим движком** без SDL (VCMI, Xash3D, Doom) | программа с `game_ipc_client.h`; в bare_app: `games/<игра>.c` со `struct game_def`, строка в `games/games.c`, символ `GAME_<ИГРА>` в `Kconfig`, `add_if()` в `CMakeLists.txt`, строки в `i18n`; в SDK: пакет движка, строка `CONFIG_GAME_<ИГРА>` в `package/bare-app/bare-app.mk`, опция в его `Config.in`, `APPS_CONFIG` | да | bare_app, пакет, rootfs |

Где что лежит на плате и на ПК:

- файлы игры — раздел игр (`/games/<id>`, карта exFAT `GAMES` у GO Ultra, см.
  [sd-layout.md](sd-layout.md)); на ПК — `lab/games/<Игра>` (вне git, `games/README.md`);
  `scripts/games-image.py` переносит их по манифесту;
- сохранения и настройки — `/data/<id>` (у Wine общий префикс `/data/wine/prefix`; если
  Windows-игра пишет сохранения в профиль — Документы, AppData, — назовите эти каталоги
  ключом `saves` в её wine.ini: по нему экран опций игры удаляет сохранения, см.
  `apps/bare_app/docs/GAMES.md`, «Данные игры»);
- обложка — `cover.png` в каталоге игры (манифест делает её из картинки, значка exe
  или кадра ролика);
- управление — `[keys]`/`[labels]` ini-файла; имена кнопок одни и те же в `wine.ini`,
  `game.ini` и файле настроек (`a`, `b`, `l1`, `stick`, `rstick`: `src/core/gp_names.c`);
  переназначение пользователем — экран «Управление игры» bare_app;
- переменные окружения для производительности — `[env]` в `game.ini`, `env =` в
  `wine.ini` (общие для всех Wine-игр: `BOX64_DYNAREC_BIGBLOCK=3`,
  `BOX64_DYNAREC_CALLRET=1`), `PAN_MESA_DEBUG=noafbc` ставит bare_app сам для SDL2-игр
  и Half-Life.

Проверка без перепрошивки: программу и ini копируют на плату по ssh
(`ssh ... tar`, пример в `GAMES.md`), игру запускают из меню или командой
`scripts/ogu-ctl.py launch:<имя>`, снимок экрана — `ogu-ctl.py shot`.
