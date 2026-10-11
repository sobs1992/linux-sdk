# Архитектура SDK

## Идея в одном абзаце

Исходники компонентов лежат в `src/` как сабмодули и **никогда** не меняются сборкой.
Всё, что специфично для платы, — конфиги, фрагменты, файлы для загрузочного раздела —
лежит в `board/<плата>/`. **Конфиг прошивки** `configs/<имя>_defconfig` связывает
одно с другим: какие исходники, какие defconfig и фрагменты, какой тулчейн, как
разметить карту. Верхний `Makefile` по этому конфигу собирает каждый компонент
отдельно в `output/<имя>/`, а скрипт `mkimage.sh` склеивает результаты в `.img`.

## Дерево каталогов

```text
linux-sdk/
├── Makefile                 оркестратор: выбор прошивки, сборка компонентов, образ
├── configs/
│   ├── oga_defconfig        конфиг прошивки ODROID-GO Advance
│   ├── bbb_defconfig        BeagleBone Black
│   ├── rpi1_defconfig       Raspberry Pi 1 / Zero
│   └── rpi4_defconfig       Raspberry Pi 4 / 400
├── board/
│   ├── common/
│   │   ├── buildroot/       общий BR2_EXTERNAL "SDK": пакеты, overlay, post-build
│   │   └── rpi-firmware.sha256
│   ├── oga/
│   │   ├── u-boot/oga.config     фрагмент U-Boot
│   │   ├── linux/oga.config      фрагмент ядра
│   │   ├── buildroot/defconfig   defconfig Buildroot
│   │   └── rkbin/                блобы и утилиты Rockchip
│   ├── bbb/ rpi1/ rpi4/          то же для других плат (+ boot/config.txt у RPi)
├── scripts/
│   ├── mkimage.sh           склейка образа
│   ├── kconfig-check.sh     проверка фрагментов
│   ├── rk-legacy-pack.sh    упаковка uboot.img/trust.img (OGA)
│   ├── fetch-files.sh       загрузка блобов с проверкой sha256
│   └── flash.sh             запись на SD
├── src/                     сабмодули: tf-a, u-boot, linux, buildroot
├── dl/                      кэш загрузок         (в .gitignore)
└── output/                  результаты сборки    (в .gitignore)
```

## Поток данных

<figure>
<svg viewBox="0 0 640 250" xmlns="http://www.w3.org/2000/svg" font-family="Noto Sans, sans-serif" font-size="10">
  <defs><marker id="b" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="#555"/></marker></defs>
  <g stroke="#4a6587" fill="#eef3f9">
    <rect x="10" y="10" width="150" height="34" rx="3"/>
    <rect x="10" y="60" width="150" height="34" rx="3"/>
    <rect x="10" y="110" width="150" height="34" rx="3"/>
    <rect x="10" y="160" width="150" height="34" rx="3"/>
  </g>
  <g stroke="#7a5a2f" fill="#fbf3e6">
    <rect x="240" y="10" width="160" height="34" rx="3"/>
    <rect x="240" y="60" width="160" height="34" rx="3"/>
    <rect x="240" y="110" width="160" height="34" rx="3"/>
    <rect x="240" y="160" width="160" height="34" rx="3"/>
  </g>
  <g stroke="#2c7343" fill="#edf7ef"><rect x="470" y="85" width="160" height="60" rx="3"/></g>
  <g fill="#14213d">
    <text x="18" y="25" font-weight="bold">src/tf-a</text><text x="18" y="38">bl31 (PLAT)</text>
    <text x="18" y="75" font-weight="bold">src/u-boot</text><text x="18" y="88">defconfig + фрагмент</text>
    <text x="18" y="125" font-weight="bold">src/linux</text><text x="18" y="138">defconfig + фрагмент</text>
    <text x="18" y="175" font-weight="bold">src/buildroot</text><text x="18" y="188">defconfig + BR2_EXTERNAL</text>
    <text x="248" y="25" font-weight="bold">output/fw/tf-a</text><text x="248" y="38">bl31.elf</text>
    <text x="248" y="75" font-weight="bold">output/fw/images</text><text x="248" y="88">u-boot-rockchip.bin, MLO…</text>
    <text x="248" y="125" font-weight="bold">output/fw/linux-install</text><text x="248" y="138">Image, dtbs/, modules/</text>
    <text x="248" y="175" font-weight="bold">output/fw/images</text><text x="248" y="188">rootfs.tar</text>
    <text x="478" y="105" font-weight="bold">scripts/mkimage.sh</text><text x="478" y="120">images/&lt;fw&gt;.img</text><text x="478" y="134">boot-area.bin</text>
  </g>
  <g stroke="#555" marker-end="url(#b)" fill="none">
    <line x1="160" y1="27" x2="238" y2="27"/><line x1="160" y1="77" x2="238" y2="77"/>
    <line x1="160" y1="127" x2="238" y2="127"/><line x1="160" y1="177" x2="238" y2="177"/>
    <path d="M320 44 L320 58"/>
    <path d="M400 77 L468 100"/><path d="M400 127 L468 118"/><path d="M400 177 L468 135"/>
  </g>
  <text x="10" y="225" fill="#555">BL31 передаётся в U-Boot (BL31=…); конфиг прошивки configs/fw_defconfig управляет всеми стрелками</text>
