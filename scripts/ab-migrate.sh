#!/bin/sh
# ab-migrate.sh: an ODROID-GO Ultra on the eMMC layout before A/B slots
# (p1 BOOT with the kernel and extlinux.conf, p2 rootfs, p3 /data to the
# end of the disk) to the A/B layout (docs/boards/ogu.md, "Обновление
# системы"), over ssh, keeping /data: what a new image does by itself
# (scripts/mkimage.sh IMAGE_AB_SLOT_MB, S05data), done on a running board.
#
#   scripts/ab-migrate.sh [-h HOST] boot
#       slot a gets its own /boot (the kernel, dtbs and extlinux.conf of
#       BOOT, which it was booting), BOOT gets boot.scr (U-Boot's mkimage
#       of board/ogu/boot/boot.cmd) and keeps its kernel as the last resort
#       (extlinux/fallback.conf), the A/B state is cleared (slot a). Nothing
#       of /data changes. Reboot and check that slot a still boots.
#   scripts/ab-migrate.sh [-h HOST] partitions
#       /data unmounted (bare_app stopped, swap off, the hibernation file
#       deleted: S06hibernate makes it again), checked and shrunk, p3 made
#       as long, slot a (p2) grown up to /data and its root file system
#       with it, slot b (p4) added at the end. The MBR's first 440 bytes
#       (the boot code of the FIP: without it the board does not start)
#       are compared before and after and put back if sfdisk changed them.
#   scripts/ab-migrate.sh [-h HOST] system FILE.upd
#       the update installed into slot b with this SDK's system-update and
#       ab-state (copied to the board's /tmp: slot a's system predates
#       them; it gets an /etc/sdk-release "pre-ab"), to be tried at the next
#       start. Reboot: slot b boots, S99ab commits it.
#
# A backup of /data first (it stays, but the layout under it changes):
#   ssh root@HOST 'cd /data && tar cf - --exclude=./hibernate.swap .' > data.tar
set -e

SDK=$(cd "$(dirname "$0")/.." && pwd)
HOST=192.168.7.2
[ "$1" = -h ] && { HOST=$2; shift 2; }
SSH="ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o LogLevel=ERROR -o BatchMode=yes root@$HOST"
DISK=mmcblk1
SLOT_MB=$(sed -n 's/^IMAGE_AB_SLOT_MB *:= *//p' "$SDK/configs/ogu_defconfig")
STATE_SECTOR=32512	# ab-state, boot.cmd

die() { echo "ab-migrate: $*" >&2; exit 1; }

# the board runs from p2 of the eMMC
check_board() {
	$SSH "grep -q 'root=PARTUUID=[0-9a-f]*-02' /proc/cmdline && [ -b /dev/$DISK ]" ||
		die "$HOST does not run from p2 of /dev/$DISK"
}

boot() {
	mkimage=$SDK/output/ogu/u-boot/tools/mkimage
	[ -x "$mkimage" ] || die "no $mkimage: make FW=ogu uboot"
	tmp=$(mktemp -d)
	trap 'rm -rf "$tmp"' EXIT
	"$mkimage" -A arm64 -O linux -T script -C none -n "A/B slots" \
		-d "$SDK/board/ogu/boot/boot.cmd" "$tmp/boot.scr" > /dev/null
	check_board
	$SSH 'cat > /tmp/boot.scr' < "$tmp/boot.scr"
	$SSH "set -e
		mountpoint -q /boot || { echo '/boot is not BOOT: done already?' >&2; exit 1; }
		[ -f /boot/extlinux/extlinux.conf ] || { echo 'BOOT has no extlinux.conf' >&2; exit 1; }
		# slot a's own /boot, under the mount of BOOT
		mkdir -p /run/ab-root
		mount --bind / /run/ab-root
		trap 'umount /run/ab-root' EXIT
		mkdir -p /run/ab-root/boot/extlinux
		cp /boot/Image /run/ab-root/boot/Image
		cp -r /boot/amlogic /run/ab-root/boot/
		sed -e 's|kernel /Image|kernel /boot/Image|; s|fdtdir /\$|fdtdir /boot/|' \
			/boot/extlinux/extlinux.conf > /run/ab-root/boot/extlinux/extlinux.conf
		grep -q 'kernel /boot/Image' /run/ab-root/boot/extlinux/extlinux.conf
		grep -q 'fdtdir /boot/' /run/ab-root/boot/extlinux/extlinux.conf
		sync
		# BOOT: boot.scr, its extlinux.conf the last resort
		cp /tmp/boot.scr /boot/boot.scr
		mv /boot/extlinux/extlinux.conf /boot/extlinux/fallback.conf
		sync
		# slot a, nothing to try
		dd if=/dev/zero of=/dev/$DISK bs=512 seek=$STATE_SECTOR count=1 conv=notrunc,fsync 2>/dev/null
		echo 'slot a:'; cat /run/ab-root/boot/extlinux/extlinux.conf
		ls -la /boot /boot/extlinux"
	echo "Now reboot $HOST: U-Boot should say \"A/B: slot on mmc 1:2\"."
}

