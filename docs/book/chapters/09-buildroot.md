# Корневая файловая система: Buildroot

## Почему Buildroot

Buildroot собирает из исходников кросс-тулчейн, библиотеку C, busybox и выбранные
пакеты и выдаёт готовую rootfs. Он прост (Makefile + Kconfig), воспроизводим и
хорошо подходит для встраиваемых систем. Альтернатива — Yocto: мощнее, но гораздо
тяжелее в освоении.

Buildroot умеет собирать и ядро, и U-Boot сам. Но по требованию SDK компоненты
независимы, поэтому в нашем defconfig Buildroot **не собирает** ни ядро, ни
загрузчик — только rootfs. На выходе — `rootfs.tar`.

## BR2_EXTERNAL: свои файлы вне дерева Buildroot

Менять файлы внутри `src/buildroot` не нужно. Для своих defconfig, пакетов и
overlay у Buildroot есть механизм **BR2_EXTERNAL** — внешнее дерево с минимальной
структурой:

```text
board/common/buildroot/
├── external.desc        имя дерева: "SDK" → переменная $(BR2_EXTERNAL_SDK_PATH)
├── external.mk          подключает package/*/*.mk
├── Config.in            подключает package/*/Config.in (меню пакетов)
├── package/             ваши пакеты
├── rootfs-overlay/      файлы, которые копируются в rootfs как есть
├── post-build.sh        скрипт, который правит rootfs перед упаковкой
└── busybox.fragment     фрагмент конфига busybox
```

{{include board/common/buildroot/external.desc text}}

Сначала у OGA было своё внешнее дерево `board/oga/buildroot`. При добавлении других
плат оно стало **общим** (`board/common/buildroot`, имя `SDK`), а у каждой платы
остался только defconfig `board/<плата>/buildroot/defconfig`. Так свои пакеты пишутся
один раз и доступны всем платам.

## Defconfig платы

{{include board/oga/buildroot/defconfig text}}

| Строки | Смысл |
|---|---|
| `BR2_aarch64`, `BR2_cortex_a35` | архитектура и точное ядро CPU |
| `BR2_TOOLCHAIN_BUILDROOT_GLIBC`, `_CXX` | собрать свой тулчейн с glibc и C++ |
| `BR2_PACKAGE_HOST_GDB`, `BR2_PACKAGE_GDB` | gdb на ПК и gdbserver на плате |
| `BR2_ROOTFS_DEVICE_CREATION_DYNAMIC_MDEV` | `/dev` через devtmpfs + mdev, модули грузятся по modalias |
| `BR2_TARGET_GENERIC_GETTY_PORT` | основная консоль входа (UART) |
| `BR2_ROOTFS_OVERLAY`, `_POST_BUILD_SCRIPT`, `_POST_SCRIPT_ARGS` | наши правки rootfs |
| `BR2_PACKAGE_BUSYBOX_CONFIG_FRAGMENT_FILES` | фрагмент конфига busybox |
| `BR2_TARGET_ROOTFS_TAR` | на выходе `rootfs.tar` (ext4 собирает `mkimage.sh`) |
| `BR2_PACKAGE_HOST_MTOOLS` | запасной `mcopy`, если его нет в системе |

### mdev и модули

С `DYNAMIC_MDEV` скрипт `/etc/init.d/S10mdev` при старте проходит по `/sys` и для
каждого устройства вызывает `modprobe` по его `modalias`. Поэтому модули ядра
(звук RK817, Ethernet, USB) подгружаются сами, без списков в `/etc/modules`.
Пакет `kmod` даёт полноценные `modprobe`/`lsmod`, хотя busybox справился бы и сам.

## post-build.sh

{{include board/common/buildroot/post-build.sh}}

Buildroot вызывает скрипт после сборки всех пакетов, передавая путь к будущей rootfs
и аргументы из `BR2_ROOTFS_POST_SCRIPT_ARGS`. Здесь он добавляет `getty` на экран
(`tty1`) рядом с основным на UART: Buildroot из коробки умеет только один getty.

Обратите внимание на комментарий: запись `/boot` в `/etc/fstab` делает **не**
post-build, а `mkimage.sh`. Это правило «знание живёт там, где его источник»:
разметку карты знает только сборка образа.

## Фрагмент busybox

