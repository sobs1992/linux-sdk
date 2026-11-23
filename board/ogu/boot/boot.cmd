# A/B system slots (docs/boards/ogu.md, "Обновление системы"): U-Boot's
# distro boot runs this, boot.scr (mkimage -T script), from BOOT (p1) of
# the disk it scans, ${devtype} ${devnum}. BOOT has no extlinux.conf of its
# own, or that would be booted first.
#
# A slot is an ext4 system with its kernel, dtbs and
# /boot/extlinux/extlinux.conf (root= its own partition): slot a is p2,
# slot b p4. Which one boots says one sector of the disk, ab_sector
# (/usr/sbin/ab-state writes it from Linux; zeros: slot a), "name=value"
# lines:
#   ab_slot    the slot that booted to its end last (a, b)
#   ab_try     a slot to boot instead (an update wrote it), none: none
#   ab_left    boots of ab_try left: each start here takes one; with none
#              left the board goes back to ab_slot and says so
#              (ab_failed=that slot) - Linux commits the slot it booted
#              to the end (S99ab): ab_slot = it, ab_try = none
#   ab_failed  the slot given up on last, none: none
# A slot without its extlinux.conf (never written) or whose kernel does
# not load is passed over at once: the other one. With neither, the
# kernel of BOOT itself (/extlinux/fallback.conf), root on p2.
#
# Only commands of this U-Boot: no setexpr, so the boots left count down
# by name.

setenv ab_sector 0x7f00
setenv ab_slot
setenv ab_try
setenv ab_left
setenv ab_failed
mw.b ${loadaddr} 0 0x200
if mmc dev ${devnum} && mmc read ${loadaddr} ${ab_sector} 1; then
	env import -t ${loadaddr} 0x200 ab_slot ab_try ab_left ab_failed
fi
if test "${ab_slot}" != b; then setenv ab_slot a; fi
if test "${ab_try}" != a && test "${ab_try}" != b; then setenv ab_try none; fi
if test -z "${ab_failed}"; then setenv ab_failed none; fi

setenv ab_boot ${ab_slot}
if test "${ab_try}" != none; then
	if test "${ab_left}" = 3; then
		setenv ab_left 2
		setenv ab_boot ${ab_try}
	elif test "${ab_left}" = 2; then
		setenv ab_left 1
		setenv ab_boot ${ab_try}
	elif test "${ab_left}" = 1; then
		setenv ab_left 0
		setenv ab_boot ${ab_try}
	else
		echo "A/B: slot ${ab_try} did not start, back to slot ${ab_slot}"
		setenv ab_failed ${ab_try}
		setenv ab_try none
		setenv ab_left 0
	fi
	mw.b ${loadaddr} 0 0x200
	env export -t ${loadaddr} ab_slot ab_try ab_left ab_failed
	mmc write ${loadaddr} ${ab_sector} 1
fi

if test "${ab_boot}" = b; then
	setenv ab_parts "4 2"
else
	setenv ab_parts "2 4"
fi
for ab_part in ${ab_parts}; do
	if test -e ${devtype} ${devnum}:${ab_part} /boot/extlinux/extlinux.conf; then
		echo "A/B: slot on ${devtype} ${devnum}:${ab_part}"
		sysboot ${devtype} ${devnum}:${ab_part} any ${pxefile_addr_r} /boot/extlinux/extlinux.conf
		echo "A/B: ${devtype} ${devnum}:${ab_part} did not boot"
	fi
done
echo "A/B: no slot boots: the kernel of BOOT"
sysboot ${devtype} ${devnum}:1 any ${pxefile_addr_r} /extlinux/fallback.conf
