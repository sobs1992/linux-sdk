# Карта разработки

Прежде чем писать код, полезно знать **где** будет жить каждое изменение, **что**
придётся пересобрать и **как** доставить результат на плату. Неправильный ответ на
любой из этих вопросов превращает пятиминутную правку в час возни.

## Где живут изменения

| Что меняете | Где хранить | Попадает на плату через |
|---|---|---|
| Своя программа, в разработке | где угодно, кросс-компиляция руками | `scp`, UART, картридер |
| Своя программа, готовая | `apps/<имя>/` + пакет в `board/common/buildroot/package/` | `make rootfs image` |
| Готовый пакет из Buildroot (strace, sdl2…) | `board/<плата>/buildroot/defconfig` | `make rootfs image` |
| Конфиги и скрипты в rootfs | `board/common/buildroot/rootfs-overlay/` | `make rootfs image` |
| Модуль ядра вне дерева | свой каталог (см. `examples/kmod/`) | `insmod` вручную или `make image` |
| Опции ядра | фрагмент `board/<плата>/linux/*.config` | `make linux image` |
| Драйвер, правка ядра | `src/linux`, ветка `oga` | `make linux image` |
| Узел device tree | `src/linux` (dts платы) или overlay | `make linux image` / `flash-boot` |
| Опции U-Boot | фрагмент `board/<плата>/u-boot/*.config` | `make uboot image` + `flash-boot` |
| Код U-Boot | `src/u-boot`, ветка `oga` | `make uboot image` + `flash-boot` |
| Аргументы ядра | `LINUX_CMDLINE` в конфиге прошивки | `make image` + `flash-boot` |

Общее правило: **плата описывается в `board/` и `configs/`, код — в сабмодулях,
результат — только в `output/`**. Ничего не правьте в `output/` руками, кроме
экспериментов, которые не жалко потерять.

## Что пересобирать

| После правки в | Команда | Сколько времени |
|---|---|---|
| программе (руками) | `$CC ...` | секунды |
| пакете Buildroot | `make rootfs-make BR=<пакет>-rebuild && make rootfs image` | минута |
| overlay | `make rootfs image` | минута |
| модуле вне дерева | `make` в каталоге модуля | секунды |
| ядре | `make linux image` | от минуты (инкрементально) до 20 минут |
| U-Boot | `make uboot image` | 1–2 минуты |
| конфиге прошивки | зависит от переменной; `make image` всегда | |

!!! warning "Ловушка: `make linux` стирает `linux-install/`"
    Цель `linux` очищает `output/<fw>/linux-install/` и ставит туда модули заново.
    Модули вне дерева, установленные туда раньше (`make install` в каталоге модуля),
    пропадут. Порядок всегда такой: `make linux` → установка своих модулей →
    `make image`. В главе 7 есть рецепт, как встроить это в SDK.

## Как доставить на плату

| Способ | Что меняет | OGA | BBB | RPi 1 | RPi 4/400 |
|---|---|---|---|---|---|
| `make flash` | всё | ✓ | ✓ | ✓ | ✓ |
| `make flash-boot` | загрузчик + ядро + dtb | ✓ | ✓ | ✓ | ✓ |
| Картридер: файлы на BOOT (FAT) | ядро, dtb, extlinux.conf, config.txt | ✓ | ✓ | ✓ | ✓ |
| Картридер: файлы в rootfs (ext4, `sudo mount`) | любые файлы | ✓ | ✓ | ✓ | ✓ |
| `scp` по сети (dropbear) | файлы | USB-Ethernet | ✓ | B/B+ | ✓ |
| UART: `sz`/`rz` (lrzsz) | небольшие файлы | ✓ | ✓ | ✓ | ✓ |
| TFTP + NFS (глава 3) | ядро и весь rootfs без перепрошивки | — | ✓ | B/B+ | ✓ |

!!! warning "Какую плату пишет `make flash`"
    Цели `flash` и `flash-boot` работают с **выбранной** прошивкой — из файла
    `output/.fw`, который пишет `make <fw>_defconfig`. Если вы собирали другую плату
    через `FW=bbb`, пишите её так же: `make FW=bbb flash DEV=/dev/sdX`. Проверить выбор —
    `make info`.

Для повседневной разработки программ удобнее всего сеть (`scp` или NFS). Для ядра и
загрузчика — `flash-boot` или сетевая загрузка ядра по TFTP.

## Цикл разработки

<figure>
<svg viewBox="0 0 640 120" xmlns="http://www.w3.org/2000/svg" font-family="Noto Sans, sans-serif" font-size="10">
  <defs><marker id="m" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="#555"/></marker></defs>
  <g stroke="#4a6587" fill="#eef3f9">
    <rect x="10" y="40" width="100" height="40" rx="4"/><rect x="140" y="40" width="100" height="40" rx="4"/>
    <rect x="270" y="40" width="100" height="40" rx="4"/><rect x="400" y="40" width="100" height="40" rx="4"/>
    <rect x="530" y="40" width="100" height="40" rx="4"/>
  </g>
  <g text-anchor="middle" fill="#14213d">
    <text x="60" y="58" font-weight="bold">правка</text><text x="60" y="71" font-size="8">src/, apps/, board/</text>
    <text x="190" y="58" font-weight="bold">сборка</text><text x="190" y="71" font-size="8">make &lt;компонент&gt;</text>
    <text x="320" y="58" font-weight="bold">доставка</text><text x="320" y="71" font-size="8">scp / flash-boot / NFS</text>
    <text x="450" y="58" font-weight="bold">проверка</text><text x="450" y="71" font-size="8">UART, dmesg, gdb</text>
    <text x="580" y="58" font-weight="bold">коммит</text><text x="580" y="71" font-size="8">ветка oga / SDK</text>
  </g>
  <g stroke="#555" marker-end="url(#m)" fill="none">
    <line x1="110" y1="60" x2="138" y2="60"/><line x1="240" y1="60" x2="268" y2="60"/>
    <line x1="370" y1="60" x2="398" y2="60"/><line x1="500" y1="60" x2="528" y2="60"/>
    <path d="M450 40 C450 10, 60 10, 60 38"/>
  </g>
  <text x="255" y="22" fill="#555" font-size="9">не работает — назад к правке</text>
</svg>
<figcaption>Рис. 1.1. Цикл разработки</figcaption>
</figure>

Самая дорогая часть цикла — доставка. Главы 2 и 3 посвящены тому, чтобы сократить
её с «вынуть карту, прошить, вставить» до одной команды.
