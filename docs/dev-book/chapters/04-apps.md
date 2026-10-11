# Свои программы

## Самая короткая дорога

{{include docs/dev-book/examples/app/hello/hello.c}}

```bash
SDK=~/linux-sdk; FW=oga
export PATH=$SDK/output/$FW/buildroot/host/bin:$PATH
aarch64-buildroot-linux-gnu-gcc -O2 -g -Wall -o hello hello.c
file hello      # ELF 64-bit LSB pie executable, ARM aarch64 ...
scp hello root@board:/tmp/ && ssh root@board /tmp/hello
```

На плате:

```text
Hello from odroid-go: aarch64, kernel 7.2.9-oga
```

## Makefile-проект

Свой Makefile пишите так, чтобы компилятор и флаги **можно было переопределить**
снаружи (`?=`), а установка шла в `$(DESTDIR)`. Тогда один и тот же Makefile работает
и для сборки руками, и внутри пакета Buildroot (глава 6):

{{include docs/dev-book/examples/app/hello/Makefile}}

```bash
make CC=aarch64-buildroot-linux-gnu-gcc
make CC=aarch64-buildroot-linux-gnu-gcc DESTDIR=/srv/nfs/rpi4 install   # прямо в NFS-корень
```

## CMake-проект

{{include docs/dev-book/examples/app/cmake-demo/CMakeLists.txt}}

Buildroot кладёт готовый toolchain-файл для CMake в `host/share/buildroot/`:

```bash
cmake -S cmake-demo -B build-oga \
      -DCMAKE_TOOLCHAIN_FILE=$SDK/output/oga/buildroot/host/share/buildroot/toolchainfile.cmake
cmake --build build-oga
```

Toolchain-файл задаёт компилятор, sysroot и флаги процессора (`-mcpu=cortex-a35`
и т. п.), так что `find_package()` и `pkg-config` ищут библиотеки в sysroot
прошивки, а не на ПК.

## Библиотеки

Программа может использовать только те библиотеки, которые **есть в rootfs**. Если
нужна библиотека, которой нет (например, `libgpiod2`, `sdl2`, `libevdev`), сначала
включите её в Buildroot (глава 6): после `make rootfs` её заголовки и `.so` появятся
в sysroot (`output/<fw>/buildroot/staging/`), а `.so` — ещё и в rootfs.

Флаги для компиляции и линковки даёт `pkg-config` из того же `host/bin`. Это обёртка
Buildroot, которая уже знает про sysroot:

```bash
aarch64-buildroot-linux-gnu-gcc app.c -o app $(pkg-config --cflags --libs libgpiod)
```

!!! warning "Ловушка: системный pkg-config"
    Если в `PATH` раньше стоит системный `/usr/bin/pkg-config`, он вернёт пути к
    библиотекам ПК (`-I/usr/include`), и сборка либо упадёт, либо — хуже — соберётся
    с чужими заголовками. Проверяйте: `which pkg-config` должен указывать в `host/bin`.

## Отладка

### gdbserver по сети

В rootfs есть `gdbserver` (`BR2_PACKAGE_GDB=y`), а на ПК — `<префикс>-gdb`
(`BR2_PACKAGE_HOST_GDB=y`), собранный под эту архитектуру.

```bash
# плата
gdbserver :2345 /tmp/hello

# ПК
aarch64-buildroot-linux-gnu-gdb hello
(gdb) set sysroot /home/you/linux-sdk/output/oga/buildroot/staging
(gdb) target remote 192.168.1.57:2345
(gdb) break main
(gdb) continue
```

`set sysroot` нужен, чтобы gdb нашёл на ПК те же библиотеки (`libc.so.6` и др.),
что загружены на плате, — с отладочной информацией.

### gdbserver по UART (OGA)

У OGA нет сети, зато на разъёме расширения P2 выведен второй UART (`ttyS1`,
контакты 2 — RXD, 3 — TXD). gdbserver умеет работать через последовательный порт:

```bash
# плата (ttyS1 — разъём P2; не консольный ttyS2!)
gdbserver /dev/ttyS1 /tmp/hello

# ПК, второй USB-UART адаптер на P2
aarch64-buildroot-linux-gnu-gdb hello
(gdb) set serial baud 115200
(gdb) target remote /dev/ttyUSB1
```

!!! note "Скорость ttyS1"
    gdbserver не меняет скорость порта. Выставьте её заранее:
    `stty -F /dev/ttyS1 115200 raw`.

### strace и журнал

- `strace` (пакет `BR2_PACKAGE_STRACE`) показывает системные вызовы: незаменим,
  когда программа «молча» не работает (`strace -f ./app 2>&1 | grep -E 'ENOENT|EACCES'`).
- Вывод в системный журнал — `logger -t myapp "текст"`, читать — `/var/log/messages`
  (busybox syslogd пишет в файл; `logread` в конфигурации busybox Buildroot выключен).
- Сообщения ядра — `dmesg`, по ходу работы — `dmesg -w`.

## Что важно помнить

- Собирайте **тулчейном прошивки**, а не системным: у них разные glibc.
- Не путайте `host/bin` BBB и RPi 1: префикс одинаковый, ISA разная.
- Отладочная информация (`-g`) не мешает: для rootfs Buildroot сам вырезает её при
  установке пакета, а при копировании руками можно сделать
  `<префикс>-strip hello`.
