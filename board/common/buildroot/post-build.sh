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

# What this image is, for reports and updates: /etc/sdk-release with the
# firmware (BASE_DIR is output/<fw>/buildroot), the day it was built and
# the SDK's and bare_app's commits ("-dirty": with changes not committed)
SDK_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
ver() {
	git -C "$1" describe --always --dirty --abbrev=7 2>/dev/null || echo unknown
}
cat > "$TARGET_DIR/etc/sdk-release" <<-END
	FIRMWARE=$(basename "$(dirname "${BASE_DIR:-unknown/x}")")
	BUILT=$(date +%Y-%m-%d)
	SDK=$(ver "$SDK_DIR")
	BARE_APP=$(ver "$SDK_DIR/apps/bare_app")
END

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
