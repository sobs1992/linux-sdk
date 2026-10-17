# Гибридный образ для OGA

Задача: одна SD-карта, которая грузится и на консоли с заводским загрузчиком во SPI,
и на консоли с пустым SPI. Для этого на карте должны лежать **обе** цепочки:

<figure>
<svg viewBox="0 0 640 170" xmlns="http://www.w3.org/2000/svg" font-family="Noto Sans, sans-serif" font-size="10">
  <defs><marker id="c" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" fill="#555"/></marker></defs>
  <g stroke="#4a6587" fill="#eef3f9"><rect x="10" y="62" width="80" height="40" rx="3"/></g>
  <g stroke="#b5651d" fill="#fbf3e6">
    <rect x="130" y="15" width="110" height="36" rx="3"/><rect x="270" y="15" width="100" height="36" rx="3"/>
    <rect x="400" y="15" width="100" height="36" rx="3"/>
  </g>
  <g stroke="#2c7343" fill="#edf7ef">
    <rect x="130" y="112" width="70" height="36" rx="3"/><rect x="215" y="112" width="70" height="36" rx="3"/>
    <rect x="300" y="112" width="90" height="36" rx="3"/><rect x="400" y="112" width="100" height="36" rx="3"/>
  </g>
  <g stroke="#4a6587" fill="#eef3f9"><rect x="540" y="62" width="90" height="40" rx="3"/></g>
  <g fill="#14213d" text-anchor="middle">
    <text x="50" y="80" font-weight="bold">BootROM</text><text x="50" y="94" font-size="8">SPI → … → SD</text>
    <text x="185" y="30" font-weight="bold">SPI: DDR-блоб</text><text x="185" y="43" font-size="8">+ miniloader (rkbin)</text>
    <text x="320" y="30" font-weight="bold">trust.img</text><text x="320" y="43" font-size="8">BL31 rkbin, SD@24576</text>
    <text x="450" y="30" font-weight="bold">uboot.img</text><text x="450" y="43" font-size="8">mainline, SD@16384</text>
    <text x="165" y="127" font-weight="bold">TPL</text><text x="165" y="140" font-size="8">SD@64</text>
    <text x="250" y="127" font-weight="bold">SPL</text><text x="250" y="140" font-size="8">SD@64</text>
    <text x="345" y="127" font-weight="bold">BL31 TF-A</text><text x="345" y="140" font-size="8">FIT SD@2048</text>
    <text x="450" y="127" font-weight="bold">U-Boot</text><text x="450" y="140" font-size="8">FIT SD@2048</text>
    <text x="585" y="80" font-weight="bold">Linux</text><text x="585" y="94" font-size="8">extlinux, BOOT</text>
  </g>
  <g stroke="#555" fill="none" marker-end="url(#c)">
    <path d="M90 74 L128 36"/><path d="M240 33 L268 33"/><path d="M370 33 L398 33"/><path d="M500 33 L538 72"/>
    <path d="M90 90 L128 128"/><path d="M200 130 L213 130"/><path d="M285 130 L298 130"/><path d="M390 130 L398 130"/><path d="M500 130 L538 92"/>
  </g>
  <text x="130" y="10" fill="#b5651d" font-size="9">заводской SPI-загрузчик есть</text>
  <text x="130" y="165" fill="#2c7343" font-size="9">SPI пустой: полностью открытая цепочка</text>
</svg>
<figcaption>Рис. 12.1. Две цепочки загрузки на одной карте</figcaption>
</figure>

## Разметка

```text
сектор 64      u-boot-rockchip.bin: idbloader (TPL+SPL)        ← mainline
сектор 2048    u-boot.itb (FIT: U-Boot + TF-A BL31 + dtb)      ← mainline, перенесён
сектор 16384   uboot.img  (U-Boot в формате Rockchip)          ← для miniloader
сектор 24576   trust.img  (BL31 в формате Rockchip)            ← для miniloader
сектор 32768   раздел BOOT
```

