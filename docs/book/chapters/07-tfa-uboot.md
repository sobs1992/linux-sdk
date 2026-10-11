# TF-A и U-Boot

## TF-A: BL31 для PX30

RK3326 в TF-A — это платформа `px30` (RK3326 — вариант PX30). Проверить, что
платформа поддерживается, можно просто по наличию каталога:

```bash
ls src/tf-a/plat/rockchip/px30
```

Сборка одной командой (её и выполняет `make tfa`):

```bash
make -C src/tf-a BUILD_BASE=output/oga/tf-a PLAT=px30 \
     CROSS_COMPILE=aarch64-linux-gnu- bl31
# результат: output/oga/tf-a/px30/release/bl31/bl31.elf
```

U-Boot нужен именно **ELF**, а не `.bin`: binman разбирает ELF на сегменты и кладёт
каждый в FIT со своим адресом загрузки (те самые `atf-1`, `atf-2`, `atf-3` из главы 1).

### Скорость консоли TF-A

В `plat/rockchip/px30/px30_def.h` написано `#define PX30_BAUDRATE 1500000` —
стандарт Rockchip. Но в `plat/rockchip/common/params_setup.c` TF-A читает
`stdout-path` из device tree, который ей передаёт SPL, и берёт скорость оттуда.
В DTS OGA стоит `serial2:115200n8`, поэтому TF-A печатает на 115200.

!!! tip "Как выяснять такие вещи"
    `grep -rn -i 'baud' src/tf-a/plat/rockchip/px30/ src/tf-a/plat/rockchip/common/`
    — две минуты чтения кода вместо часов гаданий на осциллографе.

### Запасной вариант: BL31 от Rockchip

В rkbin есть бинарный `rk3326_bl31_v1.34.elf`. Он лежит в
`board/oga/rkbin/bin/` и подключается так: `UBOOT_BL31 := $(BOARD_DIR)/rkbin/bin/rk3326_bl31_v1.34.elf`.
Mainline TF-A заработала сразу, но запасной вариант полезно иметь — и он понадобился
в другом месте (глава 12).

## U-Boot для ODROID-GO Advance

В mainline U-Boot уже есть плата: `configs/odroid-go2_defconfig` и
`board/hardkernel/odroid_go2/go2.c`, а в документации она значится как
«ODROID-GO Advance (odroid-go2)»: `doc/board/rockchip/rockchip.rst`. Кто её
сопровождает, написано в `board/hardkernel/odroid_go2/MAINTAINERS` — туда же
отправлять патчи.

### Что умеет go2.c

Главное — **определение ревизии**: на канал 0 SARADC повешен резистор, разный для
разных ревизий. U-Boot читает АЦП, находит ревизию в таблице `oga_model_details[]`
и ставит переменные окружения (упрощённо):

```c
env_set("board", ...);
env_set("board_name", ...);
env_set("fdtfile", "rockchip/rk3326-odroid-go2-v11.dtb");   /* для BE */
```

`fdtfile` потом использует extlinux: в `extlinux.conf` написано `fdtdir /`, и U-Boot
загружает `/` + `fdtfile`. Благодаря этому **один образ подходит для всех трёх
ревизий**, и никаких `if test ${hwrev} = 'v11'` из старого `boot.ini` не нужно.

### Важные опции defconfig

```text
CONFIG_DEFAULT_DEVICE_TREE="rockchip/rk3326-odroid-go2"
CONFIG_OF_LIST="rockchip/rk3326-odroid-go2 rockchip/rk3326-odroid-go2-v11 rockchip/rk3326-odroid-go3"
CONFIG_SPL_ATF=y             SPL умеет запускать BL31
CONFIG_TPL_RAM=y             TPL сам инициализирует DDR (без блоба Rockchip)
CONFIG_ENV_OFFSET=0x4000     окружение по смещению 16 КиБ
CONFIG_ROCKCHIP_SPI_IMAGE=y  дополнительно собрать образ для SPI-флеша
```

`CONFIG_TPL_RAM=y` — важная деталь: инициализация DDR в mainline TPL **открытая**
(`drivers/ram/rockchip/sdram_px30.c`), без бинарного DDR-блоба Rockchip.

### Фрагмент SDK

{{include board/oga/u-boot/oga.config}}

Первые две опции появились из-за консоли, вторые две — из-за заводского загрузчика
в SPI (глава 12).

### История про 1500000 бод

По умолчанию U-Boot для Rockchip ставит `CONFIG_BAUDRATE=1500000`. В итоге:

