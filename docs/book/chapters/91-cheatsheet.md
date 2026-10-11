# Шпаргалка команд

## SDK

```bash
make <fw>_defconfig          # выбрать прошивку (oga, bbb, rpi1, rpi4)
make info                    # что выбрано, версии компонентов
make                         # всё + образ
make uboot | tfa | bootfw | linux | rootfs | image
make FW=<fw> <цель>          # для другой прошивки, не меняя выбор
make <comp>-menuconfig       # comp: uboot, linux, rootfs
make <comp>-savedefconfig
make <comp>-clean
make rootfs-make BR=<цель>   # любая цель Buildroot: busybox-menuconfig, <pkg>-rebuild…
make rootfs-sdk              # тулчейн + sysroot для приложений
make flash DEV=/dev/sdX      # весь образ
make flash-boot DEV=/dev/sdX # загрузчик + раздел BOOT
```

## Исследование исходников

```bash
git ls-remote --tags --refs <url> | awk -F/ '{print $NF}' | sort -V | tail
grep -rn 'fdtfile' board/<vendor>/ include/configs/
grep -n -A8 '^config FOO$' $(git grep -l '^config FOO$')      # зависимости опции
grep -h -o 'compatible = "[^"]*"' arch/arm64/boot/dts/<v>/<board>*.dts* | sort -u
strings -n 6 blob.img | head                                    # что внутри блоба
```

## Проверка результатов

```bash
dumpimage -l u-boot.itb                       # содержимое FIT
loaderimage --info uboot.img                  # uboot.img Rockchip
aarch64-linux-gnu-readelf -h bl31.elf         # точка входа ELF
xxd -l 16 file                                # сигнатура
sfdisk -l image.img                           # разделы
mdir -i boot.vfat -/ ::/ ; mtype -i boot.vfat ::/path
debugfs -R 'cat /etc/fstab' rootfs.ext4
dd if=img bs=512 skip=<S> count=<N> status=none | cmp - file   # блоб на месте?
scripts/kconfig-check.sh output/<fw>/linux/.config board/<b>/linux/<b>.config
```

## UART

```bash
lsusb -v -d <vid:pid> | grep iProduct         # модель адаптера
fuser -v /dev/ttyUSB0                         # кто держит порт
screen -ls ; screen -S <id> -X hardcopy -h out.txt
screen /dev/ttyUSB0 115200                    # интерактивно; выход Ctrl-A K
stty -F /dev/ttyUSB0 115200 raw -echo cs8 -cstopb -parenb -crtscts
timeout 180 cat /dev/ttyUSB0 > boot.log       # захват с момента включения
cat -v boot.log | head ; wc -c boot.log
```

## Система

```bash
df -h /home ; free -h ; uptime
journalctl -k --since "HH:MM" | grep -i oom
lsblk -o NAME,SIZE,TRAN,RM,FSTYPE,LABEL,PARTUUID,MOUNTPOINT
```

## U-Boot (консоль платы)

```text
=> bootflow scan -l          что можно загрузить
=> printenv fdtfile          какой dtb будет выбран
=> mmc list ; ls mmc 0:1 /   карта и файлы
=> bdinfo                    память
=> sf probe ; sf read <addr> <off> <len>      SPI-флеш
=> fatwrite mmc 1:1 <addr> file <len>         сохранить память в файл на FAT
```