partitions() {
	[ -n "$SLOT_MB" ] || die "no IMAGE_AB_SLOT_MB in configs/ogu_defconfig"
	check_board
	$SSH "set -e
		disk=/dev/$DISK
		[ ! -e /sys/class/block/${DISK}p4 ] || { echo 'p4 is there: done already?' >&2; exit 1; }
		size=\$(cat /sys/block/$DISK/size)
		p2_start=\$(cat /sys/class/block/${DISK}p2/start)
		data_start=\$(cat /sys/class/block/${DISK}p3/start)
		slot=\$(( $SLOT_MB * 2048 ))
		data_end=\$(( (size - slot) / 2048 * 2048 ))
		data_size=\$(( data_end - data_start ))
		echo \"disk \$size sectors: p2 \$p2_start..\$data_start, p3 \$data_start..\$data_end, p4 \$data_end..\$size\"
		dd if=\$disk bs=440 count=1 2>/dev/null > /run/mbr-code.before
		# /data off
		/etc/init.d/S90bare-app stop
		i=0; while pidof bare_app > /dev/null && [ \$i -lt 50 ]; do sleep 0.2; i=\$((i + 1)); done
		swapoff -a || true
		rm -f /data/hibernate.swap /data/hibernate.swap.new
		/etc/init.d/S05data stop
		mountpoint -q /data && { echo '/data is still mounted' >&2; exit 1; }
		e2fsck -f -y \${disk}p3
		resize2fs \${disk}p3 \${data_size}s
		# the table: p3 shorter, p2 up to /data, p4 at the end
		echo \"size=\$data_size\" | sfdisk -q -N 3 --no-reread --no-tell-kernel \$disk
		echo \"size=\$(( data_start - p2_start ))\" | sfdisk -q -N 2 --no-reread --no-tell-kernel \$disk
		echo \"start=\$data_end, size=\$slot, type=83\" | sfdisk -q --append --no-reread --no-tell-kernel \$disk
		dd if=\$disk bs=440 count=1 2>/dev/null > /run/mbr-code.after
		if ! cmp -s /run/mbr-code.before /run/mbr-code.after; then
			echo 'the MBR boot code changed: put back' >&2
			dd if=/run/mbr-code.before of=\$disk bs=440 count=1 conv=notrunc,fsync 2>/dev/null
		fi
		partx -u -n 3 \$disk
		partx -u -n 2 \$disk
		partx -a -n 4 \$disk
		e2fsck -f -n \${disk}p3
		resize2fs \${disk}p2
		sfdisk -l \$disk | sed -n '/^Device/,\$p'
		df -h /
		/etc/init.d/S05data start
		df -h /data
		/etc/init.d/S90bare-app start"
}

system() {
	file=$1
	[ -f "$file" ] || die "no update file: $file (make FW=ogu update)"
	check_board
	$SSH "[ -b /dev/${DISK}p4 ]" || die "no slot b: ab-migrate.sh partitions first"
	for f in ab-state system-update; do
		$SSH "cat > /tmp/$f && chmod 755 /tmp/$f" < "$SDK/board/ogu/buildroot/rootfs-overlay/usr/sbin/$f"
	done
	$SSH 'cat > /tmp/system-keep' < "$SDK/board/ogu/buildroot/rootfs-overlay/etc/system-keep"
	$SSH "[ -f /etc/sdk-release ] || printf 'FIRMWARE=ogu\nBUILT=unknown\nSDK=pre-ab\n' > /etc/sdk-release
		[ -f /etc/system-keep ] || cp /tmp/system-keep /etc/system-keep
		mkdir -p /data/updates"
	name=$(basename "$file")
	echo "copying $name"
	$SSH "cat > /data/updates/$name.part && mv /data/updates/$name.part /data/updates/$name" < "$file"
	$SSH "PATH=/tmp:\$PATH system-update /data/updates/$name && /tmp/ab-state"
	echo "Now reboot $HOST: slot b should boot."
}

case $1 in
boot) boot ;;
partitions) partitions ;;
system) system "$2" ;;
*) echo "usage: $0 [-h HOST] boot | partitions | system FILE.upd" >&2; exit 1 ;;
esac
