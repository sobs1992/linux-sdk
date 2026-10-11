# Модули ядра вне дерева

Модуль ядра — код, который загружается в работающее ядро (`insmod`/`modprobe`) и
работает в его адресном пространстве с полными правами. Модуль «вне дерева»
(out-of-tree) живёт в своём каталоге, а не в `src/linux`. Это лучший способ начать:
не нужно пересобирать ядро, цикл «правка — проверка» занимает секунды.

## Главное правило: тот же самый ядро

Модуль собирается **против конкретного собранного ядра** — того, что лежит в
`output/<fw>/linux`. Оттуда берутся конфигурация, заголовки, сгенерированные файлы и
таблица экспортируемых символов (`Module.symvers`). При загрузке ядро сверяет
«vermagic» модуля со своей:

```text
$ modinfo -F vermagic hello.ko
7.2.9-oga SMP preempt mod_unload aarch64           OGA
7.2.9-bbb SMP mod_unload modversions ARMv6 p2v8    BBB
7.2.9-rpi1 mod_unload ARMv6 p2v8                   RPi 1
7.2.9-rpi4 SMP preempt mod_unload aarch64          RPi 4
```

Если версия или ключевые опции не совпадают, `insmod` откажется:
`Invalid module format`. Отсюда правило: **пересобрали ядро — пересоберите модули**.

!!! note "Особенности по платам"
    - **BBB**: в `omap2plus_defconfig` включён `MODVERSIONS` — каждая используемая
      функция ядра проверяется по контрольной сумме. Модуль от «почти такого же»
      ядра не загрузится.
    - **BBB, RPi 1**: в vermagic стоит `ARMv6`. У RPi 1 это родная архитектура, а у BBB —
      следствие того, что `omap2plus_defconfig` поддерживает и старые OMAP2 (ARMv6),
      поэтому ядро собрано с базовым набором инструкций ARMv6.
    - **RPi 1**: одноядерный, без `SMP` и `preempt` — ошибки синхронизации, которые на
      многоядерных платах всплывают сразу, здесь могут годами не проявляться.

## Общий Makefile

Чтобы не повторять в каждом модуле логику «где ядро, какая архитектура, какой
компилятор», в примерах есть общий `module.mk`:

{{include docs/dev-book/examples/kmod/module.mk make}}

В каталоге каждого модуля — два крошечных файла:

```text
Kbuild:    obj-m := hello.o
Makefile:  include ../module.mk
```

`Kbuild` читает система сборки ядра (какие объекты собрать), `Makefile` — вы
(как и для какого ядра собрать). `make -C <каталог O= ядра> M=$(CURDIR)` — стандартный
способ сборки внешнего модуля: каталог `output/<fw>/linux` содержит Makefile-обёртку,
которая ведёт в исходники ядра.

## Пример 1: hello

{{include docs/dev-book/examples/kmod/hello/hello.c}}

```bash
cd docs/dev-book/examples/kmod/hello
make FW=bbb                  # hello.ko для BBB
scp hello.ko root@board:/tmp/
```

```text
# insmod /tmp/hello.ko who=BBB
# dmesg | tail -1
hello: hello, BBB! kernel 7.2.9-bbb on armv7l
# cat /sys/module/hello/parameters/who
BBB
# rmmod hello
```

- `pr_fmt` добавляет префикс `hello: ` ко всем сообщениям модуля.
- `module_param(who, charp, 0444)` делает параметр, который задаётся при загрузке и
  виден в sysfs (только чтение).
- `MODULE_LICENSE("GPL")` обязателен: без него ядро «испортится» (taint) и модулю будут
  недоступны функции, экспортированные как `EXPORT_SYMBOL_GPL`.

## Пример 2: символьное устройство

{{include docs/dev-book/examples/kmod/sdkchar/sdkchar.c}}

```text
# insmod sdkchar.ko
# ls -l /dev/sdkchar                         (младший номер у вас будет свой)
crw-rw-rw-    1 root     root       10, 123 ... /dev/sdkchar
# echo "hello from shell" > /dev/sdkchar
# cat /dev/sdkchar
hello from shell
```

`misc`-устройство — самый простой способ получить файл в `/dev`: ядро само выделит
номер, а mdev создаст узел. `simple_read_from_buffer` и `simple_write_to_buffer` берут
на себя проверку границ и копирование между пространствами пользователя и ядра
(`copy_to_user`/`copy_from_user`). Мьютекс защищает буфер от одновременного доступа
из нескольких процессов.

## Пример 3: логгер кнопок (OGA и любая плата с клавиатурой)

{{include docs/dev-book/examples/kmod/padlog/padlog.c}}

Input handler — «соседний» с evdev обработчик: ядро вызывает `connect()` для каждого
подходящего устройства ввода и `event()` для каждого события. На OGA:

