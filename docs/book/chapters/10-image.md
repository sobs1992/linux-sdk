# Образ SD-карты

Все компоненты собраны по отдельности. Теперь их нужно разложить на «виртуальную
SD-карту» — файл `.img`, который потом побайтово пишется на настоящую карту.
Делает это `scripts/mkimage.sh`, и делает **без root**.

## Разметка

<figure>
<svg viewBox="0 0 640 120" xmlns="http://www.w3.org/2000/svg" font-family="Noto Sans, sans-serif" font-size="9">
  <rect x="10" y="20" width="14" height="44" fill="#c9d6e8" stroke="#4a6587"/>
  <rect x="24" y="20" width="14" height="44" fill="#f2e0c9" stroke="#7a5a2f"/>
  <rect x="38" y="20" width="22" height="44" fill="#e7d3f1" stroke="#6b4a8a"/>
  <rect x="60" y="20" width="30" height="44" fill="#d9ead9" stroke="#2c7343"/>
  <rect x="90" y="20" width="30" height="44" fill="#fbe4d5" stroke="#b5651d"/>
  <rect x="120" y="20" width="30" height="44" fill="#fbe4d5" stroke="#b5651d"/>
  <rect x="150" y="20" width="180" height="44" fill="#e8f0fa" stroke="#4a6587"/>
  <rect x="330" y="20" width="300" height="44" fill="#eef7ee" stroke="#2c7343"/>
  <g text-anchor="middle" fill="#14213d">
    <text x="17" y="80">MBR</text><text x="31" y="92">env</text><text x="49" y="80">idb</text>
    <text x="75" y="92">itb</text><text x="105" y="80">uboot.img</text><text x="135" y="92">trust.img</text>
    <text x="240" y="40" font-size="11" font-weight="bold">p1 FAT32 BOOT</text><text x="240" y="54">Image, dtb, extlinux</text>
    <text x="480" y="40" font-size="11" font-weight="bold">p2 ext4 rootfs</text><text x="480" y="54">rootfs.tar + модули</text>
  </g>
  <g fill="#555" font-size="8">
    <text x="10" y="14">0</text><text x="20" y="14">16K</text><text x="36" y="14">32K</text><text x="58" y="14">1M</text>
    <text x="88" y="14">8M</text><text x="118" y="14">12M</text><text x="146" y="14">16M</text><text x="320" y="14">144M</text>
  </g>
  <text x="10" y="112" fill="#555">Масштаб условный. Сырые области (слева) у каждой платы свои и задаются IMAGE_RAW; разделы — общие для всех.</text>
</svg>
<figcaption>Рис. 10.1. Разметка образа OGA</figcaption>
</figure>

| Где | Что | Кто читает |
|---|---|---|
| сектор 0 | MBR: таблица разделов, disk id | все |
| 16–32 КиБ | окружение U-Boot (`saveenv`) | U-Boot |
| `IMAGE_RAW` (до 16 МиБ) | сырые блобы загрузчика | BootROM, SPL, miniloader |
| 16 МиБ | p1, FAT32, метка `BOOT`, активный | U-Boot, прошивка RPi, ROM BBB |
| дальше | p2, ext4, метка `rootfs` | ядро (`root=PARTUUID=…-02`) |

### Почему MBR, а не GPT

GPT — современный формат, но занимает сектора 1–33 (заголовок и таблица записей) и
ещё копию в конце диска. На Rockchip окружение U-Boot по умолчанию лежит с 16 КиБ
(сектор 32) — пересечение. Кроме того, ROM AM335x ищет **активный** (bootable)
раздел в MBR, а Raspberry Pi 1–3 вообще понимают только MBR. MBR занимает один
сектор и подходит всем.

### Почему FAT для BOOT

FAT читают U-Boot, ROM AM335x (`MLO` с FAT) и прошивка Raspberry Pi (`config.txt`,
`start.elf`). И его можно открыть на любом ПК, чтобы поправить `extlinux.conf`.

### Почему 16 МиБ до первого раздела

Это запас на все сырые блобы. Самая «толстая» раскладка — у OGA: `trust.img` с
сектора 24576 (12 МиБ) занимает 4 МиБ и кончается ровно на 16 МиБ.

