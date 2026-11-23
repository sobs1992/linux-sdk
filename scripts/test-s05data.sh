#!/bin/sh
# test-s05data.sh [HOST]: /etc/init.d/S05data of this SDK against a disk
# image on a loop device of a board (GO Ultra: util-linux, e2fsprogs,
# dosfstools), over ssh. The cases, each a fresh image of 600 MiB:
#   fresh      the image only (p1, a small p2), A/B config: p2 grown to the
#              data start, p3 "data" made up to slot b, p4 added, empty
#   reflash    an A/B disk flashed again (table back to p1, p2): p3 and p4
#              back where they were, /data and slot b's file system kept
#   old        a "data" of the older layout to the end of the disk: p3 of
#              its own size, mounted, no p4 (ab-migrate.sh makes room)
#   steady     everything there: the table not touched
#   no-slot    the older config ("start" only): p3 to the end, no p4
#   games      a config with a size (GO Advance): p3 of that size, p4 FAT
#              "GAMES" after it
# Prints PASS or FAIL per case; exit status 1 if one failed.
set -e
SDK=$(cd "$(dirname "$0")/.." && pwd)
HOST=${1:-192.168.7.2}
SSH="ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o LogLevel=ERROR -o BatchMode=yes root@$HOST"

$SSH 'cat > /tmp/S05data.test && chmod 755 /tmp/S05data.test' \
	< "$SDK/board/common/buildroot/rootfs-overlay/etc/init.d/S05data"
$SSH 'cat > /tmp/s05test.sh && sh /tmp/s05test.sh' <<'EOF'
set -u
# the image on /data (room), everything mounted under /run: never a mount
# inside the data under test; no recursive removal anywhere
IMG=/data/s05test.img
W=/run/s05test
MNT=$W/mnt
CONF=$W/data-partition
DISK_SECTORS=1228800		# 600 MiB
P1="start=2048, size=30720, type=c, bootable"
P2="start=32768, size=40960, type=83"
DATA_START=102400		# 50 MiB
SLOT=204800			# 100 MiB
DATA_END=1024000		# (DISK - SLOT) on a MiB boundary
fails=0

mkdir -p "$W" "$MNT"
cleanup() {
	while umount "$MNT" 2>/dev/null; do :; done
	[ -n "${loop:-}" ] && losetup -d "/dev/$loop" 2>/dev/null
	loop=
}
die() {
	echo "s05test: $*"
	cleanup
	exit 2
}
fresh() {
	cleanup
	rm -f "$IMG"
	truncate -s $((DISK_SECTORS * 512)) "$IMG"
	printf 'label: dos\nlabel-id: 0x5e5e5e5e\n%s\n%s\n' "$P1" "$P2" | sfdisk -q "$IMG"
}
attach() {
	dev=$(losetup -f) || die "no free loop device"
	case $dev in /dev/loop[0-9]*) ;; *) die "losetup -f gave \"$dev\"" ;; esac
	losetup -P "$dev" "$IMG" || die "cannot attach $IMG"
	loop=${dev#/dev/}
	[ -b "/dev/${loop}p1" ] || sleep 1
	[ -b "/dev/${loop}p1" ] || die "no partitions on /dev/$loop"
}
run() {	# the config, then S05data start
	case ${loop:-} in loop[0-9]*) ;; *) die "no loop device" ;; esac
	echo "$1" > "$CONF"
	S05DATA_DISK=$loop S05DATA_CONF=$CONF S05DATA_MNT=$MNT S05DATA_NO_GAMES=1 \
		/tmp/S05data.test start > "$W/log" 2>&1
}
part() {	# "start size" of partition N, "" none
	[ -e "/sys/class/block/${loop}p$1" ] || { echo ""; return; }
	echo "$(cat /sys/class/block/${loop}p$1/start) $(cat /sys/class/block/${loop}p$1/size)"
}
label() {
	blkid -p -o value -s LABEL "/dev/${loop}p$1" 2>/dev/null
}
check() {	# name, condition (eval)
	if eval "$2"; then :; else
		echo "FAIL $1: $2"
		sed 's/^/    /' "$W/log"
		fails=$((fails + 1))
		return 1
	fi
}
pass() { echo "PASS $1"; }