```text
# insmod padlog.ko                           (примерный вывод)
padlog: watching gpio-keys
padlog: watching rk805 pwrkey
# (нажимаем крестовину вверх, затем одну из кнопок A/B/X/Y)
padlog: gpio-keys: code 544 pressed          BTN_DPAD_UP = 0x220
padlog: gpio-keys: code 305 pressed          BTN_EAST    = 0x131
```

Стика (`adc-joystick`) в списке не будет: он посылает только `EV_ABS`, а фильтр
`padlog_ids` пропускает устройства, умеющие `EV_KEY`. Коды смотрите в
`include/uapi/linux/input-event-codes.h`.

На Raspberry Pi 400 тот же модуль будет показывать коды встроенной клавиатуры, на BBB и
RPi — любой подключённой USB-клавиатуры.

!!! warning "Ловушка: контекст"
    `event()` вызывается в атомарном контексте (под спинлоком устройства). В нём
    нельзя спать: никаких `mutex_lock`, `kmalloc(GFP_KERNEL)`, `msleep`. Если нужно
    что-то тяжёлое — отложите в workqueue (как в примере 4).

## Пример 4: драйвер по device tree

Настоящие драйверы не ищут железо сами: они говорят ядру, с какими узлами device tree
работают (`compatible`), а ядро вызывает `probe()`, когда такой узел есть.

{{include docs/dev-book/examples/kmod/sdk-gpio-led/sdk-gpio-led.c}}

Ключевые приёмы:

- `devm_*` — ресурсы, которые ядро освободит само при отвязке драйвера. Не нужно
  писать очистку для каждой ошибки в `probe()`.
- `devm_gpiod_get(dev, "led", ...)` берёт GPIO из свойства `led-gpios` узла.
  Полярность (`GPIO_ACTIVE_LOW`) учитывается автоматически.
- `dev_err_probe()` правильно обрабатывает `-EPROBE_DEFER` (контроллер GPIO ещё не
  готов — ядро попробует позже) и не засоряет лог.
- `delayed_work` — периодическая работа в контексте процесса, где можно спать
  (`gpiod_set_value_cansleep`).
- `MODULE_DEVICE_TABLE(of, ...)` записывает в модуль алиас
  `of:N*T*Csdk,gpio-led`. Когда в DT есть такой узел, mdev при загрузке вызовет
  `modprobe` с этим алиасом, и модуль загрузится сам — если он установлен в образ.

Чтобы драйвер заработал, в device tree платы должен появиться узел `sdk,gpio-led` —
об этом глава 8.

## Модули в образе

Пока модуль копируется руками, он живёт до перепрошивки. Чтобы модуль был в каждом
образе и грузился сам:

```bash
make FW=rpi4 linux                                  # 1. ядро (стирает linux-install!)
make -C docs/dev-book/examples/kmod/sdk-gpio-led FW=rpi4 install   # 2. модуль
make FW=rpi4 image                                  # 3. образ
```

`make install` вызывает `modules_install` ядра: модуль попадает в
`linux-install/modules/lib/modules/7.2.9-rpi4/updates/`, а `depmod` обновляет
`modules.dep` и `modules.alias`. `mkimage.sh` копирует весь этот каталог в rootfs.

### Рецепт: встроить свои модули в SDK

Ручной порядок из трёх команд легко нарушить. Его можно встроить в Makefile SDK — это
не сделано в репозитории, но изменение небольшое. В конфиг прошивки:

```make
LINUX_EXT_MODULES := apps/kmod/sdk-gpio-led apps/kmod/padlog
```

В Makefile SDK, в рецепт цели `linux`, после строки с `modules_install`:

```make
	$(foreach m,$(LINUX_EXT_MODULES),\
	  $(LINUX_MAKE) M=$(call sdkpath,$(m)) modules && \
	  $(LINUX_MAKE) M=$(call sdkpath,$(m)) INSTALL_MOD_PATH=$(LINUX_INSTALL)/modules \
	    INSTALL_MOD_STRIP=1 modules_install &&) true
```

`LINUX_MAKE` уже содержит `-C src/linux O=output/<fw>/linux ARCH=… CROSS_COMPILE=…`;
вызов с `O=` и `M=` одновременно проверен — модуль собирается и ставится в `updates/`.
Тогда `make linux image` всегда даёт образ, в котором ядро и модули согласованы.

## Отладка модулей

- `dmesg -w` в отдельной консоли — смотреть сообщения по ходу.
- `cat /proc/modules`, `lsmod` — что загружено; `modinfo <модуль>` — параметры и алиасы.
- Oops (падение в ядре) печатает стек вызовов с адресами вида `sdkchar_write+0x24/0x90`.
  Строку исходника можно найти на ПК:

```bash
aarch64-linux-gnu-objdump -dS sdkchar.ko | less        # дизассемблер с исходником
src/linux/scripts/decode_stacktrace.sh output/oga/linux/vmlinux \
    src/linux docs/dev-book/examples/kmod/sdkchar < oops.txt
```

Отладочная информация (`CONFIG_DEBUG_INFO`) включена во всех ядрах SDK, поэтому
`vmlinux` и модули содержат номера строк.
