#!/bin/bash
# Glue separately built components into an SD card image.
#
#   sector 0        MBR (disk id DISK_ID)
#   16K..32K        U-Boot environment (written by saveenv)
#   UBOOT_SECTOR    u-boot-rockchip.bin (idbloader: TPL+SPL, then u-boot.itb)
#   8M  (16384)     uboot.img  } optional (RK_UBOOT_IMG/RK_TRUST_IMG): Rockchip
#   12M (24576)     trust.img  } legacy format, loaded by an SPI miniloader
#   16M             p1 FAT32 "BOOT": Image, dtbs, extlinux/extlinux.conf
#   16M+BOOT        p2 ext4 "rootfs": Buildroot rootfs.tar + kernel modules
#
# Usage: mkimage.sh <output.img>, inputs come from the environment (see Makefile).
set -euo pipefail

OUT_IMG=$1
: "${UBOOT_BIN:?}" "${UBOOT_SECTOR:?}" "${LINUX_DIR:?}" "${ROOTFS_TAR:?}" "${CMDLINE:?}"
: "${BOOT_SIZE_MB:?}" "${ROOTFS_FREE_MB:?}" "${DISK_ID:?}" "${WORK_DIR:?}"

P1_START=32768	# 16 MiB, in 512-byte sectors
RK_UBOOT_SECTOR=16384
RK_TRUST_SECTOR=24576
RK_UBOOT_IMG=${RK_UBOOT_IMG:-}
RK_TRUST_IMG=${RK_TRUST_IMG:-}

die() { echo "mkimage: $*" >&2; exit 1; }

# System tools first, Buildroot host tools as a fallback
export PATH="$PATH:/usr/sbin:/sbin${HOST_TOOLS:+:$HOST_TOOLS}"
need() { command -v "$1" >/dev/null || die "'$1' not found (package: $2)"; }
need sfdisk fdisk
need mkfs.vfat dosfstools
need mcopy mtools
need mke2fs e2fsprogs
need fakeroot fakeroot

for f in "$UBOOT_BIN" "$LINUX_DIR/Image" "$ROOTFS_TAR"; do
	[ -e "$f" ] || die "missing $f: build the component first"
done

# $1=file $2=start sector $3=end sector (exclusive)
fits() {
	[ $(( $2 * 512 + $(stat -c %s "$1") )) -le $(( $3 * 512 )) ] || \
		die "$(basename "$1") at sector $2 does not fit below sector $3"
}
if [ -n "$RK_UBOOT_IMG$RK_TRUST_IMG" ]; then
	[ -f "$RK_UBOOT_IMG" ] && [ -f "$RK_TRUST_IMG" ] || die "missing uboot.img/trust.img: run 'make uboot'"
	fits "$UBOOT_BIN" "$UBOOT_SECTOR" $RK_UBOOT_SECTOR
	fits "$RK_UBOOT_IMG" $RK_UBOOT_SECTOR $RK_TRUST_SECTOR
	fits "$RK_TRUST_IMG" $RK_TRUST_SECTOR $P1_START
else
	fits "$UBOOT_BIN" "$UBOOT_SECTOR" $P1_START
fi

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/boot/extlinux"

# --- boot partition ---
BOOT_DIR=$WORK_DIR/boot
cp "$LINUX_DIR/Image" "$BOOT_DIR/"
[ -d "$LINUX_DIR/dtbs" ] && cp -r "$LINUX_DIR/dtbs/." "$BOOT_DIR/"

disk_id=$(printf '%08x' $(( DISK_ID )))
# U-Boot sets ${fdtfile} from the board revision; fdtdir prepends the path.
cat > "$BOOT_DIR/extlinux/extlinux.conf" <<EOT
default linux

label linux
	kernel /Image
	fdtdir /
	append root=PARTUUID=$disk_id-02 $CMDLINE
EOT

boot_kb=$(du -sk "$BOOT_DIR" | cut -f1)
[ "$boot_kb" -lt $(( BOOT_SIZE_MB * 1024 * 95 / 100 )) ] || \
	die "boot files ($((boot_kb / 1024)) MiB) do not fit into IMAGE_BOOT_SIZE_MB=$BOOT_SIZE_MB"

BOOT_IMG=$WORK_DIR/boot.vfat
mkfs.vfat -F 32 -n BOOT -i "$disk_id" -C "$BOOT_IMG" $(( BOOT_SIZE_MB * 1024 )) >/dev/null
mcopy -i "$BOOT_IMG" -s -p -m "$BOOT_DIR"/* ::/

# --- rootfs partition ---
ROOT_DIR=$WORK_DIR/rootfs
ROOT_IMG=$WORK_DIR/rootfs.ext4
fakeroot -- bash -euo pipefail -c '
	root=$1 tar=$2 mods=$3 free_mb=$4 img=$5
	mkdir -p "$root"
	tar -xpf "$tar" -C "$root"
	if [ -d "$mods/lib/modules" ]; then
		mkdir -p "$root/lib/modules"
		cp -r "$mods/lib/modules/." "$root/lib/modules/"
		chown -R 0:0 "$root/lib/modules"
	fi
	size_mb=$(( $(du -sm "$root" | cut -f1) * 11 / 10 + free_mb ))
	mke2fs -q -F -t ext4 -L rootfs -d "$root" -E root_owner=0:0 "$img" "${size_mb}M"
' _ "$ROOT_DIR" "$ROOTFS_TAR" "$LINUX_DIR/modules" "$ROOTFS_FREE_MB" "$ROOT_IMG"
rm -rf "$ROOT_DIR"

# --- disk ---
boot_sectors=$(( BOOT_SIZE_MB * 2048 ))
p2_start=$(( P1_START + boot_sectors ))
root_sectors=$(( $(stat -c %s "$ROOT_IMG") / 512 ))
total_sectors=$(( p2_start + root_sectors + 2048 ))

TMP_IMG=$OUT_IMG.tmp
rm -f "$TMP_IMG"
truncate -s $(( total_sectors * 512 )) "$TMP_IMG"
sfdisk -q "$TMP_IMG" <<EOT
label: dos
label-id: $DISK_ID
start=$P1_START, size=$boot_sectors, type=c, bootable
start=$p2_start, size=$root_sectors, type=83
EOT

put() { dd if="$1" of="$TMP_IMG" bs=1M seek=$(( $2 * 512 )) oflag=seek_bytes conv=notrunc status=none; }
put "$UBOOT_BIN" "$UBOOT_SECTOR"
if [ -n "$RK_UBOOT_IMG" ]; then
	put "$RK_UBOOT_IMG" $RK_UBOOT_SECTOR
	put "$RK_TRUST_IMG" $RK_TRUST_SECTOR
fi
put "$BOOT_IMG" "$P1_START"
put "$ROOT_IMG" "$p2_start"
mv "$TMP_IMG" "$OUT_IMG"

# Whole bootloader area for "make flash-uboot"
dd if="$OUT_IMG" of="$(dirname "$OUT_IMG")/bootloader.bin" bs=512 skip="$UBOOT_SECTOR" \
	count=$(( P1_START - UBOOT_SECTOR )) status=none

echo "Image: $OUT_IMG ($(( total_sectors / 2048 )) MiB)"
sfdisk -l "$OUT_IMG" | sed -n '/^Device/,$p'
echo "root=PARTUUID=$disk_id-02"
