#!/bin/sh
# Buildroot post-build hook: $1 = target dir
set -e
TARGET_DIR="$1"

# Login prompt on the panel in addition to the serial console
grep -q '^tty1::' "$TARGET_DIR/etc/inittab" || \
	sed -i '/# GENERIC_SERIAL$/a tty1::respawn:/sbin/getty -L tty1 0 linux' "$TARGET_DIR/etc/inittab"

# Boot partition (kernel, dtbs, extlinux.conf)
mkdir -p "$TARGET_DIR/boot"
grep -q '[[:space:]]/boot[[:space:]]' "$TARGET_DIR/etc/fstab" || \
	echo '/dev/mmcblk0p1	/boot	vfat	defaults,noatime	0	0' >> "$TARGET_DIR/etc/fstab"
