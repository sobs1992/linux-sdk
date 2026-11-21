#!/bin/sh
# Builds rk818-sim against the patched kernel tree (make FW=ogu linux) and
# runs it over a battery.raw log of bare_app (a discharge from full):
#   scripts/rk818-sim/run.sh [RAW...]      default: the 2026-11-21 one of ogu2
# The FCC must converge from below and from above, the level never rise on
# the battery (also with the counter run out), and a partial charge midway
# must not teach a brown-out.
set -e
here=$(cd "$(dirname "$0")" && pwd)
sdk=$(cd "$here/../.." && pwd)
work=${TMPDIR:-/tmp}/rk818-sim.$$
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT
drv="$sdk/output/ogu/linux-src/drivers/power/supply/rk818_battery.c"
[ -f "$drv" ] || { echo "no $drv: make FW=ogu linux first" >&2; exit 1; }
gcc -O1 -w -I "$here/include" -include "$here/include/kstub.h" -DDRIVER="\"$drv\"" \
	"$here/rk818-sim.c" -o "$work/sim"
[ $# -gt 0 ] || set -- "$sdk/lab/wip/battery-192.168.8.2/2026-11-21/battery.raw.prev" \
	"$sdk/lab/wip/battery-192.168.8.2/2026-11-21/battery.raw"
BATTERY_FIT="$sdk/scripts/battery-fit.py" python3 - "$work/trace" "$@" <<'PY'
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location("bf", os.environ["BATTERY_FIT"])
bf = importlib.util.module_from_spec(spec); spec.loader.exec_module(bf)
first, run, _ = bf.last_discharge(bf.load(sys.argv[2:]))
t0 = run[0]["mono_ms"]
with open(sys.argv[1], "w") as f:
    for r in run:
        f.write("%d %d %d 0 0\n" % (r["mono_ms"] - t0, r["mv"], r["ma"]))
PY
fail=0
for fcc in 4000 5900; do
	"$work/sim" "$work/trace" $fcc 4 > "$work/out"
	grep -o "FCC [0-9]* mAh, [0-9]* -> [0-9]* mAh" "$work/out" | sed "s/^/from $fcc: /"
	grep -q "rises on battery: [1-9]" "$work/out" && { echo "from $fcc: the level rose on the battery"; fail=1; }
	last=$(grep -o "\-> [0-9]* mAh" "$work/out" | tail -1 | grep -o "[0-9]*")
	[ -n "$last" ] && [ $((last > 4600 && last < 5000)) = 1 ] || { echo "from $fcc: FCC $last not near 4800"; fail=1; }
done
MID=1 "$work/sim" "$work/trace" 4800 1 > "$work/out"
grep -q "not a brown-out" "$work/out" || { echo "midway charge: learnt as a brown-out"; fail=1; }
# the counter runs out long before the brown-out (2026-11-20): the level
# stays at 0 on the battery, and the brown-out teaches the FCC
NO_BARE_APP=1 "$work/sim" "$work/trace" 4000 1 > "$work/out"
grep -q "rises on battery: 0" "$work/out" || { echo "no bare_app: the level rose on the battery"; fail=1; }
grep -q "brown-out: dsoc 0 " "$work/out" || { echo "no bare_app: not at 0 at the brown-out"; fail=1; }
grep -q "to a brown-out.*-> 48[0-9][0-9] mAh" "$work/out" || { echo "no bare_app: the brown-out taught nothing"; fail=1; }
[ $fail = 0 ] && echo PASS || echo FAIL
exit $fail
