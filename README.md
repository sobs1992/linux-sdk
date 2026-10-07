# OdroidLinux SDK

SDK для ODROID-GO Advance (RK3326) на mainline-компонентах:

| Компонент | Каталог | Версия | Upstream |
|---|---|---|---|
| TF-A (BL31) | `src/tf-a` | v2.15.0 | github.com/ARM-software/arm-trusted-firmware |
| U-Boot | `src/u-boot` | v2026.07 | source.denx.de/u-boot/u-boot |
| Linux | `src/linux` | v7.2.9 | git.kernel.org stable |
| Buildroot | `src/buildroot` | 2026.08 | gitlab.com/buildroot.org/buildroot |

Каждый компонент — отдельный git-сабмодуль (локальная ветка `oga`), собирается
отдельно и out-of-tree в `output/<прошивка>/`, исходники не загрязняются.

## Быстрый старт

```sh
sudo apt install mtools          # для сборки FAT-раздела (иначе возьмётся из Buildroot host)
make oga_defconfig               # выбрать прошивку configs/oga_defconfig
make                             # uboot + linux + rootfs + image
make flash DEV=/dev/sdX          # записать output/oga/images/oga.img на SD
```

Отдельные компоненты:

```sh
make uboot            # TF-A + U-Boot  -> images/u-boot-rockchip.bin
make linux            # Image, dtbs, модули -> output/oga/linux-install/
make rootfs           # Buildroot      -> images/rootfs.tar
make image            # только склейка .img из уже собранного
make flash-uboot DEV=/dev/sdX   # перезаписать только загрузчик
make help             # все цели
```

Для каждого компонента есть `-menuconfig`, `-savedefconfig`, `-configure`, `-clean`
(`uboot-`, `linux-`, `rootfs-`). `make rootfs-make BR=busybox-menuconfig` вызывает
любую цель Buildroot, `make rootfs-sdk` собирает кросс-тулчейн с sysroot для приложений.

## Структура

```
configs/<fw>_defconfig      конфиг прошивки: какие конфиги компонентов брать, разметка образа
board/oga/u-boot/*.config   фрагменты поверх in-tree defconfig U-Boot
board/oga/linux/*.config    фрагменты поверх arm64 defconfig
board/oga/buildroot/        BR2_EXTERNAL: defconfig, overlay, post-build, свои пакеты
board/oga/rkbin/            блобы и утилиты Rockchip (BL31, loaderimage, trust_merger)
scripts/mkimage.sh          склейка образа (без root: fakeroot + mke2fs -d + mtools)
scripts/rk-legacy-pack.sh   упаковка uboot.img/trust.img для SPI miniloader
scripts/flash.sh            запись на SD с проверками
src/                        сабмодули компонентов
dl/                         кэш загрузок Buildroot (общий для всех прошивок)
```

Новая прошивка — новый `configs/<name>_defconfig`. В `*_DEFCONFIG` можно указать
имя in-tree defconfig'а или путь к своему файлу (если в значении есть `/`).
`.config` компонента пересоздаётся, когда меняется defconfig-файл или фрагмент;
правки из `menuconfig` живут до этого момента, сохраняйте их через `*-savedefconfig`
или переносите во фрагмент.

## Загрузка и разметка SD

```
сектор 0        MBR (disk id 0x4f474131)
16K..32K        окружение U-Boot (saveenv)
сектор 64       u-boot-rockchip.bin: idbloader (TPL с инициализацией DDR + SPL)
сектор 2048     u-boot.itb (U-Boot + BL31 TF-A + dtb), его грузит SPL
сектор 16384    uboot.img  (тот же U-Boot в формате Rockchip)   } для miniloader
сектор 24576    trust.img  (BL31 rkbin в формате Rockchip)       } из SPI-флеша
16M             p1 FAT32 BOOT: Image, rockchip/*.dtb, extlinux/extlinux.conf
16M+128M        p2 ext4 rootfs: rootfs.tar + модули ядра
```

BootROM RK3326 проверяет SPI-флеш раньше SD. У OGA Black Edition во SPI с завода
стоит recovery-загрузчик Hardkernel (DDR-блоб + miniloader rkbin, лог на 1500000),
поэтому образ гибридный (`RK_LEGACY := y` в конфиге прошивки):

- SPI с заводским загрузчиком: BootROM → SPI miniloader → `trust.img` (BL31 rkbin)
  → `uboot.img` (mainline U-Boot) → Linux;
- SPI пустой: BootROM → TPL → SPL → BL31 (mainline TF-A) → U-Boot → Linux,
  полностью открытая цепочка.

U-Boot определяет ревизию платы по SARADC и ставит `fdtfile`
(`rk3326-odroid-go2.dtb`, `-go2-v11.dtb`, `-go3.dtb`), extlinux берёт dtb через `fdtdir`.
Ядро получает `root=PARTUUID=4f474131-02`.

Консоль UART: `ttyS2`, 115200 начиная с U-Boot (TPL/SPL тоже 115200; DDR-блоб и
miniloader из SPI печатают на 1500000, CP2102 это не читает).
Логин `root` без пароля, getty также на экране (`tty1`).

`make flash-uboot DEV=/dev/sdX` перезаписывает всю загрузочную область
(сектора 64…32767, файл `images/bootloader.bin`), не трогая разделы.

Типичные причины «не грузится»:

- Загрузчик записан не по тем секторам или раздел перекрывает первые 16M.
- GPT: его таблица (сектора 2–33) пересекается с окружением U-Boot на 16K,
  поэтому здесь MBR.
- Не задан BL31: binman соберёт нерабочий образ (в SDK BL31 обязателен).

## Свои изменения в компонентах

```sh
cd src/linux
git checkout oga && git commit ...                    # работа в ветке oga
git remote add mine git@github.com:<you>/linux.git && git push mine oga
cd ../.. && git config -f .gitmodules submodule.src/linux.url git@github.com:<you>/linux.git
git add .gitmodules src/linux && git commit           # SDK пинует новый коммит
```
