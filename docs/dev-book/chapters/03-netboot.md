# Быстрый цикл: загрузка по сети

Перепрошивать карту после каждой правки ядра долго. На платах с Ethernet можно
сделать так, чтобы **ядро грузилось по TFTP**, а **rootfs была каталогом на ПК** по
NFS. Тогда:

- пересобрали ядро → скопировали в каталог TFTP → перезагрузили плату;
- собрали программу → положили прямо в каталог rootfs на ПК → она сразу видна на плате.

SD-карта при этом нужна только для загрузчика.

| Плата | Сеть в U-Boot | Сеть в ядре для NFS-корня |
|---|---|---|
| BBB | CPSW (`DRIVER_TI_CPSW`) | `TI_CPSW=y` |
| RPi 1 B/B+ | USB LAN9512/9514 (`USB_ETHER_SMSC95XX`), нужен `usb start` | `USB_NET_SMSC95XX=y`, `USB_DWC2=y` |
| RPi 4/400 | GENET (`BCMGENET`) | `BCMGENET=y`, `BROADCOM_PHY=y` (фрагмент SDK) |
| OGA | нет | — |

!!! warning "Ловушка: драйвер сети для NFS-корня должен быть встроен"
    Ядро монтирует NFS-корень **до** того, как может загрузить хоть один модуль
    (модули лежат на том самом корне). Драйвер Ethernet и всё, от чего он зависит,
    должны быть `=y`. У RPi 4 в arm64 `defconfig` GENET — модуль, поэтому во фрагменте
    SDK стоит `CONFIG_BCMGENET=y`. Проверка:
    `grep -E 'BCMGENET|ROOT_NFS|IP_PNP_DHCP' output/rpi4/linux/.config`.

## Сервер на ПК

```bash
sudo apt install tftpd-hpa nfs-kernel-server
```

### TFTP

`tftpd-hpa` раздаёт `/srv/tftp`. Сложим туда ядро и dtb каждой прошивки:

```bash
FW=rpi4
sudo mkdir -p /srv/tftp/$FW
sudo cp output/$FW/linux-install/Image /srv/tftp/$FW/          # у bbb и rpi1 — zImage
sudo cp -r output/$FW/linux-install/dtbs/. /srv/tftp/$FW/      # broadcom/*.dtb
```

### NFS

```bash
sudo mkdir -p /srv/nfs/$FW
sudo tar -xpf output/$FW/images/rootfs.tar -C /srv/nfs/$FW
sudo cp -r output/$FW/linux-install/modules/lib/modules /srv/nfs/$FW/lib/
echo "/srv/nfs/$FW *(rw,sync,no_root_squash,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra
```

`no_root_squash` нужен, потому что на плате всё работает от root. Распаковывать rootfs
нужно через `sudo`, чтобы файлы получили владельца root.

!!! note "Почему DHCP при загрузке не рвёт NFS"
    В rootfs сеть поднимается скриптом `S40network` по `/etc/network/interfaces`, где
    для `eth0` стоит `pre-up /etc/network/nfs_check`. Этот скрипт Buildroot проверяет
    `/proc/mounts`: если корень смонтирован по NFS через этот интерфейс, он не трогает
    его. Иначе повторный DHCP мог бы на секунду снять адрес, и система бы зависла.

## PXE: тот же extlinux, но по сети

U-Boot умеет PXE: скачать по TFTP файл в формате `extlinux.conf` и загрузить, что
в нём написано. Это самый удобный путь: формат уже знаком, а `fdtdir` и
автоматический выбор dtb работают так же, как с SD-карты.

Файл `/srv/tftp/pxelinux.cfg/default` (или `01-<mac-адрес-через-дефисы>`, чтобы у
каждой платы был свой):

```text
default nfs

label nfs
	kernel rpi4/Image
	fdtdir rpi4/
	append root=/dev/nfs nfsroot=192.168.1.10:/srv/nfs/rpi4,v3,tcp ip=dhcp rw console=tty1 console=ttyS1,115200n8
```

`192.168.1.10` — адрес ПК. `ip=dhcp` просит ядро само получить адрес до монтирования
корня (опция `IP_PNP_DHCP`, она включена во всех ядрах SDK).

В консоли U-Boot (прервите автозагрузку любой клавишей):

```text
=> setenv autoload no          # dhcp только получит адрес, ничего не скачивая
=> dhcp
=> setenv serverip 192.168.1.10
=> pxe get
=> pxe boot
```

Особенности плат:

| Плата | Перед `dhcp` | `kernel` | `fdtdir` и `${fdtfile}` |
|---|---|---|---|
| BBB | — | `bbb/zImage` | `bbb/` → `bbb/am335x-boneblack.dtb` |
| RPi 1 | `usb start` (Ethernet на USB) | `rpi1/zImage` | `rpi1/` → `rpi1/bcm2835-rpi-b-plus.dtb` |
| RPi 4/400 | — | `rpi4/Image` | `rpi4/` → `rpi4/broadcom/bcm2711-rpi-400.dtb` |

В `append` замените консоль: `ttyS0` у BBB, `ttyAMA0` у RPi 1, `ttyS1` у RPi 4.

## Ручная загрузка без PXE

Иногда полезно сделать всё по шагам, например чтобы загрузить ядро по сети, а rootfs
оставить на карте:

```text
=> setenv autoload no; dhcp; setenv serverip 192.168.1.10
=> tftpboot ${kernel_addr_r} bbb/zImage
=> tftpboot ${fdt_addr_r} bbb/${fdtfile}
=> setenv bootargs root=PARTUUID=42424231-02 rootwait rw console=ttyS0,115200n8
=> bootz ${kernel_addr_r} - ${fdt_addr_r}
```

Для arm64 (RPi 4) вместо `bootz` — `booti`. Здесь новое ядро с TFTP работает с rootfs
на SD — удобно, когда меняете только ядро. Но помните: модули на SD-карте остались
от старого ядра, и если версия или конфигурация изменились, `modprobe` их не загрузит.

## Сделать сетевую загрузку постоянной

```text
=> setenv bootcmd 'setenv autoload no; dhcp; setenv serverip 192.168.1.10; pxe get && pxe boot'
=> saveenv
```

`saveenv` у BBB и RPi пишет файл `uboot.env` на раздел BOOT (FAT). Вернуть всё как было:
`env default -a; saveenv` в U-Boot или просто удалить `uboot.env` с карты на ПК.

## Цикл разработки с NFS

```bash
make FW=rpi4 linux && sudo cp output/rpi4/linux-install/Image /srv/tftp/rpi4/
# перезагрузить плату — новое ядро

aarch64-buildroot-linux-gnu-gcc -o hello hello.c && sudo cp hello /srv/nfs/rpi4/usr/bin/
# на плате сразу: hello
```

!!! tip "Совет"
    Отдайте каталог NFS своему пользователю (`sudo chown -R $USER /srv/nfs/rpi4/root`),
    чтобы копировать в домашний каталог root на плате без `sudo`.

## А если сети нет (OGA)

Для OGA этот цикл недоступен: в U-Boot нет драйвера USB-Ethernet для её адаптера, а
своей сети на плате нет. Самые быстрые варианты:

- программы — USB-Ethernet адаптер в работающем Linux и `scp` (глава 2);
- ядро и dtb — `make linux image` + `make flash-boot DEV=/dev/sdX` через картридер
  (rootfs и ваши файлы на ней не трогаются);
- небольшие файлы — UART и `rz`.
