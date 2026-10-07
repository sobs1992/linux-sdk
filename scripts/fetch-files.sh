#!/bin/bash
# Download files from <base url>/<file> into a cache dir, check them against
# a sha256sum-format hash file and copy them to <out dir>.
#
# Usage: fetch-files.sh <base url> <cache dir> <hash file> <out dir> <file>...
set -euo pipefail

URL=$1 CACHE=$2 HASHES=$3 OUT=$4
shift 4

die() { echo "fetch-files: $*" >&2; exit 1; }
[ -f "$HASHES" ] || die "hash file $HASHES not found"

mkdir -p "$CACHE" "$OUT"
for f in "$@"; do
	want=$(awk -v f="$f" '$2 == f { print $1 }' "$HASHES")
	[ -n "$want" ] || die "no hash for $f in $HASHES"
	if [ ! -f "$CACHE/$f" ] || [ "$(sha256sum "$CACHE/$f" | cut -d' ' -f1)" != "$want" ]; then
		echo ">>> Downloading $URL/$f"
		wget -q -O "$CACHE/$f.tmp" "$URL/$f" || die "download of $URL/$f failed"
		got=$(sha256sum "$CACHE/$f.tmp" | cut -d' ' -f1)
		[ "$got" = "$want" ] || { rm -f "$CACHE/$f.tmp"; die "$f: sha256 $got, expected $want"; }
		mv "$CACHE/$f.tmp" "$CACHE/$f"
	fi
	cp "$CACHE/$f" "$OUT/$f"
done