## mkimage.sh по шагам

Скрипт получает всё через переменные окружения (их выставляет `make image`) и
проходит четыре шага.

### 1. Проверки и сырые блобы

{{include scripts/mkimage.sh 24-52}}

`set -euo pipefail` (в начале файла) останавливает скрипт на первой ошибке, на
неопределённой переменной и на ошибке внутри конвейера.

`IMAGE_RAW` — список вида `файл@сектор`. Скрипт сортирует блобы по сектору и
проверяет, что они не перекрывают друг друга и первый раздел. Это защита от ошибки,
которая погубила прошлую попытку (глава 3). Размер блобов зависит от раскладки:
`u-boot-rockchip.bin` весит ≈ 9 МиБ, когда FIT лежит на 8 МиБ, и ≈ 2 МиБ, когда на
1 МиБ. Сдвинули одно — и без проверки легко не заметить, что блоб налез на соседний.

### 2. Раздел BOOT

{{include scripts/mkimage.sh 54-93}}

- Ядро, dtb и `IMAGE_BOOT_FILES` складываются в каталог.
- Раскладка dtb (`DTB_LAYOUT`) зависит от того, как U-Boot платы строит `fdtfile`:
  `rockchip/rk3326-odroid-go2-v11.dtb` (с каталогом) у OGA, `am335x-boneblack.dtb`
  (без каталога) у BBB. Конструкция `;;&` в `case` значит «выполнить и проверить
  следующие шаблоны» — так `both` выполняет обе ветки.
- `extlinux.conf` минимальный: одна метка, `fdtdir /`, корень по PARTUUID.
- `mkfs.vfat -C` **создаёт файл** нужного размера с файловой системой, а `mcopy` из
  пакета mtools копирует в него файлы — без `mount` и без root. Серийный номер тома
  (`-i`) — тот же disk id, просто для красоты.

### 3. Раздел rootfs

{{include scripts/mkimage.sh 95-114}}

Это самая интересная часть. Rootfs должна содержать файлы, принадлежащие root
(`/bin/busybox` с битом setuid, `/root`, `/etc/shadow`…). Обычный пользователь не
может создать файл, принадлежащий root. Решение — **fakeroot**: он перехватывает
вызовы `chown`, `stat` и т. п. и **запоминает** «как будто» установленных владельцев.
Внутри одной сессии fakeroot:

1. `tar -xp` распаковывает `rootfs.tar` с владельцами из архива (fakeroot их запомнит);
2. в `/lib/modules` копируются модули ядра и «отдаются» root;
3. в `/etc/fstab` дописывается строка для `/boot` по метке;
4. `mke2fs -d <каталог>` создаёт ext4 **сразу с содержимым**. Он читает владельцев
   через `stat` — а fakeroot отвечает «root».

Все четыре шага должны идти **в одной** сессии fakeroot: между сессиями память о
владельцах теряется (если не использовать файл состояния `-s`/`-i`).

Размер раздела — содержимое плюс 10 % плюс `IMAGE_ROOTFS_FREE_MB` свободного места.

### 4. Сборка диска

{{include scripts/mkimage.sh 116-148}}

- `truncate` создаёт разреженный файл нужного размера (на диске почти не занимает места).
- `sfdisk` умеет работать с обычным файлом как с диском: записывает MBR с disk id
  `label-id` и двумя разделами; у первого — флаг `bootable`.
- `dd ... oflag=seek_bytes conv=notrunc` кладёт каждый кусок по точному байтовому
  смещению, не обрезая файл. `bs=1M` с `seek` в байтах — быстро и без арифметики
  в блоках.
- `boot-area.bin` — всё от первого сырого блоба до конца раздела BOOT. Его пишет
  `make flash-boot`, чтобы обновить загрузчик и ядро, не трогая rootfs.

## PARTUUID и LABEL

Ядро должно найти rootfs, а init — раздел BOOT. Варианты:

| Способ | Пример | Плюсы и минусы |
|---|---|---|
| Имя устройства | `root=/dev/mmcblk0p2` | зависит от порядка инициализации контроллеров |
| PARTUUID | `root=PARTUUID=4f474131-02` | понимает **ядро** без initramfs; для MBR = disk id + номер раздела |
| UUID ФС | `root=UUID=...` | ядро без initramfs **не** понимает |
| LABEL | `LABEL=BOOT` в fstab | понимает `mount` (busybox — с `FEATURE_MOUNT_LABEL`) |

