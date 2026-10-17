#!/bin/sh
# Buildroot post-build hook for the OGA (runs after board/common's one).
#   $1  target dir
# Wi-Fi networks from board/oga/buildroot/wifi.conf (not in git: it holds
# passwords) are appended to /etc/wpa_supplicant.conf. The overlay copy is
# fresh on every build, so appending does not pile up.
set -e
TARGET_DIR="$1"
WIFI_CONF="$(dirname "$0")/wifi.conf"

if [ -f "$WIFI_CONF" ]; then
	echo "Adding Wi-Fi networks from $WIFI_CONF"
	cat "$WIFI_CONF" >> "$TARGET_DIR/etc/wpa_supplicant.conf"
	chmod 600 "$TARGET_DIR/etc/wpa_supplicant.conf"
fi
