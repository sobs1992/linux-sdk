# Шпаргалка разработчика

## Программы

```bash
export PATH=$SDK/output/<fw>/buildroot/host/bin:$PATH
<префикс>-gcc -O2 -g -o app app.c $(pkg-config --cflags --libs <lib>)
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=$SDK/output/<fw>/buildroot/host/share/buildroot/toolchainfile.cmake
scp app root@board:/usr/bin/
gdbserver :2345 app            # плата
<префикс>-gdb app              # ПК: set sysroot …/staging ; target remote board:2345
```

## Пакеты

```bash
make rootfs-menuconfig && make rootfs-savedefconfig
make rootfs-make BR=<пакет>-rebuild        # после правки исходников
make rootfs-make BR=<пакет>-reconfigure    # после смены опций пакета
make rootfs image
```

## Модули

```bash
cd apps/kmod/<модуль> && make FW=<fw>          # .ko против output/<fw>/linux
make FW=<fw> install                            # в linux-install (после make linux!)
insmod x.ko param=val ; rmmod x ; modinfo x.ko ; dmesg -w
```

## Ядро и device tree

```bash
make linux-menuconfig ; src/linux/scripts/diffconfig before after
make linux image && make flash-boot DEV=/dev/sdX
build-overlay.sh src/linux x.dtso x.dtbo
fdtoverlay -i base.dtb -o merged.dtb x.dtbo && fdtget merged.dtb /node prop
fdtget -l <dtb> / | grep __symbols__
```

Командная строка ядра для отладки: `earlycon ignore_loglevel initcall_debug`.

## U-Boot

```text
=> printenv / setenv / saveenv / env default -a
=> bootflow scan -l ; bootflow scan -lb
=> setenv autoload no; dhcp; setenv serverip <ПК>; pxe get; pxe boot
=> tftpboot ${kernel_addr_r} <файл> ; booti|bootz ${kernel_addr_r} - ${fdt_addr_r}
=> ls mmc 0:1 / ; load mmc 0:1 <addr> <файл> ; md.l <addr> 10
=> gpio status -a ; i2c dev 1 ; i2c probe ; dm tree ; bdinfo
```

## Доставка

| Что | Команда |
|---|---|
| Весь образ | `make flash DEV=/dev/sdX` |
| Загрузчик + ядро + dtb | `make flash-boot DEV=/dev/sdX` |
| Файл по сети | `scp file root@board:/path` |
| Файл по UART | `picocom --send-cmd "sz -vv"` + `rz` на плате |
| Ядро по сети | TFTP + `pxe boot` |
| Весь rootfs по сети | NFS, `root=/dev/nfs nfsroot=… ip=dhcp` |