| Стадия | Скорость без фрагмента |
|---|---|
| TPL, SPL, U-Boot | 1 500 000 (CONFIG_BAUDRATE) |
| TF-A | 115 200 (из stdout-path) |
| Ядро | 115 200 (console=ttyS2,115200) |

Лог «разъезжался» бы по скоростям. Фрагмент выставляет 115200 везде. Это ещё и
практично: у многих USB-UART адаптеров (например, CP2102) максимум — 921600 бод,
1,5 Мбод они физически не умеют (глава 11).

!!! note "Отладочный UART в TPL/SPL"
    TPL и SPL печатают через «debug UART» — простейший драйвер без device tree.
    Его параметры — `CONFIG_DEBUG_UART_BASE=0xFF160000` (UART2),
    `CONFIG_DEBUG_UART_CLOCK=24000000`, а скорость — тот же `CONFIG_BAUDRATE`.
    Функция `board_debug_uart_init()` в `arch/arm/mach-rockchip/px30/px30.c`
    переключает пины на UART и выбирает источник тактирования 24 МГц.

### Сборка

```bash
make -C src/u-boot O=output/oga/u-boot CROSS_COMPILE=aarch64-linux-gnu- odroid-go2_defconfig
# + merge_config.sh с фрагментом, olddefconfig
make -C src/u-boot O=output/oga/u-boot CROSS_COMPILE=aarch64-linux-gnu- \
     BL31=output/oga/tf-a/px30/release/bl31/bl31.elf -j16
```

В конце сборки работает **binman** — инструмент U-Boot, который по описанию в
`arch/arm/dts/rockchip-u-boot.dtsi` собирает итоговые образы:

| Файл | Что это |
|---|---|
| `idbloader.img` | TPL + SPL с заголовком Rockchip |
| `u-boot.itb` | FIT: U-Boot + BL31 + dtb |
| `u-boot-rockchip.bin` | idbloader + FIT по смещению `CONFIG_SPL_PAD_TO` — **пишется с сектора 64** |
| `u-boot-rockchip-spi.bin` | то же для SPI-флеша |

Сборка напечатала предупреждение:

```text
Image 'simple-bin' is missing optional external blobs but is still functional: tee-os
```

`tee-os` — это OP-TEE (BL32), необязательный компонент. «Still functional» — образ
рабочий.

!!! danger "Опасно: образ без BL31 всё равно появится"
    U-Boot всегда вызывает binman с `--allow-missing --fake-ext-blobs`. Если BL31 не
    передан, binman подставит **фальшивый** блоб, запишет `u-boot-rockchip.bin` и
    только потом сообщит об ошибке. Make завершится неуспешно, но файл на диске
    останется — и выглядит он как настоящий. А с `BINMAN_ALLOW_MISSING=1` (добавляет
    `--ignore-missing`) не будет даже ошибки. Если вы запускали сборку руками и
    пропустили сообщение, можно получить «загрузчик», который молча не грузится.
    Проверяйте `dumpimage -l u-boot.itb` или код возврата make.

### Проверка результата

```bash
dumpimage -l output/oga/u-boot/u-boot.itb | grep -E 'Image [0-9]|Description|Load'
grep -E '^CONFIG_(BAUDRATE|SYS_MMCSD_RAW_MODE_U_BOOT_SECTOR|SPL_PAD_TO)=' output/oga/u-boot/.config
```

Проверяем три вещи: в FIT есть U-Boot, сегменты BL31 и все три dtb; скорость — 115200;
сектор FIT совпадает с тем, куда он реально попадёт в образе.

## Адреса загрузки ядра

Ещё одна проверка, которую стоит делать для каждой новой платы: **влезет ли ядро в
память между адресами, которые использует U-Boot**. Переменные адресов для PX30 —
в `include/configs/px30_common.h`:

```text
fdt_addr_r=0x01e00000        dtb
kernel_addr_r=0x02080000     ядро
ramdisk_addr_r=0x06000000    initrd
```

Между `kernel_addr_r` и `ramdisk_addr_r` — `0x06000000 − 0x02080000 = 0x3F80000`,
то есть 63,5 МиБ. `Image` из arm64 `defconfig` весит ≈ 40,5 МиБ — влезает. Если бы
ядро было больше, оно перекрыло бы область, куда загрузится что-то ещё, и упало бы
непредсказуемо.

!!! example "Упражнение"
    Найдите в `include/configs/` адреса для am335x и для Raspberry Pi 4 и проверьте,
    сколько места там под ядро. Сравните с размером `zImage` BBB (≈ 5,6 МиБ) и
    `Image` RPi 4 (≈ 41 МиБ).
