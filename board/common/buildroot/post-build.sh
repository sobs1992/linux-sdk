#!/bin/sh
# Buildroot post-build hook shared by all boards.
#   $1     target dir
#   $2...  extra login consoles, "tty[:baud]" (BR2_ROOTFS_POST_SCRIPT_ARGS),
#          e.g. "tty1" for the display next to the serial getty
# The /boot fstab entry is added by scripts/mkimage.sh, which knows the layout.
# SSH public keys from board/common/buildroot/authorized_keys (local, not in
# git) go to /root/.ssh: root has no password, and dropbear refuses empty ones.
set -e
TARGET_DIR="$1"
shift

KEYS="$(dirname "$0")/authorized_keys"
if [ -f "$KEYS" ]; then
	echo "Adding SSH keys from $KEYS"
	install -d -m 700 "$TARGET_DIR/root/.ssh"
	install -m 600 "$KEYS" "$TARGET_DIR/root/.ssh/authorized_keys"
fi

for spec; do
	tty=${spec%%:*}
	baud=${spec#*:}; [ "$baud" != "$spec" ] || baud=0
	grep -q "^$tty::" "$TARGET_DIR/etc/inittab" || \
		sed -i "/# GENERIC_SERIAL\$/a $tty::respawn:/sbin/getty -L $tty $baud linux" "$TARGET_DIR/etc/inittab"
done