# --- fresh
fresh; attach; run "$DATA_START - $SLOT"
check fresh '[ "$(part 2)" = "32768 $((DATA_START - 32768))" ]' &&
check fresh '[ "$(part 3)" = "$DATA_START $((DATA_END - DATA_START))" ]' &&
check fresh '[ "$(label 3)" = data ] && grep -q "^/dev/${loop}p3 $MNT " /proc/mounts' &&
check fresh '[ "$(part 4)" = "$DATA_END $SLOT" ] && [ -z "$(blkid -p -o value -s TYPE "/dev/${loop}p4" 2>/dev/null)" ]' &&
pass fresh

# --- reflash: the same disk, its table as the image writes it
echo saved > "$MNT/save"
mke2fs -q -t ext4 -L system-b "/dev/${loop}p4"
cleanup
printf 'label: dos\nlabel-id: 0x5e5e5e5e\n%s\n%s\n' "$P1" "start=32768, size=$((DATA_START - 32768)), type=83" |
	sfdisk -q "$IMG"
attach; run "$DATA_START - $SLOT"
check reflash '[ "$(part 3)" = "$DATA_START $((DATA_END - DATA_START))" ]' &&
check reflash '[ "$(cat "$MNT/save" 2>/dev/null)" = saved ]' &&
check reflash '[ "$(part 4)" = "$DATA_END $SLOT" ] && [ "$(label 4)" = system-b ]' &&
pass reflash

# --- steady: nothing to do
before=$(sfdisk -d "/dev/$loop")
cleanup; attach; run "$DATA_START - $SLOT"
check steady '[ "$(sfdisk -d "/dev/$loop")" = "$before" ] && grep -q "^/dev/${loop}p3 $MNT " /proc/mounts' &&
pass steady

# --- old: "data" of the older layout to the end of the disk
fresh
printf 'label: dos\nlabel-id: 0x5e5e5e5e\n%s\n%s\nstart=%s, type=83\n' "$P1" "$P2" "$DATA_START" | sfdisk -q "$IMG"
attach
mke2fs -q -t ext4 -L data "/dev/${loop}p3"
mount "/dev/${loop}p3" "$MNT" && echo saved > "$MNT/save" && umount "$MNT"
cleanup
printf 'label: dos\nlabel-id: 0x5e5e5e5e\n%s\n%s\n' "$P1" "$P2" | sfdisk -q "$IMG"
attach; run "$DATA_START - $SLOT"
check old '[ "$(part 3)" = "$DATA_START $((DISK_SECTORS - DATA_START))" ]' &&
check old '[ "$(cat "$MNT/save" 2>/dev/null)" = saved ]' &&
check old '[ -z "$(part 4)" ] && grep -q "no room for slot b" "$W/log"' &&
pass old

# --- no-slot: the config before slots, p3 to the end
fresh; attach; run "$DATA_START"
check no-slot '[ "$(part 3)" = "$DATA_START $((DISK_SECTORS - DATA_START))" ] && [ -z "$(part 4)" ]' &&
check no-slot '[ "$(part 2)" = "32768 40960" ] && grep -q "^/dev/${loop}p3 $MNT " /proc/mounts' &&
pass no-slot

# --- games: a size, p4 "GAMES" after p3
fresh; attach; run "$DATA_START 409600"
check games '[ "$(part 3)" = "$DATA_START 409600" ] && [ "$(label 3)" = data ]' &&
check games '[ "$(part 4)" = "$((DATA_START + 409600)) $((DISK_SECTORS - DATA_START - 409600))" ]' &&
check games '[ "$(label 4)" = GAMES ]' &&
pass games

cleanup
grep -q " $W" /proc/mounts && die "something is still mounted under $W"
rm -f "$IMG" "$CONF" "$W/log" /tmp/s05save
rmdir "$MNT" "$W"
echo "$fails failed"
[ $fails -eq 0 ]
EOF
