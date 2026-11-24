#!/bin/sh
# run-scan.sh CMD...: run ddr-eyescan commands (EYESCAN: another binary) (one per argument) with /data frozen; always thaws
sync
fsfreeze --freeze /data && echo frozen
( sleep 1200; fsfreeze --unfreeze /data 2>/dev/null ) & T=$!
trap 'fsfreeze --unfreeze /data 2>/dev/null; kill $T 2>/dev/null; echo unfrozen' EXIT INT TERM HUP
for c in "$@"; do echo "=== $c"; sh -c "${EYESCAN:-ddr-eyescan} $c" 2>&1 | grep -v "errors 0,"; sleep 1; done
