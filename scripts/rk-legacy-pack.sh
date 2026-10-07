#!/bin/bash
# Pack mainline U-Boot proper and BL31 in Rockchip legacy format, for boards
# whose SPI flash holds Rockchip's DDR blob + miniloader (e.g. the factory
# loader of ODROID-GO Advance Black Edition). The miniloader loads
# uboot.img from sector 16384 and trust.img from sector 24576 of the SD card.
#
# Usage: rk-legacy-pack.sh <rkbin dir> <u-boot objdir> <bl31.elf> <out dir>
set -euo pipefail

RKBIN=$1 UBOOT_OUT=$2 BL31=$3 OUT=$4

die() { echo "rk-legacy-pack: $*" >&2; exit 1; }
[ -x "$RKBIN/tools/loaderimage" ] || die "$RKBIN/tools/loaderimage not found"
[ -x "$RKBIN/tools/trust_merger" ] || die "$RKBIN/tools/trust_merger not found"
[ -f "$BL31" ] || die "BL31 $BL31 not found"

load_addr=$(sed -n 's/^CONFIG_TEXT_BASE=//p' "$UBOOT_OUT/.config")
[ -n "$load_addr" ] || die "CONFIG_TEXT_BASE not found in $UBOOT_OUT/.config"

mkdir -p "$OUT"
"$RKBIN/tools/loaderimage" --pack --uboot "$UBOOT_OUT/u-boot-dtb.bin" "$OUT/uboot.img" "$load_addr" >/dev/null

# BL31 only: without a BL32 the kernel needs no OP-TEE memory reservation
work=$UBOOT_OUT/rk-legacy
mkdir -p "$work"
cat > "$work/trust.ini" <<EOF
[VERSION]
MAJOR=1
MINOR=0
[BL30_OPTION]
SEC=0
[BL31_OPTION]
SEC=1
PATH=$(realpath "$BL31")
ADDR=0x00040000
[BL32_OPTION]
SEC=0
[BL33_OPTION]
SEC=0
[OUTPUT]
PATH=$(realpath "$OUT")/trust.img
EOF
(cd "$work" && "$(realpath "$RKBIN")/tools/trust_merger" --pack trust.ini >/dev/null)

echo "uboot.img: $(stat -c %s "$OUT/uboot.img") bytes, load address $load_addr"
echo "trust.img: $(stat -c %s "$OUT/trust.img") bytes, BL31 $(basename "$BL31")"
