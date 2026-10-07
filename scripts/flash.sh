#!/bin/bash
# Write a file to a removable block device at a sector offset.
# Usage: flash.sh <file> <device> <sector>
set -euo pipefail

FILE=$1 DEV=${2:-} SECTOR=${3:-0}
die() { echo "flash: $*" >&2; exit 1; }

if [ -z "$DEV" ]; then
	echo "Specify the SD card: DEV=/dev/sdX. Removable devices:"
	lsblk -d -o NAME,SIZE,TRAN,RM,MODEL | awk 'NR==1 || $4==1'
	exit 1
fi
[ -f "$FILE" ] || die "$FILE not found: build it first"
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
read -r -p "Write $(basename "$FILE") to $DEV at sector $SECTOR? Data on $DEV will be lost. Type 'yes': " answer
[ "$answer" = yes ] || die "aborted"

for part in $(lsblk -lnpo NAME,MOUNTPOINT "$DEV" | awk '$2 != "" {print $1}'); do
	sudo umount "$part"
done
sudo dd if="$FILE" of="$DEV" bs=4M seek=$(( SECTOR * 512 )) oflag=seek_bytes conv=fsync status=progress
sync
echo "Done."