{{include board/common/buildroot/busybox.fragment text}}

`/boot` монтируется по метке `LABEL=BOOT`, потому что номер `mmcblkN` у разных плат
разный (на Raspberry Pi 4 SD-карта может стать `mmcblk1`). Но в стандартной
конфигурации busybox `mount` **не понимает** ни `LABEL=`, ни `PARTUUID=`
(`# CONFIG_FEATURE_MOUNT_LABEL is not set`). Фрагмент включает эту возможность.

!!! warning "Ловушка: изменение фрагмента не пересобирает пакет"
    Buildroot пересобирает пакет только если его нет или вы попросили явно.
    После изменения фрагмента busybox для уже собранного rootfs нужно:
    `make rootfs-make BR=busybox-reconfigure`, затем `make rootfs`. То же касается
    любых изменений в конфигурации уже собранного пакета (`<пакет>-reconfigure`,
    `<пакет>-rebuild`, `<пакет>-dirclean`).

!!! warning "Ловушка: удалённые файлы overlay остаются"
    Buildroot копирует overlay в `output/<fw>/buildroot/target/`, но никогда оттуда
    **не удаляет**. Когда `profile.d/oga.sh` переименовали в `sdk.sh`, в rootfs
    оказались оба файла. Лечится удалением файла из `target/` руками (или полной
    пересборкой `make rootfs-clean rootfs`).

## Время и место

Первая сборка — самая долгая: Buildroot собирает **тулчейн** (binutils, GCC в два
прохода, glibc, заголовки ядра) — 30–60 минут и 5–9 ГБ в `output/<fw>/buildroot`.
Повторные сборки быстрые.

!!! danger "Опасно: параллельные сборки Buildroot"
    Buildroot по умолчанию собирает каждый пакет в `nproc + 1` поток. Три сборки
    Buildroot одновременно на 16 потоках и 14 ГБ ОЗУ, плюс ядро, привели к нехватке
    памяти: OOM killer убил графическую сессию вместе с IDE и всеми сборками
    (глава 14). Собирайте тулчейны **по одному**.

Можно сократить первую сборку, взяв готовый внешний тулчейн Bootlin
(`BR2_TOOLCHAIN_EXTERNAL_BOOTLIN_*`): он скачивается за минуту и экономит 3–5 ГБ.
В SDK остались собственные тулчейны, чтобы у всех плат были одинаковые версии
GCC/glibc и не было готовых бинарников. Решение стоит пересмотреть, если важнее
скорость.

## SDK для приложений

```bash
make rootfs-sdk
# → output/<fw>/images/aarch64-buildroot-linux-gnu_sdk-buildroot.tar.gz
```

Это переносимый тулчейн с sysroot — в нём уже есть заголовки и библиотеки всех
пакетов из rootfs. Использование:

```bash
tar xf aarch64-buildroot-linux-gnu_sdk-buildroot.tar.gz -C ~/opt
SDK=~/opt/aarch64-buildroot-linux-gnu_sdk-buildroot
$SDK/relocate-sdk.sh                     # прописать новый путь внутрь SDK
$SDK/bin/aarch64-buildroot-linux-gnu-gcc hello.c -o hello
scp hello root@board:/root/              # на BBB/RPi есть dropbear
```

Для CMake в SDK есть готовый toolchain-файл:
`cmake -DCMAKE_TOOLCHAIN_FILE=$SDK/share/buildroot/toolchainfile.cmake ..`.
Если включить в defconfig `BR2_PACKAGE_HOST_ENVIRONMENT_SETUP=y`, в SDK появится
скрипт `environment-setup`, который выставляет `CC`, `CFLAGS` и прочее:
`source $SDK/environment-setup`.

Отладка — `gdbserver :2345 ./hello` на плате и `aarch64-buildroot-linux-gnu-gdb`
на ПК (`target remote board:2345`).

!!! example "Упражнение: свой пакет"
    Создайте `board/common/buildroot/package/hello/` с `Config.in` и `hello.mk`
    (тип `generic-package`, исходник — локальный каталог через `HELLO_SITE_METHOD = local`),
    подключите его строкой в `board/common/buildroot/Config.in` и включите в defconfig
    платы. Проверьте, что `make rootfs` кладёт программу в rootfs.
