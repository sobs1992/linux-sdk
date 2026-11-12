#!/bin/bash
# Pack mainline U-Boot (BL33) with Amlogic's BL2/BL30/BL31 and DDR firmware
# into the signed boot image ("FIP") that the G12B BootROM loads from sector
# 1 of the eMMC or SD card. The same steps as g12a.inc of LibreELEC's
# amlogic-boot-fip (aml_encrypt_g12b, --level v3), without its Makefile.
#
# Outputs in <out dir>:
#   u-boot-fip.bin      the FIP: written from sector 1 on
#   u-boot-fip-mbr.bin  the first 440 bytes of u-boot.bin.sd.bin: the boot
#                       code part of sector 0 (the partition table is kept)
#
# aml_encrypt_g12b is an x86-64 Linux binary; on other hosts it runs under
# qemu-x86_64 (QEMU_LD_PREFIX).
#
# AML_DDR_FREQ=<MT/s> (optional): acs.bin holds two DDR configurations that
# BL2 tries in turn, the next one when a configuration fails its training
# or its data or address bus test. The first becomes a copy of the second
# at this data rate, the second stays as it is: BL2 falls back to the
# blob's own rate whenever the slower one does not work. For boards whose
# first configuration never trains (the ODROID-GO Ultra's is for two ranks).
#
# Usage: [AML_DDR_FREQ=<MT/s>] amlogic-fip.sh <blob dir> <u-boot.bin> <out dir>
set -euo pipefail

BLOBS=$(readlink -f "$1") BL33=$(readlink -f "$2") OUT=$(readlink -f "$3")

die() { echo "amlogic-fip: $*" >&2; exit 1; }
[ -f "$BL33" ] || die "missing $BL33: build U-Boot first"
for f in aml_encrypt_g12b bl2.bin acs.bin bl30.bin bl301.bin bl31.img \
	ddr4_1d.fw ddr4_2d.fw ddr3_1d.fw piei.fw lpddr4_1d.fw lpddr4_2d.fw \
	diag_lpddr4.fw aml_ddr.fw; do
	[ -f "$BLOBS/$f" ] || die "missing $BLOBS/$f"
done
[ ! -e "$BLOBS/lpddr3_1d.fw" ] || die "lpddr3_1d.fw is not supported by this script"

QEMU=
if [ "$(uname -m)" != x86_64 ]; then
	QEMU="qemu-x86_64 -L ${QEMU_LD_PREFIX:-/usr/x86_64-linux-gnu/}"
fi
chmod +x "$BLOBS/aml_encrypt_g12b"
enc() { $QEMU "$BLOBS/aml_encrypt_g12b" "$@" >/dev/null; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# <a> padded with zeros to <a limit>, then <b> padded to <b limit> (blx_fix.sh)
pad2() {
	local a=$1 a_lim=$2 b=$3 b_lim=$4 out=$5
	[ "$(stat -c %s "$a")" -le "$a_lim" ] || die "$(basename "$a") is larger than $a_lim bytes"
	[ "$(stat -c %s "$b")" -le "$b_lim" ] || die "$(basename "$b") is larger than $b_lim bytes"
	{ cat "$a"; head -c $(( a_lim - $(stat -c %s "$a") )) /dev/zero
	  cat "$b"; head -c $(( b_lim - $(stat -c %s "$b") )) /dev/zero; } > "$out"
}

ACS=$BLOBS/acs.bin
if [ -n "${AML_DDR_FREQ:-}" ]; then
	# ddr_set_t (Amlogic's arch-g12b/timing.h, 0x270 bytes, magic "cfg.")
	# at 0x10 and 0x280; DRAMFreq[0] at 52 in it
	ACS=$TMP/acs.bin
	python3 - "$BLOBS/acs.bin" "$ACS" "$AML_DDR_FREQ" <<'PY' || die "acs.bin: cannot set the DDR rate"
import struct, sys
d = bytearray(open(sys.argv[1], 'rb').read())
first, second, size = 0x10, 0x280, 0x270
assert d[first:first + 4] == b'cfg.' and d[second:second + 4] == b'cfg.', 'no ddr_set_t at 0x10 and 0x280'
d[first:first + size] = d[second:second + size]
struct.pack_into('<H', d, first + 52, int(sys.argv[3]))
open(sys.argv[2], 'wb').write(d)
PY
	echo "acs.bin: DDR at $AML_DDR_FREQ MT/s first, then $(python3 -c "import struct,sys; print(struct.unpack_from('<H', open(sys.argv[1],'rb').read(), 0x280 + 52)[0])" "$BLOBS/acs.bin") MT/s"
fi

pad2 "$BLOBS/bl30.bin" 40960 "$BLOBS/bl301.bin" 13312 "$TMP/bl30_new.bin"
pad2 "$BLOBS/bl2.bin" 57344 "$ACS" 4096 "$TMP/bl2_new.bin"

enc --bl30sig --input "$TMP/bl30_new.bin" --output "$TMP/bl30_new.bin.g12a.enc" --level v3
enc --bl3sig --input "$TMP/bl30_new.bin.g12a.enc" --output "$TMP/bl30_new.bin.enc" --level v3 --type bl30
enc --bl3sig --input "$BLOBS/bl31.img" --output "$TMP/bl31.img.enc" --level v3 --type bl31
enc --bl3sig --input "$BL33" --output "$TMP/bl33.bin.enc" --level v3 --type bl33
enc --bl2sig --input "$TMP/bl2_new.bin" --output "$TMP/bl2.n.bin.sig"
(cd "$BLOBS" && enc --bootmk --output "$TMP/u-boot.bin" --level v3 \
	--bl2 "$TMP/bl2.n.bin.sig" --bl30 "$TMP/bl30_new.bin.enc" \
	--bl31 "$TMP/bl31.img.enc" --bl33 "$TMP/bl33.bin.enc" \
	--ddrfw1 ddr4_1d.fw --ddrfw2 ddr4_2d.fw --ddrfw3 ddr3_1d.fw \
	--ddrfw4 piei.fw --ddrfw5 lpddr4_1d.fw --ddrfw6 lpddr4_2d.fw \
	--ddrfw7 diag_lpddr4.fw --ddrfw8 aml_ddr.fw)

# u-boot.bin.sd.bin = a 512-byte sector 0 + the FIP. Only its boot code
# (440 bytes) is used: mkimage.sh writes the partition table itself.
SD=$TMP/u-boot.bin.sd.bin
[ -f "$SD" ] || die "aml_encrypt_g12b made no u-boot.bin.sd.bin"
tail -c +513 "$SD" | cmp -s - "$TMP/u-boot.bin" || die "u-boot.bin.sd.bin is not sector 0 + u-boot.bin"
# The BootROM checks the "@AML" magic of the BL2 header at 0x10 of sector 1
[ "$(dd if="$TMP/u-boot.bin" bs=1 skip=16 count=4 status=none)" = "@AML" ] || die "no @AML header in the FIP"

mkdir -p "$OUT"
cp "$TMP/u-boot.bin" "$OUT/u-boot-fip.bin"
head -c 440 "$SD" > "$OUT/u-boot-fip-mbr.bin"
echo "FIP: $OUT/u-boot-fip.bin ($(( $(stat -c %s "$OUT/u-boot-fip.bin") / 1024 )) KiB)"