</svg>
<figcaption>Рис. 5.1. От исходников к образу</figcaption>
</figure>

## Принципы

**Компонент собирается одной командой и не знает о других.** `make linux` не
трогает U-Boot, `make rootfs` не трогает ядро. Единственная связь — U-Boot получает
готовый BL31 через переменную `BL31=`.

**Модули ядра попадают в rootfs только при склейке.** Buildroot ничего не знает
о ядре. Ядро ставит модули в `output/<fw>/linux-install/modules`, а `mkimage.sh`
распаковывает `rootfs.tar` и докладывает туда модули. Поэтому можно пересобрать
ядро и сделать `make image`, не трогая Buildroot.

**Конфиг прошивки — единственное место, где описана плата.** В Makefile нет ни
одного `ifeq ($(BOARD),oga)`. Всё, чем платы отличаются, — переменные в конфиге.

**Повторяемость.** Версии зафиксированы сабмодулями, блобы — хешами, загрузки —
кэшем `dl/`. Один и тот же коммит SDK даёт один и тот же образ.

**Без root.** Образ собирается через `fakeroot`, `mke2fs -d`, `mtools` и `sfdisk`
по файлу. `sudo` нужен только в `flash.sh`.

## Конфиг прошивки

Это обычный фрагмент Makefile, который подключается через `include`. Вот конфиг OGA
целиком:

{{include configs/oga_defconfig make}}

Обратите внимание:

- `*_DEFCONFIG` бывает двух видов: имя из дерева исходников (`odroid-go2_defconfig`,
  `defconfig`) или путь к файлу в SDK (`$(BOARD_DIR)/buildroot/defconfig`). Makefile
  различает их по наличию `/`.
- `$(IMAGES_DIR)` и `$(LINUX_INSTALL)` — каталоги с результатами сборки этой прошивки.
  Makefile определяет их **до** подключения конфига, поэтому ими можно пользоваться
  в `IMAGE_RAW` и `IMAGE_BOOT_FILES`.
- `ifeq` внутри конфига работает: это настоящий Makefile.

Полный справочник переменных — в приложении B.

## Выбор прошивки

```bash
make oga_defconfig        # запоминает выбор в output/.fw
make                      # собирает выбранную
make FW=bbb linux         # разово собрать для другой, не меняя выбор
make info                 # что выбрано и какие версии компонентов
```

`make info` для OGA:

```text
Firmware:  oga (configs/oga_defconfig)
Compiler:  aarch64-linux-gnu-gcc
TF-A:      src/tf-a [v2.15.0] PLAT=px30
U-Boot:    src/u-boot [v2026.07] odroid-go2_defconfig oga.config
BL31:      output/oga/tf-a/px30/release/bl31/bl31.elf
Linux:     src/linux [v7.2.9] ARCH=arm64 defconfig oga.config
Buildroot: src/buildroot [2026.08] board/oga/buildroot/defconfig
Image:     output/oga/images/oga.img
```

Версия в квадратных скобках — `git describe --dirty`. Если в сабмодуле есть
незакоммиченные изменения, к ней добавится `-dirty`.
