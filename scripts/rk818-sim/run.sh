#!/bin/sh
# Builds rk818-sim against the patched kernel tree (make FW=ogu linux) and
# runs its scenario matrix (rk818-sim.c): the current's zero, boots after a
# panic, a reboot, a brown-out, a power-off; the level's rules; the FCC's
# learning; sleep and hibernation; the log.
#   scripts/rk818-sim/run.sh [CELL...]      DRIVER=FILE: another driver source,
#                                           SIM=FILE: another rk818-sim.c
set -e
here=$(cd "$(dirname "$0")" && pwd)
sdk=$(cd "$here/../.." && pwd)
work=${TMPDIR:-/tmp}/rk818-sim.$$
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT
drv=${DRIVER:-"$sdk/output/ogu/linux-src/drivers/power/supply/rk818_battery.c"}
[ -f "$drv" ] || { echo "no $drv: make FW=ogu linux first" >&2; exit 1; }
gcc -O1 -w -I "$here/include" -include "$here/include/kstub.h" -DDRIVER="\"$drv\"" \
	"${SIM:-$here/rk818-sim.c}" -o "$work/sim" -lm
if "$work/sim" "$@"; then echo PASS; else echo FAIL; exit 1; fi
