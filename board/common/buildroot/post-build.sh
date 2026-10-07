#!/bin/sh
# Buildroot post-build hook shared by all boards.
#   $1     target dir
#   $2...  extra login consoles, "tty[:baud]" (BR2_ROOTFS_POST_SCRIPT_ARGS),
#          e.g. "tty1" for the display next to the serial getty
# The /boot fstab entry is added by scripts/mkimage.sh, which knows the layout.
set -e
TARGET_DIR="$1"
shift

for spec; do
	tty=${spec%%:*}
	baud=${spec#*:}; [ "$baud" != "$spec" ] || baud=0
	grep -q "^$tty::" "$TARGET_DIR/etc/inittab" || \
		sed -i "/# GENERIC_SERIAL\$/a $tty::respawn:/sbin/getty -L $tty $baud linux" "$TARGET_DIR/etc/inittab"
done
