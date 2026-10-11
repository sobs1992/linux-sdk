#!/bin/sh
# board-check.sh: automatic report on a running board (OdroidLinux SDK).
#
# Runs with busybox sh, needs no extra packages. Prints one line per check:
#   OK    works as expected
#   WARN  worth a look (may be normal for this board)
#   FAIL  broken
#   INFO  facts to write into the test report
# Exit code: number of FAIL lines.

fails=0
ok()      { printf 'OK    %s\n' "$*"; }
warn()    { printf 'WARN  %s\n' "$*"; }
fail()    { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
info()    { printf 'INFO  %s\n' "$*"; }
section() { printf '\n== %s\n' "$*"; }
first()   { [ -r "$1" ] && head -n 1 "$1" 2>/dev/null; }

section "System"
model=$(tr -d '\000' 2>/dev/null < /proc/device-tree/model)
info "model:   ${model:-unknown}"
info "kernel:  $(uname -r) ($(uname -m))"
info "cmdline: $(cat /proc/cmdline)"
info "CPUs:    $(grep -c '^processor' /proc/cpuinfo), RAM: $(awk '/^MemTotal/ {print int($2 / 1024) " MiB"}' /proc/meminfo)"
info "uptime:  $(cut -d' ' -f1 /proc/uptime) s"

section "Storage"
rootline=$(awk '$2 == "/" && $1 != "rootfs" {print $1, $3, $4}' /proc/mounts | tail -n 1)
case "$rootline" in
*" rw,"*|*" rw") ok "rootfs: $rootline" ;;
"")              fail "rootfs not found in /proc/mounts" ;;
*)               fail "rootfs mounted read-only: $rootline" ;;
esac
if grep -q ' /boot ' /proc/mounts; then
	ok "/boot: $(awk '$2 == "/boot" {print $1, $3}' /proc/mounts)"
	[ -r /boot/extlinux/extlinux.conf ] && ok "/boot/extlinux/extlinux.conf readable" ||
		fail "/boot/extlinux/extlinux.conf missing"
else
	fail "/boot not mounted (fstab: LABEL=BOOT)"
fi
if dd if=/dev/zero of=/root/.board-check bs=1024 count=4096 2>/dev/null && sync &&
   [ "$(wc -c < /root/.board-check)" -eq 4194304 ]; then
	ok "rootfs write test (4 MiB)"
else
	fail "rootfs write test"
fi
rm -f /root/.board-check 2>/dev/null
df -h / 2>/dev/null | tail -n 1 | sed 's/^/INFO  /'
grep -q ' /boot ' /proc/mounts && df -h /boot | tail -n 1 | sed 's/^/INFO  /'

section "Kernel"
moddir=/lib/modules/$(uname -r)
if [ -d "$moddir" ]; then
	ok "modules for this kernel: $moddir ($(find "$moddir" -name '*.ko*' | wc -l) files)"
else
	fail "no $moddir: modules do not match the kernel (rebuild the image)"
fi
info "loaded modules: $(wc -l < /proc/modules)"
if log=$(dmesg 2>/dev/null); then
	if echo "$log" | grep -q -E 'Oops|BUG:|Call trace:|Kernel panic'; then
		fail "kernel oops/BUG in dmesg: dmesg | grep -n -E 'Oops|BUG:|Call trace'"
	else
		ok "no oops/BUG in dmesg"
	fi
	n=$(echo "$log" | grep -c -i -E 'error|failed')
	[ "$n" -eq 0 ] && ok "no error/failed lines in dmesg" ||
		warn "$n error/failed lines in dmesg: dmesg | grep -i -E 'error|failed'"
else
	warn "dmesg not readable (run as root)"
fi
mount -t debugfs none /sys/kernel/debug 2>/dev/null
if [ -r /sys/kernel/debug/devices_deferred ]; then
	d=$(cat /sys/kernel/debug/devices_deferred)
	[ -z "$d" ] && ok "no deferred devices" ||
		warn "deferred devices (driver or supplier missing): $(echo "$d" | tr '\n' ';')"
fi

section "Consoles and display"
ttys=""
for p in /proc/[0-9]*; do
	cmd=$(tr '\000' ' ' 2>/dev/null < "$p/cmdline")
	case "$cmd" in
	*/getty\ *|getty\ *) ttys="$ttys $(echo "$cmd" | awk '{for (i = 2; i <= NF; i++) if ($i ~ /^tty/) {print $i; exit}}')" ;;
	esac
