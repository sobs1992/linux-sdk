#!/bin/sh
# Compile a .dtso overlay with the kernel's dt-bindings headers.
#   build-overlay.sh <linux source dir> <in.dtso> <out.dtbo>
set -e
LINUX=$1 IN=$2 OUT=$3
cpp -nostdinc -undef -D__DTS__ -x assembler-with-cpp \
    -I "$LINUX/include" -I "$LINUX/scripts/dtc/include-prefixes" "$IN" |
    dtc -@ -q -I dts -O dtb -o "$OUT" -