Поэтому: корень — по PARTUUID (его разбирает само ядро), `/boot` в fstab — по метке
(её разбирает `mount`). Disk id задаётся в конфиге (`IMAGE_DISK_ID`), разный у
разных плат — так их образы легко различить.

## Проверка образа без железа

Прежде чем писать на карту, образ стоит проверить. Всё делается без root:

```bash
O=output/oga
sfdisk -l $O/images/oga.img                              # таблица разделов
mdir -i $O/image-work/boot.vfat -/ ::/                   # что в BOOT
mtype -i $O/image-work/boot.vfat ::/extlinux/extlinux.conf
debugfs -R 'cat /etc/fstab' $O/image-work/rootfs.ext4    # файл из ext4
debugfs -R 'ls -l /lib/modules' $O/image-work/rootfs.ext4
# загрузчик лежит там, где надо?
dd if=$O/images/oga.img bs=512 skip=64 count=$(( $(stat -c%s $O/images/u-boot-rockchip.bin)/512 )) \
   status=none | cmp - $O/images/u-boot-rockchip.bin && echo "u-boot @64 OK"
dd if=$O/images/oga.img bs=512 skip=2048 count=1 status=none | xxd -l 8   # d00dfeed = FIT
```

!!! tip "Совет: прогон на фиктивном rootfs"
    Пока Buildroot собирается (а это час), скрипт образа можно отладить на пустышке:
    `mkdir -p fake/{bin,etc} && tar -C fake -cf fake.tar .` и запустить
    `mkimage.sh` с `ROOTFS_TAR=fake.tar`. Ошибки в разметке всплывут за секунды.
    Именно так в проекте нашли, что в системе нет `mcopy` (пакет `mtools`).

!!! note "Сигнатуры, которые полезно знать"
    `d0 0d fe ed` — FIT или dtb (это одна и та же структура). `3b 8c dc fc` — начало
    idbloader Rockchip (заголовок зашифрован RC4, и так выглядит его первая часть).
    `LOADER  ` — `uboot.img` формата Rockchip; `BL3X` — `trust.img` (глава 12);
    `55 aa` в конце сектора 0 — сигнатура MBR.

## Запись на карту

{{include scripts/flash.sh}}

Запись на неправильное устройство — самая дорогая ошибка в этой области, поэтому
скрипт осторожен:

- отказывается писать на раздел (`/dev/sda1`) вместо диска;
- отказывается писать на **несъёмный** диск (не `RM=1`, не USB, не `mmcblk`);
- отказывается, если на устройстве смонтирован `/`, `/boot`, `/home`…;
- показывает `lsblk` и требует набрать `yes`;
- отмонтирует разделы карты, пишет с `conv=fsync` и делает `sync`.

```bash
make flash DEV=/dev/sdX          # весь образ
make flash-boot DEV=/dev/sdX     # только загрузчик + BOOT (rootfs остаётся)
```

!!! warning "Ловушка: образ какой платы будет записан"
    `make flash` пишет образ **выбранной** прошивки — той, что записана в
    `output/.fw` последней командой `make <fw>_defconfig`. `FW=<fw>` в командной строке
    действует только на одну команду и выбор не меняет. Образы разных плат лежат
    рядом (`output/oga/images/oga.img`, `output/bbb/images/bbb.img`,
    `output/rpi1/images/rpi1.img`, `output/rpi4/images/rpi4.img`), поэтому легко
    собрать одну плату через `FW=`, а записать — другую.

    ```bash
    make info                                       # строка Firmware: — что выбрано
    make FW=rpi4 flash DEV=/dev/sdX                 # записать rpi4 разово
    make rpi4_defconfig && make flash DEV=/dev/sdX  # переключиться на rpi4 насовсем
    ```

!!! danger "Опасно"
    Перед `make flash` проверьте `lsblk`: какое устройство появилось, когда вы
    вставили карту. `/dev/sda` на одной машине — SD-кардридер, на другой — системный
    диск.
