#!/bin/sh
# Buildroot post-build hook of the ODROID-GO Ultra, after the common one.
#   $1  target dir
# The mdev daemon and the module coldplug start early, in the background
# (the overlay's /etc/init.d/S03mdev): Buildroot's S10mdev would do them a
# second time.
set -e
rm -f "$1/etc/init.d/S10mdev"

# The system bus and bluetoothd start with a Bluetooth adapter, not at boot
# (the overlay's /etc/init.d/S40bluetooth): renamed so that rcS leaves them.
for d in S30dbus-daemon:dbus-daemon S40bluetoothd:bluetoothd; do
	if [ -e "$1/etc/init.d/${d%%:*}" ]; then
		mv -f "$1/etc/init.d/${d%%:*}" "$1/etc/init.d/${d#*:}"
	fi
done
# The keys of the paired devices stay on the data partition, through a
# reflash of the system
if [ -d "$1/var/lib/bluetooth" ] && [ ! -L "$1/var/lib/bluetooth" ]; then
	rm -rf "$1/var/lib/bluetooth"
fi
mkdir -p "$1/var/lib"
ln -sfn /data/bluetooth "$1/var/lib/bluetooth"