done
[ -n "$ttys" ] && ok "login (getty) on:$ttys" || warn "no getty running"
if [ -e /dev/fb0 ]; then
	ok "framebuffer fb0: $(first /sys/class/graphics/fb0/virtual_size | tr ',' 'x'), $(first /sys/class/graphics/fb0/bits_per_pixel) bpp, $(first /sys/class/graphics/fb0/name)"
else
	warn "no /dev/fb0 (no display driver or no display connected)"
fi
[ -r /sys/class/graphics/fbcon/rotate ] && info "fbcon rotate: $(first /sys/class/graphics/fbcon/rotate)"
for b in /sys/class/backlight/*; do
	[ -d "$b" ] && info "backlight $(basename "$b"): $(first "$b/brightness")/$(first "$b/max_brightness")"
done

section "Input"
found=0
for e in /sys/class/input/event*; do
	[ -d "$e" ] || continue
	found=1
	info "$(basename "$e"): $(first "$e/device/name")"
done
[ "$found" -eq 1 ] || warn "no input devices"

section "LEDs"
for l in /sys/class/leds/*; do
	[ -d "$l" ] && info "$(basename "$l"): trigger $(sed -n 's/.*\[\(.*\)\].*/\1/p' "$l/trigger")"
done

section "Sound"
if [ -r /proc/asound/cards ] && grep -q '^ *[0-9]' /proc/asound/cards; then
	grep '^ *[0-9]' /proc/asound/cards | sed 's/^ */OK    sound card /'
else
	warn "no sound cards"
fi

section "Network"
for n in /sys/class/net/*; do
	i=$(basename "$n")
	[ "$i" = lo ] && continue
	addr=$(ip -4 addr show dev "$i" 2>/dev/null | awk '/inet / {print $2}')
	state=$(first "$n/operstate")
	if [ -n "$addr" ]; then ok "$i: $state, $addr"; else warn "$i: $state, no IPv4 address"; fi
done
[ -n "$(ip route 2>/dev/null | grep '^default')" ] && ok "default route: $(ip route | grep '^default')" ||
	info "no default route"
pidof dropbear >/dev/null && ok "SSH server (dropbear) running" || info "no SSH server"

section "Buses"
info "GPIO chips: $(ls /dev/gpiochip* 2>/dev/null | tr '\n' ' ')"
for g in /sys/bus/gpio/devices/gpiochip*; do
	# the parent device names the controller: ff040000.gpio, 4804c000.gpio, ...
	[ -e "$g" ] && info "  $(basename "$g"): $(basename "$(dirname "$(readlink -f "$g")")")"
done
for b in /sys/bus/i2c/devices/i2c-*; do
	[ -d "$b" ] && info "I2C $(basename "$b"): $(first "$b/name")"
done
usb=$(ls /sys/bus/usb/devices 2>/dev/null | grep -c -v ':')
info "USB devices (incl. root hubs): $usb"
for u in /sys/bus/usb/devices/*; do
	[ -r "$u/product" ] && info "  $(basename "$u"): $(first "$u/product")"
done

section "Clock, sensors, power"
if [ -e /dev/rtc0 ]; then
	ok "RTC: $(first /sys/class/rtc/rtc0/name), $(first /sys/class/rtc/rtc0/date) $(first /sys/class/rtc/rtc0/time)"
else
	warn "no /dev/rtc0"
fi
info "system time: $(date)"
for t in /sys/class/thermal/thermal_zone*; do
	[ -r "$t/temp" ] && info "$(first "$t/type"): $(( $(first "$t/temp") / 1000 )) C"
done
c=/sys/devices/system/cpu/cpu0/cpufreq
if [ -d "$c" ]; then
	ok "cpufreq: $(( $(first $c/scaling_cur_freq) / 1000 )) MHz, governor $(first $c/scaling_governor), available: $(first $c/scaling_available_frequencies)"
else
	info "no cpufreq (CPU frequency is fixed)"
fi
for p in /sys/class/power_supply/*; do
	[ -d "$p" ] && info "power $(basename "$p"): $(first "$p/type") $(first "$p/status") $(first "$p/capacity")"
done

section "Summary"
[ "$fails" -eq 0 ] && echo "no FAIL lines" || echo "$fails FAIL line(s)"
exit "$fails"
