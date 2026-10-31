# Программы в rootfs: пакеты Buildroot

Копировать программы на плату руками удобно, пока идёт разработка. Но всё, что
должно быть **в каждом образе**, нужно оформить так, чтобы `make rootfs image`
собирал это само. Для этого есть три механизма: готовые пакеты Buildroot, свои пакеты
и overlay.

## Включить готовый пакет

В Buildroot почти 3000 пакетов. Найти нужный:

```bash
ls src/buildroot/package | grep -i gpio
make FW=bbb rootfs-menuconfig          # меню; поиск — клавиша /
```

После выбора в меню сохраните изменения обратно в defconfig платы:

```bash
make FW=bbb rootfs-savedefconfig       # пишет board/bbb/buildroot/defconfig
git diff board/bbb/buildroot/defconfig # проверить, что добавилось
make FW=bbb rootfs image
```

Можно и сразу дописать строки в `board/<плата>/buildroot/defconfig`: SDK заметит,
что файл новее `.config`, и переконфигурирует Buildroot сам.

Полезные пакеты по платам:

| Пакет | Опция | Для чего | Платы |
|---|---|---|---|
| libgpiod2 + утилиты | `BR2_PACKAGE_LIBGPIOD2`, `_TOOLS` | GPIO из программ и shell | BBB, RPi |
| i2c-tools | `BR2_PACKAGE_I2C_TOOLS` | `i2cdetect`, `i2cget` | все |
| strace | `BR2_PACKAGE_STRACE` | отладка системных вызовов | все |
| lrzsz | `BR2_PACKAGE_LRZSZ` | файлы по UART | все, особенно OGA |
| dropbear | `BR2_PACKAGE_DROPBEAR` | SSH | OGA (у остальных уже есть) |
| SDL2 | `BR2_PACKAGE_SDL2`, `_KMSDRM` | игры и графика | OGA, RPi 4 |
| libevdev | `BR2_PACKAGE_LIBEVDEV` | удобная работа с вводом | OGA |
| picocom | `BR2_PACKAGE_PICOCOM` | терминал для UART на плате | все |

!!! warning "Ловушка: включили пакет — а уже собранный не пересобрался"
    Если пакет **уже собран**, а вы поменяли его опции (например, включили
    `BR2_PACKAGE_SDL2_KMSDRM`), Buildroot его не пересоберёт. Нужно
    `make rootfs-make BR=sdl2-reconfigure` (или `-dirclean`, а потом `make rootfs`).
    Новые пакеты собираются автоматически.

## Свой пакет

Возьмём программу `hello` из главы 4 и сделаем так, чтобы она попадала в каждый образ
вместе с init-скриптом, который запускает её при загрузке.

### Где что лежит

```text
apps/hello/                                     исходники (в SDK)
  hello.c, Makefile
board/common/buildroot/package/sdk-hello/       описание пакета
  Config.in        пункт меню
  sdk-hello.mk     как собирать и устанавливать
  S90sdk-hello     init-скрипт
board/common/buildroot/Config.in                подключение пункта меню
```

Исходники можно держать и в отдельном git-репозитории — тогда пакет будет скачивать
их (`SDK_HELLO_SITE = https://...git`, `SDK_HELLO_SITE_METHOD = git`). Для своих
программ в активной разработке удобнее локальный каталог.

### Config.in

{{include docs/dev-book/examples/package/sdk-hello/Config.in text}}

И строка в общем `board/common/buildroot/Config.in`, чтобы пункт появился в меню:

```text
source "$BR2_EXTERNAL_SDK_PATH/package/sdk-hello/Config.in"
```

### sdk-hello.mk

{{include docs/dev-book/examples/package/sdk-hello/sdk-hello.mk make}}

Разберём:

- Имя переменных — имя пакета заглавными, `-` заменяется на `_`: `sdk-hello` →
  `SDK_HELLO_*`.
- `SITE_METHOD = local` — исходники берутся из каталога (копируются через `rsync` в
  `output/<fw>/buildroot/build/sdk-hello-1.0/`).
- `$(BR2_EXTERNAL_SDK_PATH)` — путь к `board/common/buildroot`, поэтому
  `../../../apps/hello` указывает на `apps/hello` в корне SDK.
- `TARGET_CONFIGURE_OPTS` передаёт `CC`, `CFLAGS`, `LDFLAGS` и прочее для тулчейна
  прошивки. Наш Makefile задаёт их через `?=`, поэтому значения Buildroot побеждают.
- `$(@D)` — каталог сборки пакета, `$(TARGET_DIR)` — будущая rootfs.
- `INSTALL_INIT_SYSV` — установка init-скрипта для busybox init (а для systemd был бы
  `INSTALL_INIT_SYSTEMD`).
- `$(eval $(generic-package))` — «generic» означает «я сам скажу, как собирать».
  Для CMake есть `cmake-package`, для autotools — `autotools-package`, для Meson —
  `meson-package`: им достаточно `SITE` и пары опций.

### Init-скрипт

{{include docs/dev-book/examples/package/sdk-hello/S90sdk-hello bash}}

Busybox init запускает `/etc/init.d/S??*` по порядку имён с аргументом `start` при
загрузке и `stop` при выключении. Номер задаёт порядок: `S10mdev` (устройства),
`S40network` (сеть), ваши службы — после сети, например `S90`.

### Включить и собрать

Пакет, исходники которого лежат в `apps/` (его `*_SITE` указывает туда), SDK считает
**приложением**. Приложения включаются не в defconfig Buildroot платы, а в конфиге
прошивки — переменной `APPS`:

