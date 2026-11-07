#!/bin/bash
# Write a file to a removable block device at a sector offset.
# Usage: flash.sh <file> <device> <sector> [<mbr code>]
#   <mbr code>: up to 440 bytes of boot code, written to the start of the
#   device after <file>; the partition table after them stays.
# EJECT=1: eject the device afterwards (a board showing its eMMC as a USB
# disk then restarts).
set -euo pipefail

FILE=$1 DEV=${2:-} SECTOR=${3:-0} MBR=${4:-}
die() { echo "flash: $*" >&2; exit 1; }

if [ -z "$DEV" ]; then
	echo "Specify the SD card: DEV=/dev/sdX. Removable devices:"
	lsblk -d -o NAME,SIZE,TRAN,RM,MODEL | awk 'NR==1 || $4==1'
	exit 1
fi
[ -f "$FILE" ] || die "$FILE not found: build it first"
[ -z "$MBR" ] || [ -f "$MBR" ] || die "$MBR not found: build it first"
[ -z "$MBR" ] || [ "$(stat -c %s "$MBR")" -le 440 ] || die "$MBR is larger than 440 bytes"
[ -b "$DEV" ] || die "$DEV is not a block device"
[ "$(lsblk -dno TYPE "$DEV")" = disk ] || die "$DEV is a partition, pass the whole disk"
if [ "$(lsblk -dno RM "$DEV")" != 1 ] && [ "$(lsblk -dno TRAN "$DEV")" != usb ] && [[ $DEV != /dev/mmcblk* ]]; then
	die "$DEV is not removable, refusing to write"
fi
if lsblk -lno MOUNTPOINT "$DEV" | grep -qxE '/|/boot|/home|/usr|/var'; then
	die "$DEV holds a system mount point"
fi

lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DEV"
echo
what=$(basename "$FILE")${MBR:+ (+ $(basename "$MBR") at sector 0)}
read -r -p "Write $what to $DEV at sector $SECTOR? Data on $DEV will be lost. Type 'yes': " answer
[ "$answer" = yes ] || die "aborted"

for part in $(lsblk -lnpo NAME,MOUNTPOINT "$DEV" | awk '$2 != "" {print $1}'); do
	sudo umount "$part"
done
sudo dd if="$FILE" of="$DEV" bs=4M seek=$(( SECTOR * 512 )) oflag=seek_bytes conv=fsync status=progress
if [ -n "$MBR" ]; then
	sudo dd if="$MBR" of="$DEV" conv=notrunc,fsync status=none
fi
sync
if [ "${EJECT:-}" = 1 ]; then
	sudo eject "$DEV" && echo "Ejected $DEV."
fi
echo "Done."
