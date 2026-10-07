#!/bin/bash
# Glue separately built components into an SD card image.
#
#   sector 0        MBR (disk id DISK_ID)
#   RAW             raw bootloader blobs ("file@sector ..."), below 16 MiB
#   16M             p1 FAT32 "BOOT" (bootable): kernel, dtbs, extlinux.conf,
#                   BOOT_FILES ("src[:name] ...", e.g. MLO, RPi firmware)
#   16M+BOOT        p2 ext4 "rootfs": Buildroot rootfs.tar + kernel modules
#
# DTB_LAYOUT picks where the dtbs land in BOOT, matching how U-Boot builds
# ${fdtfile} for extlinux "fdtdir /": "tree" keeps the vendor dirs
# (rockchip/foo.dtb), "flat" puts them in the root, "both" does both.
#
# Usage: mkimage.sh <output.img>, inputs come from the environment (see Makefile).
set -euo pipefail

OUT_IMG=$1
: "${KERNEL:?}" "${LINUX_DIR:?}" "${ROOTFS_TAR:?}" "${CMDLINE:?}"
: "${BOOT_SIZE_MB:?}" "${ROOTFS_FREE_MB:?}" "${DISK_ID:?}" "${WORK_DIR:?}"
RAW=${RAW:-}
BOOT_FILES=${BOOT_FILES:-}
DTB_LAYOUT=${DTB_LAYOUT:-tree}

P1_START=32768	# 16 MiB, in 512-byte sectors

die() { echo "mkimage: $*" >&2; exit 1; }

# System tools first, Buildroot host tools as a fallback
export PATH="$PATH:/usr/sbin:/sbin${HOST_TOOLS:+:$HOST_TOOLS}"
need() { command -v "$1" >/dev/null || die "'$1' not found (package: $2)"; }
need sfdisk fdisk
need mkfs.vfat dosfstools
need mcopy mtools
need mke2fs e2fsprogs
need fakeroot fakeroot

for f in "$KERNEL" "$ROOTFS_TAR"; do
	[ -e "$f" ] || die "missing $f: build the component first"
done

# --- raw blobs: sorted by sector, must not overlap each other or p1 ---
raw_sorted=$(for r in $RAW; do echo "${r##*@} ${r%@*}"; done | sort -n)
first_sector=$P1_START
prev_end=1
while read -r sector file; do
	[ -n "$sector" ] || continue
	[ -f "$file" ] || die "missing $file: build the component first"
	[ "$sector" -ge "$prev_end" ] || die "$(basename "$file") at sector $sector overlaps the previous blob"
	prev_end=$(( sector + ($(stat -c %s "$file") + 511) / 512 ))
	[ "$prev_end" -le $P1_START ] || die "$(basename "$file") at sector $sector overlaps the first partition"
	if [ "$sector" -lt "$first_sector" ]; then first_sector=$sector; fi
done <<< "$raw_sorted"

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/boot/extlinux"

# --- boot partition ---
BOOT_DIR=$WORK_DIR/boot
cp "$KERNEL" "$BOOT_DIR/"
if [ -d "$LINUX_DIR/dtbs" ]; then
	case $DTB_LAYOUT in
	tree|both) cp -r "$LINUX_DIR/dtbs/." "$BOOT_DIR/" ;;&
	flat|both) find "$LINUX_DIR/dtbs" -name '*.dtb' -exec cp {} "$BOOT_DIR/" \; ;;
	tree) ;;
	*) die "unknown DTB_LAYOUT '$DTB_LAYOUT' (tree, flat or both)" ;;
	esac
fi

for f in $BOOT_FILES; do
	src=${f%%:*}
	dst=${f#*:}; [ "$dst" != "$f" ] || dst=$(basename "$src")
	[ -f "$src" ] || die "missing $src: build the component first"
	cp "$src" "$BOOT_DIR/$dst"
done

disk_id=$(printf '%08x' $(( DISK_ID )))
# U-Boot sets ${fdtfile} from the board model; fdtdir prepends the path.
cat > "$BOOT_DIR/extlinux/extlinux.conf" <<EOT
default linux

label linux
	kernel /$(basename "$KERNEL")
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
	# BOOT partition on /boot, by label: the mmcblk number differs per board
	mkdir -p "$root/boot"
	sed -i "/[[:space:]]\/boot[[:space:]]/d" "$root/etc/fstab"
	printf "LABEL=BOOT\t/boot\tvfat\tdefaults,noatime\t0\t0\n" >> "$root/etc/fstab"
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
while read -r sector file; do
	if [ -n "$sector" ]; then put "$file" "$sector"; fi
done <<< "$raw_sorted"
put "$BOOT_IMG" "$P1_START"
put "$ROOT_IMG" "$p2_start"
mv "$TMP_IMG" "$OUT_IMG"

# Bootloader blobs + BOOT partition for "make flash-boot"
out_dir=$(dirname "$OUT_IMG")
dd if="$OUT_IMG" of="$out_dir/boot-area.bin" bs=1M skip=$(( first_sector * 512 )) \
	count=$(( (p2_start - first_sector) * 512 )) iflag=skip_bytes,count_bytes status=none
echo "$first_sector" > "$out_dir/boot-area.sector"

echo "Image: $OUT_IMG ($(( total_sectors / 2048 )) MiB)"
sfdisk -l "$OUT_IMG" | sed -n '/^Device/,$p'
echo "root=PARTUUID=$disk_id-02"