```make
# configs/oga_defconfig
APPS           := bare-app oga-pad sdk-hello
APPS_AUTOSTART := sdk-hello        # нужна опция BR2_PACKAGE_SDK_HELLO_AUTOSTART
```

```bash
make FW=oga apps-list              # какие приложения есть, у кого автозапуск и опции
make FW=oga rootfs image
```

Строку `BR2_PACKAGE_SDK_HELLO=y` в `board/oga/buildroot/defconfig` писать бесполезно:
SDK накладывает поверх него список приложений из `APPS`, и всё, чего там нет,
выключает. Чтобы приложение поддерживало `APPS_AUTOSTART`, дайте ему опцию
`BR2_PACKAGE_<ИМЯ>_AUTOSTART` и ставьте init-скрипт только при ней. Так сделано
у `bare-app` и `oga-pad`. Опции пакета задаются через
`APPS_CONFIG := пакет.ОПЦИЯ=значение`.

Пакеты не из `apps/` (как `esp8089-firmware`) по-прежнему включаются в defconfig
платы: `echo 'BR2_PACKAGE_X=y' >> board/oga/buildroot/defconfig`.

Проверить без железа:

```bash
tar -tvf output/oga/images/rootfs.tar | grep -E 'usr/bin/hello|S90sdk-hello'
```

### Изменили исходник — что пересобрать

!!! danger "Ловушка: `make rootfs` не видит изменений в исходниках"
    Пакет с `SITE_METHOD = local` копирует исходники **один раз** при первой сборке.
    Если поменять `apps/hello/hello.c` и запустить `make rootfs`, Buildroot решит, что
    пакет уже собран, и в rootfs останется **старая** программа. Это проверено:
    после правки строки в `hello.c` обычный `make` оставил старый бинарник, а
    `sdk-hello-rebuild` — подхватил изменение.

```bash
make FW=oga rootfs-make BR=sdk-hello-rebuild    # rsync исходников + сборка + установка
make FW=oga rootfs image
```

### Тот же приём для чужих пакетов: OVERRIDE_SRCDIR

Если нужно поправить пакет из Buildroot (busybox, SDL2…), не трогая архив, укажите
Buildroot свой каталог с исходниками. Файл `output/<fw>/buildroot/local.mk`:

```make
BUSYBOX_OVERRIDE_SRCDIR = /home/you/src/busybox
```

Теперь `busybox-rebuild` будет брать код оттуда. Это локальная настройка вашей
сборки: файл лежит в `output/` и в git не попадает.

## Overlay: просто файлы

Конфигурационные файлы, скрипты, ключи — то, что не надо компилировать, — кладите в
`board/common/buildroot/rootfs-overlay/` с той же структурой каталогов, что в rootfs:

```text
board/common/buildroot/rootfs-overlay/
├── etc/profile.d/sdk.sh          уже есть: приглашение shell
├── etc/init.d/S95myservice       свой init-скрипт (не забудьте chmod +x)
└── root/.ssh/authorized_keys     ключ для SSH (глава 2)
```

Overlay общий для всех плат. Если файл нужен только одной плате — сделайте свой
overlay `board/<плата>/buildroot/rootfs-overlay` и добавьте его в
`BR2_ROOTFS_OVERLAY` defconfig платы через пробел.

!!! warning "Ловушка: удалённые файлы остаются"
    Buildroot никогда не удаляет из `output/<fw>/buildroot/target/` то, что туда уже
    скопировал. Переименовали или удалили файл в overlay — удалите его и из `target/`
    (или `make rootfs-clean rootfs`).

## Быстрая проверка пакета отдельно

Полная сборка rootfs долгая. Пакет можно проверить в отдельной маленькой сборке
Buildroot, которая использует **уже собранный тулчейн** прошивки как внешний:

```text
BR2_aarch64=y
BR2_cortex_a35=y
BR2_TOOLCHAIN_EXTERNAL=y
BR2_TOOLCHAIN_EXTERNAL_CUSTOM=y
BR2_TOOLCHAIN_EXTERNAL_PREINSTALLED=y
BR2_TOOLCHAIN_EXTERNAL_PATH="/home/you/linux-sdk/output/oga/buildroot/host"
BR2_TOOLCHAIN_EXTERNAL_CUSTOM_PREFIX="aarch64-buildroot-linux-gnu"
BR2_TOOLCHAIN_EXTERNAL_GCC_15=y
BR2_TOOLCHAIN_EXTERNAL_HEADERS_7_1=y
BR2_TOOLCHAIN_EXTERNAL_CUSTOM_GLIBC=y
BR2_TOOLCHAIN_EXTERNAL_CXX=y
# BR2_TOOLCHAIN_EXTERNAL_INET_RPC is not set
BR2_PACKAGE_SDK_HELLO=y
```

```bash
make -C src/buildroot O=/tmp/br-test BR2_EXTERNAL=$PWD/board/common/buildroot \
     defconfig BR2_DEFCONFIG=/tmp/br-test.defconfig
make -C src/buildroot O=/tmp/br-test sdk-hello
ls -l /tmp/br-test/target/usr/bin/hello
```

Именно так проверялся пакет из этой главы: сборка заняла меньше минуты. Версии GCC и
заголовков ядра в defconfig должны совпадать с тулчейном (для SDK — GCC 15 и
заголовки 7.1), а строка про `INET_RPC` нужна, потому что в glibc тулчейна нет RPC.
