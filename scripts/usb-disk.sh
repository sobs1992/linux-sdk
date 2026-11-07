#!/bin/bash
# Print the block device (/dev/sdX) of a USB disk by its USB id, e.g. a
# board's eMMC shown by U-Boot "ums". Nothing (and a note on stderr) if
# there is none or more than one.
# Usage: usb-disk.sh <vendor>:<product>
set -euo pipefail

id=${1:-}
[ -n "$id" ] || { echo "usb-disk: no USB id given" >&2; exit 0; }
vendor=${id%%:*} product=${id##*:}

found=()
for blk in /sys/block/sd*; do
	[ -e "$blk" ] || continue
	dev=$(readlink -f "$blk/device")
	# Up the sysfs path to the USB device that has the ids
	while [ "$dev" != / ] && [ ! -f "$dev/idVendor" ]; do dev=$(dirname "$dev"); done
	[ -f "$dev/idVendor" ] || continue
	if [ "$(cat "$dev/idVendor")" = "$vendor" ] && [ "$(cat "$dev/idProduct")" = "$product" ]; then
		found+=("/dev/$(basename "$blk")")
	fi
done

case ${#found[@]} in
0) echo "usb-disk: no USB disk $id: is the board in USB disk mode and the cable in?" >&2 ;;
1) echo "${found[0]}" ;;
*) echo "usb-disk: several USB disks $id (${found[*]}): pass DEV=" >&2 ;;
esac
