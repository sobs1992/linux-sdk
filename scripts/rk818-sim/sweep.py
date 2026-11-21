#!/usr/bin/env python3
"""The matrix over each tuning constant of the rk818 driver at the edges of
its tested range (noted at the constant): every cell must pass there.
mutate.py takes values far outside them, where a cell must fail; just
outside a range the matrix need not fail.

  scripts/rk818-sim/sweep.py [CONSTANT...]
"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(os.path.dirname(HERE))
DRV = os.path.join(SDK, "output/ogu/linux-src/drivers/power/supply/rk818_battery.c")
V = {
 "RESERVE_PCT": [2, 4], "LEARN_REST_MIN": [20, 40], "OCV_LEVEL_REST_MIN": [100, 150], "BROWNOUT_PCT": [8, 11],
 "INITIAL_FCC_PCT": [70, 76], "ZERO_UNCERT_PCT": [4, 6], "CHARGE_SEEN_MAH": [8, 20], "SLEEP_ZERO_MA": [205, 225],
 "REST_SLEEP_MIN": [55, 75], "DISCHARGE_POL_MV_PER_A": [25, 50], "FULL_KEEP_PCT": [3, 8], "BAL_MIN_MIN": [45, 90],
 "BOOT_GAS_TOL": [1, 2], "FCC_MAX_PCT": [130, 200], "BAL_STEP_MAX": [40, 64], "BAL_CHARGE_MIN_PCT": [1],
}
src = open(DRV).read()
want = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix="rk818-sweep.", dir=os.environ.get("TMPDIR")) as tmp:
    for k, vals in V.items():
        if want and k not in want: continue
        m = re.search(r"#define %s(\s+)(-?\d+)" % k, src)
        for v in vals:
            mut = os.path.join(tmp, "d.c")
            open(mut, "w").write(src[:m.start()] + "#define %s%s%d" % (k, m.group(1), v) + src[m.end():])
            r = subprocess.run(["sh", "-c", "ulimit -v 2000000; sh %s/run.sh" % HERE],
                               capture_output=True, text=True, env=dict(os.environ, DRIVER=mut, TMPDIR=tmp))
            fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL ")]
            print("%-24s %-5s %s" % (k, v, "ok" if not fails else " | ".join(f[5:120] for f in fails)), flush=True)