Конфликт был один: и SPL, и miniloader хотят свой файл по сектору 16384. Miniloader
изменить нельзя (он во SPI, закрытый), а SPL — можно.

### Перенос FIT

{{include board/oga/u-boot/oga.config}}

- `CONFIG_SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR=0x800` — SPL ищет FIT в секторе 2048 (1 МиБ).
- `CONFIG_SPL_PAD_TO` — смещение FIT **внутри** `u-boot-rockchip.bin`. Файл пишется
  с сектора 64, значит смещение в нём = `(0x800 − 0x40) × 512 = 0xF8000`.

Откуда известно, что binman берёт именно `SPL_PAD_TO`? Из описания образа:

```bash
grep -n -B2 -A6 'SPL_PAD_TO' src/u-boot/arch/arm/dts/rockchip-u-boot.dtsi
#   u-boot-img { offset = <CONFIG_SPL_PAD_TO>; };
```

По умолчанию `SPL_PAD_TO=0x7f8000` = `(0x4000 − 0x40) × 512` — это и есть «FIT по
сектору 16384». Две опции **связаны**, и менять их нужно вместе. Если поменять только
сектор, SPL будет искать FIT там, где его нет.

## Форматы Rockchip

### uboot.img

Это бинарник U-Boot с заголовком `LOADER  `: адрес загрузки, размер, CRC и хеш.
Miniloader проверяет заголовок, кладёт U-Boot по адресу из заголовка и запоминает
его как BL33. Упаковывает утилита `loaderimage` из rkbin:

```bash
loaderimage --pack --uboot output/oga/u-boot/u-boot-dtb.bin uboot.img 0x00800000
```

Адрес — **`CONFIG_TEXT_BASE`** нашего U-Boot: тот адрес, по которому он слинкован.
Скрипт берёт его из `.config` автоматически. У рабочего `uboot.img` Hardkernel адрес
был `0x200000` — их U-Boot слинкован иначе. Взять «как у них» было бы ошибкой.

```text
$ loaderimage --info uboot.img          (наш)      $ loaderimage --info uboot.img  (Hardkernel)
Load Addr is 0x800000                              Load Addr is 0x200000
```

`u-boot-dtb.bin` — U-Boot proper с приклеенным **одним** dtb (по умолчанию
`rk3326-odroid-go2`, rev 1.0). В mainline-цепочке SPL выбирает dtb из FIT по ревизии,
а здесь SPL нет. Это не страшно: драйверы, нужные U-Boot (SD, UART, ADC), у всех
ревизий одинаковые, а `fdtfile` для **ядра** go2.c всё равно ставит по АЦП —
и в логе видно, что для BE выбран `rk3326-odroid-go2-v11.dtb`.

### trust.img

Контейнер с заголовком `BL3X` для BL31 (и опционально BL32). Собирается утилитой
`trust_merger` по ini-файлу:

```ini
[BL31_OPTION]
SEC=1
PATH=/abs/path/rk3326_bl31_v1.34.elf
ADDR=0x00040000
[BL32_OPTION]
SEC=0
```

`ADDR` — точка входа BL31. Её стоит проверить, а не копировать из примера:

```bash
aarch64-linux-gnu-readelf -h rk3326_bl31_v1.34.elf | grep Entry   # 0x40000
```

### Почему BL31 от Rockchip, а не mainline

Mainline TF-A ждёт параметры от BL2 в формате, который ей передаёт U-Boot SPL.
Miniloader передаёт параметры в своём формате, и будет ли mainline TF-A с ним
работать — не проверено. BL31 из rkbin гарантированно работает с miniloader:
Hardkernel использует именно эту пару.

### Почему без BL32

В rkbin-шаблоне `RK3326TRUST.ini` есть BL32 (OP-TEE) по адресу `0x08400000`. Его
не включили. OP-TEE занимает кусок DRAM и закрывает его аппаратно (TrustZone).
Ядро должно знать об этой области (узел `reserved-memory` в device tree), иначе
оно может обратиться к защищённой памяти и упасть. В mainline-DTS PX30 такого узла
нет — это легко проверить: `grep -n 'reserved-memory\|optee' px30.dtsi rk3326*.dtsi`
ничего не находит. Без BL32 этой проблемы нет, а OP-TEE нашему SDK не нужен.

