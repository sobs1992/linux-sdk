#!/bin/sh
# Buildroot post-build hook for the OGA (runs after board/common's one).
#   $1  target dir
# Wi-Fi networks from board/oga/buildroot/wifi.conf (not in git: it holds
# passwords) are appended to /etc/wpa_supplicant.conf. The overlay copy is
# fresh on every build, so appending does not pile up.
# The mdev daemon and the module coldplug start early, in the background
# (the overlay's /etc/init.d/S03mdev): Buildroot's S10mdev would do them a
# second time.
set -e
TARGET_DIR="$1"
rm -f "$TARGET_DIR/etc/init.d/S10mdev"
WIFI_CONF="$(dirname "$0")/wifi.conf"

if [ -f "$WIFI_CONF" ]; then
	echo "Adding Wi-Fi networks from $WIFI_CONF"
	cat "$WIFI_CONF" >> "$TARGET_DIR/etc/wpa_supplicant.conf"
	chmod 600 "$TARGET_DIR/etc/wpa_supplicant.conf"
fi
