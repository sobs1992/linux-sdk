# Как добавить плату

Исходники общие для всех плат, различаются конфиги. Новая плата — это каталог
`board/<board>/`, конфиг `configs/<fw>_defconfig` и, если на ней работает bare_app,
платформа в приложении. Образец с TF-A и патчами — `oga`; с блобами загрузчика,
скачиваемыми при сборке, — `ogu` (Amlogic) и `rpi4` (Raspberry Pi); самый короткий —
`bbb`.

## Чек-лист

1. **`configs/<fw>_defconfig`.** Нужны `CROSS_COMPILE`, U-Boot (`UBOOT_DEFCONFIG`,
   `UBOOT_IMAGES`), ядро (`LINUX_DEFCONFIG`, `LINUX_DTBS`, `LINUX_CMDLINE`, для 32-битных
   плат `LINUX_ARCH := arm` и `LINUX_IMAGE := zImage`), образ (`IMAGE_RAW` или
   `IMAGE_BOOT_FILES`, `IMAGE_BOOT_SIZE_MB`, `IMAGE_DISK_ID`). Всё остальное имеет
   умолчания (`BOARD_DIR = board/<fw>`, исходники в `src/`, `IMAGE_NAME = <fw>`), см.
   таблицу в [config.md](config.md) и шапку `configs/oga_defconfig`.
   Если плате нужен иной способ упаковки загрузчика (как `RK_LEGACY` у Rockchip или
   FIP у Amlogic), это шаг в `Makefile` в разделе U-Boot: пока таких способов два.
2. **`board/<board>/buildroot/defconfig`** — defconfig Buildroot: скопировать у
   ближайшей платы (общая часть у всех одинакова: тулчейн glibc с C++, mdev, dropbear,
   overlay и post-build общего дерева, `BR2_PACKAGE_HOST_MTOOLS` — его `mcopy` нужен
   `mkimage.sh`). Приложения (`BR2_PACKAGE_BARE_APP` и т. п.) сюда не писать: они
   приходят из `APPS` конфига прошивки. Свой overlay и post-build платы указываются в
   defconfig путями от `$(BR2_EXTERNAL_SDK_PATH)/../../<board>/buildroot/...` (как у
   `oga` и `ogu`); если `/data` и `/games` нужны, в rootfs должны быть `sfdisk`, `partx`,
   `blkid` (util-linux) и `mke2fs` (e2fsprogs), см. [sd-layout.md](sd-layout.md).
3. **`board/<board>/linux/<board>.config`** — фрагмент поверх in-tree defconfig ядра
   (`LINUX_FRAGMENTS`); `scripts/kconfig-check.sh` после конфигурирования скажет, какие
   строки не попали в `.config`. Патчи — `linux/patches/`, внешние модули —
   `linux/<module>/` с `Kbuild` (`LINUX_EXT_MODULES`).
4. **`board/<board>/u-boot/<board>.config`** и при необходимости `u-boot/patches/`.
5. **`board/<board>/boot/`** — файлы, которые лежат в корне BOOT (`config.txt`,
   `boot.ini`), перечисленные в `IMAGE_BOOT_FILES`.
6. **Блобы.** Скачиваемые при сборке — через `BOOTFW_*` (копируются на BOOT) или
   `AML_FIP_*` (пакуются в FIP), с файлом хешей `sha256sum` в каталоге платы.
   Коммитить блобы можно только там, где лицензия позволяет (`board/oga/rkbin`).
7. **Пакеты платы** (прошивка Wi-Fi, кодера) — `board/common/buildroot/package/<pkg>/`
   плюс строка `source` в `board/common/buildroot/Config.in` (`.mk` подхватывается сам,
   `Config.in` — нет); включаются в defconfig платы.
8. **bare_app**, если плата с экраном и кнопками: `apps/bare_app/src/platforms/<board>.c`
   (таблицы драйверов, раскладка кнопок, пути), строка в `platforms[]`
   (`hal/platform.c`), символ `PLATFORM_<BOARD>` в `Kconfig`, `add_if()` и список
   платформ в `CMakeLists.txt`, `configs/<board>_defconfig` приложения; подробно —
   таблица «Как расширять» в `apps/bare_app/docs/ARCHITECTURE.md`. В конфиге прошивки:
   `APPS := bare-app`, `APPS_CONFIG := bare-app.DEFCONFIG=<board>_defconfig`.
9. **Документация:** строка в таблице «Платы» `README.md`, свой `docs/boards/<board>.md`
   (загрузочная цепочка, консоль, особенности), при необходимости глава в
   `docs/check-book`.

## Проверка

```sh
make <fw>_defconfig && make info     # все пути и версии, ничего не собирая
make uboot && make linux && make rootfs && make image
make flash DEV=/dev/sdX              # make info перед этим: какая прошивка выбрана
```

Собирать по одному компоненту удобнее: `make -n <цель>` показывает команды без
запуска. `.config` компонента пересоздаётся, когда меняется его defconfig или фрагмент
(`.sdk-inputs` в каталоге сборки хранит, из чего он сделан).