## Скрипт упаковки

{{include scripts/rk-legacy-pack.sh}}

`trust_merger` запускается из рабочего каталога, потому что пишет временные файлы
рядом с собой. Пути в ini — абсолютные (`realpath`).

В конфиге прошивки всё включается тремя переменными (`RK_LEGACY`, `RKBIN_DIR`,
`RK_TRUST_BL31`), а в `IMAGE_RAW` при `RK_LEGACY=y` добавляются два блоба:

```make
IMAGE_RAW  := $(IMAGES_DIR)/u-boot-rockchip.bin@64
ifeq ($(RK_LEGACY),y)
IMAGE_RAW  += $(IMAGES_DIR)/uboot.img@16384 $(IMAGES_DIR)/trust.img@24576
endif
```

## Проверка

```bash
I=output/oga/images
loaderimage --info $I/uboot.img                  # Load Addr is 0x800000
xxd -l 16 $I/uboot.img                           # 4c4f 4144 4552 2020  "LOADER  "
xxd -l 16 $I/trust.img                           # 424c 3358            "BL3X"
for b in u-boot-rockchip.bin@64 uboot.img@16384 trust.img@24576; do
  f=${b%@*} s=${b#*@}
  dd if=$I/oga.img bs=512 skip=$s count=$(( ($(stat -c%s $I/$f)+511)/512 )) status=none |
    cmp -n $(stat -c%s $I/$f) - $I/$f && echo "$f @ $s OK"
done
dd if=$I/oga.img bs=512 skip=2048 count=1 status=none | xxd -l 4   # d00dfeed: FIT
```

Формат заголовков сравнили с рабочими `uboot.img`/`trust.img` Hardkernel: та же
сигнатура и структура.

## Результат

Карту перепрошили только в загрузочной области (раздел BOOT и rootfs не менялись) —
и консоль загрузилась. Ключевые строки лога UART (сначала короткий мусор от
miniloader на 1,5 Мбод, дальше всё читаемо на 115200):

```text
U-Boot 2026.07 (Oct 06 2026 - 22:29:26 +0200)
Model: ODROID-GO Advance
DRAM:  1 GiB (total 1022 MiB)
** Booting bootflow 'mmc@ff370000.bootdev.part_1' with extlinux
Retrieving file: /Image
Retrieving file: /rockchip/rk3326-odroid-go2-v11.dtb
Starting kernel ...
[    0.000000] Linux version 7.2.9-oga ...
[    0.000000] Machine model: ODROID-GO Advance Black Edition
[    3.588084] VFS: Mounted root (ext4 filesystem) on device 179:2.
[    3.619962] Run /sbin/init as init process
Welcome to ODROID-GO Advance
odroid-go login:
```

Что тут подтверждается:

- `DRAM: 1 GiB` — U-Boot правильно узнал размер памяти, хотя DDR инициализировал
  не наш TPL, а DDR-блоб Rockchip;
- `rk3326-odroid-go2-v11.dtb` — go2.c определил Black Edition по АЦП;
- `Machine model: ... Black Edition` — ядро получило правильный dtb;
- `Mounted root ... 179:2` — PARTUUID сработал;
- загорелся синий светодиод, на экране — лог и приглашение.

Безобидные строки в том же логе:

| Строка | Почему не страшно |
|---|---|
| `Loading Boot0000 'mmc 0' failed` | U-Boot сначала пробует EFI-загрузку, не находит и идёт к extlinux |
| `mmc0: error -110 whilst initialising SD card` | первая попытка инициализации SD, вторая успешна |
| `FAT-fs (mmcblk0p1): Volume was not properly unmounted` | раздел был смонтирован на ПК при записи |
