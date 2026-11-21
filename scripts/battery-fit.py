#!/usr/bin/env python3
"""The battery's model from bare_app's raw readings (<battery_log>.raw).

bare_app (services/battlog.c) writes a line every 5 s: the voltage and the
current of the same moment, the driver's level, the state. A new file starts
when the battery turns full on the charger, the cycle before is kept as
.raw.prev. From the last discharge that began full this works out:

  - the capacity: the charge drawn from full to the last reading (bare_app
    powers off below 3.3 V, so that is the usable charge to the cut-off);
  - the resistance R and the OCV curve: V = OCV(SoC) + R * I fitted by least
    squares, OCV one unknown per SoC bin, R one for the whole run;
  - the OCV table for the device tree (ocv-capacity-table-0, every 5 %);
  - how far the driver's level was from the true state of charge.

  battery-fit.py --host 192.168.8.2            fetch from the device and fit
  battery-fit.py FILE [FILE...]                 fit local files (.raw.prev first)
  battery-fit.py --selftest                     fit a made-up battery, check it
  battery-fit.py --current-offset-ma 578 FILE   the same with the readings' zero corrected

The results go to --out (default lab/wip/battery-<host>/<date>/): the raw files,
report.md, fit.json, fit.png.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

import numpy as np

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SSH = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
F_ONLINE, F_FULL = 1, 2
GAP_MS = 30000          # longer between two readings: asleep, off or restarted
BIN = 1.0               # % of the SoC per OCV unknown
STATES = ["menu", "game", "screen off", "sleep", "off"]

# the device tree's table now (meson-g12b-odroid-go-ultra.dts), uV -> %
DT_OCV = [(4082960, 100), (4045980, 95), (4009010, 90), (3972010, 85), (3934350, 80),
          (3895710, 75), (3862500, 70), (3841170, 65), (3818400, 60), (3780330, 55),
          (3739860, 50), (3714430, 45), (3700410, 40), (3684780, 35), (3664670, 30),
          (3648220, 25), (3640160, 20), (3634280, 15), (3624410, 10), (3617000, 5),
          (3610000, 0)]


def load(paths):
    rows = []
    for p in paths:
        with open(p) as f:
            head = f.readline().strip().split(",")
            for line in f:
                v = line.rstrip("\n").split(",")
                if len(v) < len(head):
                    continue
                r = dict(zip(head, v))
                rows.append({k: (r[k] if k == "game" else int(r[k])) for k in r})
    rows.sort(key=lambda r: r["real_ms"])
    return rows


def last_discharge(rows):
    """The readings off the charger after the last full one on it."""
    full = [i for i, r in enumerate(rows) if r["flags"] & F_FULL]
    starts = [i for i in full if i + 1 < len(rows) and not rows[i + 1]["flags"] & F_ONLINE]
    if not starts:
        sys.exit("no discharge that began full in the readings")
    s = starts[-1]
    e = s + 1
    while e < len(rows) and not rows[e]["flags"] & F_ONLINE:
        e += 1
    return rows[s], rows[s + 1:e], e < len(rows)


def integrate(first, run):
    """Charge drawn (mAh, +) up to each reading; a reading's current counts
    since the one before (as battlog does). Gaps count nothing."""
    q, out, gaps, prev = 0.0, [], [], first
    for r in run:
        dt = r["mono_ms"] - prev["mono_ms"]
        same_boot = r["boot_ms"] >= prev["boot_ms"]
        if same_boot and 0 <= dt <= GAP_MS and r["boot_ms"] - prev["boot_ms"] <= GAP_MS:
            q += -r["ma"] * dt / 3.6e6
        else:
            gaps.append((prev, r))
        out.append(q)
        prev = r
    return np.array(out), gaps


def fit(soc, v, i_a):
    """V = OCV[bin] + R * I: least squares, one OCV a bin, one R."""
    bins = np.clip((soc / BIN).astype(int), 0, int(100 / BIN) - 1)
    used = np.unique(bins)
    col = {b: k for k, b in enumerate(used)}
    a = np.zeros((len(v), len(used) + 1))
    for n, b in enumerate(bins):
        a[n, col[b]] = 1
    a[:, -1] = i_a
    x, *_ = np.linalg.lstsq(a, v, rcond=None)
    resid = v - a @ x
    centres = (used + 0.5) * BIN
    return centres, x[:-1], x[-1], float(np.sqrt(np.mean(resid ** 2)))


PHASE_S = 300           # a steady load at least this long gives an OCV point
STEP_A = 0.4            # a load step: the 30 s mean current moves this much
# the OCV table from the phases of a light load when there are enough: the
# driver reads it at rest, and V - R*I of a phase at 1.6 A is still some
# polarisation below that (fit rms 8.8 mV over all phases, 1.7 over these)
LIGHT_A = 0.6


def plateaus(t, v, i_a, soc):
    """Phases of a steady load: the mean of each one's last minute (SoC, V,
    I) and R of the steps between them (V and I 20 s either side). Under a
    steady load the polarisation has settled: V - R*I of a phase's end is
    the OCV, the 5 s readings of a varying load are not (bin fit)."""
    m30 = np.array([i_a[(t >= x - 30) & (t <= x)].mean() for x in t])
    segs, s0 = [], 0
    for n in range(1, len(t)):
        if abs(m30[n] - m30[s0:n].mean()) > STEP_A:
            segs.append((s0, n))
            s0 = n
    segs.append((s0, len(t)))
    pts, rs = [], []
    prev = None
    for a, b in segs:
        k = np.arange(a, b)
        if t[b - 1] - t[a] < 60:
            prev = None
            continue
        if prev is not None:
            first = k[t[k] - t[a] < 20]
            di = i_a[first].mean() - i_a[prev].mean()
            if abs(di) >= STEP_A:
                rs.append((v[first].mean() - v[prev].mean()) / di)
        last = k[t[k] >= t[b - 1] - 60]
        if t[b - 1] - t[a] >= PHASE_S or b == len(t):
            pts.append((soc[last].mean(), v[last].mean(), i_a[last].mean()))
        prev = k[t[k] >= t[b - 1] - 20]
    return pts, rs


def smooth_table(points, lam=0.3):
    """OCV at 0, 5 ... 100 %: piecewise linear through the points (SoC, V)
    by least squares, its second differences kept small, never falling with
    the SoC; listed 100 % first, strictly falling, as the DT has it."""
    knots = np.arange(0, 101, 5.0)
    xs = np.array([p[0] for p in points])
    ys = np.array([p[1] for p in points])
    h = np.clip(1 - np.abs(xs[:, None] - knots[None, :]) / 5.0, 0, None)
    d = np.zeros((len(knots) - 2, len(knots)))
    for n in range(len(knots) - 2):
        d[n, n:n + 3] = [1, -2, 1]
    x, *_ = np.linalg.lstsq(np.r_[h, lam * d], np.r_[ys, np.zeros(len(d))], rcond=None)
    x = np.maximum.accumulate(x)
    pts = [(int(round(o * 1e5)) * 10, int(c)) for c, o in zip(knots[::-1], x[::-1])]
    for n in range(1, len(pts)):
        if pts[n][0] >= pts[n - 1][0]:
            pts[n] = (pts[n - 1][0] - 10, pts[n][1])
    return pts, float(np.sqrt(np.mean((ys - h @ x) ** 2)))


def table(centres, ocv):
    """OCV at 100, 95 ... 0 %: interpolated, extrapolated at the ends,
    never falling with the SoC."""
    order = np.argsort(centres)
    c, o = centres[order], np.maximum.accumulate(ocv[order])
    pts = []
    for pct in range(100, -1, -5):
        if pct <= c[0]:
            k = (o[1] - o[0]) / (c[1] - c[0]) if len(c) > 1 else 0
            val = o[0] + k * (pct - c[0])
        elif pct >= c[-1]:
            k = (o[-1] - o[-2]) / (c[-1] - c[-2]) if len(c) > 1 else 0
            val = o[-1] + k * (pct - c[-1])
        else:
            val = np.interp(pct, c, o)
        pts.append((int(round(val * 1e6 / 10) * 10), pct))
    for n in range(1, len(pts)):       # strictly falling for the driver's lookup
        if pts[n][0] >= pts[n - 1][0]:
            pts[n] = (pts[n - 1][0] - 10, pts[n][1])
    return pts


def dt_soc(uv):
    """The level the device tree's table gives a voltage (uV)."""
    vs = [p[0] for p in DT_OCV][::-1]
    ps = [p[1] for p in DT_OCV][::-1]
    return float(np.interp(uv, vs, ps))


def analyse(rows):
    first, run, recharged = last_discharge(rows)
    q, gaps = integrate(first, run)
    cap = float(q[-1])
    v = np.array([r["mv"] for r in run]) / 1000.0
    i_a = np.array([r["ma"] for r in run]) / 1000.0
    drv = np.array([r["cap"] for r in run], dtype=float)
    soc = 100.0 * (1 - q / cap)
    keep = (v > 0) & (i_a < 0)
    centres, ocv, r_ohm, rms = fit(soc[keep], v[keep], i_a[keep])
    pts = table(centres, ocv)
    t = np.array([r["mono_ms"] for r in run]) / 1000.0
    phases, steps = plateaus(t[keep], v[keep], i_a[keep], soc[keep])
    method = "bins of 5 s readings"
    if len(phases) >= 6 and steps:
        r_ohm = float(np.median(steps))
        light = [p for p in phases if abs(p[2]) <= LIGHT_A]
        if len(light) >= 6:
            phases = light
        pts, rms = smooth_table([(s_, v_ - r_ohm * i_) for s_, v_, i_ in phases])
        centres = np.array([p[0] for p in phases])
        ocv = np.array([v_ - r_ohm * i_ for _, v_, i_ in phases])
        method = "%d steady phases%s, R the median of %d load steps" % (
            len(phases), " of a light load" if phases is light else "", len(steps))
    err = drv - soc
    t0, t1 = first["real_ms"] / 1000, run[-1]["real_ms"] / 1000
    awake_ms = sum(r["mono_ms"] - p["mono_ms"] for p, r in zip([first] + run[:-1], run)
                   if 0 <= r["mono_ms"] - p["mono_ms"] <= GAP_MS)
    by_state = {}
    prev = first
    for r in run:
        dt = r["mono_ms"] - prev["mono_ms"]
        if 0 <= dt <= GAP_MS:
            key = r["game"] or STATES[r["state"]] if r["state"] < len(STATES) else str(r["state"])
            s = by_state.setdefault(key, [0.0, 0.0])
            s[0] += dt / 1000
            s[1] += -r["ma"] * dt / 3.6e6
        prev = r
    est_ocv = v - r_ohm * i_a
    dt_err = np.array([dt_soc(x * 1e6) for x in est_ocv]) - soc
    return {
        "from": datetime.datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
        "to": datetime.datetime.fromtimestamp(t1).isoformat(timespec="seconds"),
        "hours": (t1 - t0) / 3600, "awake_hours": awake_ms / 3.6e6,
        "readings": len(run), "gaps": len(gaps), "ended_on_charger": recharged,
        "capacity_mah": cap, "mean_ma": cap / (awake_ms / 3.6e6) if awake_ms else 0,
        "end_mv": int(run[-1]["mv"]), "end_ma": int(run[-1]["ma"]), "end_driver_pct": int(drv[-1]),
        "r_mohm": r_ohm * 1000, "fit_rms_mv": rms * 1000,
        "ocv_table": pts, "method": method,
        "driver_err_max": float(np.max(np.abs(err))), "driver_err_mean": float(np.mean(err)),
        "driver_zero_at_soc": float(soc[np.argmax(drv <= 0)]) if (drv <= 0).any() else None,
        "dt_table_err_max": float(np.max(np.abs(dt_err[keep]))),
        "by_state": {k: {"s": s[0], "mah": s[1]} for k, s in by_state.items()},
        "_series": (soc, v, i_a, drv, est_ocv, centres, ocv),
    }


def report(res, out, sources):
    soc, v, i_a, drv, est_ocv, centres, ocv = res.pop("_series")
    with open(os.path.join(out, "fit.json"), "w") as f:
        json.dump(res, f, indent=1)
    dts = ",\n\t\t\t".join(", ".join("<%d %d>" % p for p in res["ocv_table"][k:k + 4])
                            for k in range(0, len(res["ocv_table"]), 4))
    lines = [
        "# Battery fit, %s .. %s" % (res["from"], res["to"]), "",
        "Sources: %s" % ", ".join(os.path.basename(s) for s in sources), "",
        "| | |", "|---|---|",
        "| Capacity, full to the last reading | **%.0f mAh** |" % res["capacity_mah"],
        "| Time | %.1f h (%.1f h awake), %d readings, %d gaps |" % (
            res["hours"], res["awake_hours"], res["readings"], res["gaps"]),
        "| Mean current awake | %.0f mA |" % res["mean_ma"],
        "| End | %d mV at %d mA, driver %d %%%s |" % (
            res["end_mv"], res["end_ma"], res["end_driver_pct"],
            ", then the charger" if res["ended_on_charger"] else ""),
        "| R | %.0f mOhm, fit rms %.1f mV |" % (res["r_mohm"], res["fit_rms_mv"]),
        "| OCV table from | %s |" % res["method"],
        "| Driver's level vs true SoC | max %.1f %%, mean %+.1f %% |" % (
            res["driver_err_max"], res["driver_err_mean"]),
        "| Driver showed 0 %% at true SoC | %s |" % (
            "%.1f %%" % res["driver_zero_at_soc"] if res["driver_zero_at_soc"] is not None else "never"),
        "| DT table on the fitted R, worst | %.1f %% |" % res["dt_table_err_max"],
        "", "Drawn by:", "",
    ]
    for k, s in sorted(res["by_state"].items(), key=lambda kv: -kv[1]["mah"]):
        lines.append("- %s: %.0f min, %.0f mAh, %.0f mA" % (
            k, s["s"] / 60, s["mah"], s["mah"] / (s["s"] / 3600) if s["s"] else 0))
    lines += ["", "Device tree:", "", "```",
              "\t\tcharge-full-design-microamp-hours = <%d>;" % (round(res["capacity_mah"]) * 1000),
              "\t\tfactory-internal-resistance-micro-ohms = <%d>;" % (round(res["r_mohm"]) * 1000),
              "\t\tocv-capacity-table-0 =", "\t\t\t" + dts + ";", "```", ""]
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write("\n".join(lines))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(10, 8))
        ax[0].plot(soc, v, ",", alpha=.4, label="V loaded")
        ax[0].plot(soc, est_ocv, ",", alpha=.4, label="V - R*I")
        ax[0].plot(centres, ocv, "o-", ms=3, label="fitted OCV")
        ax[0].plot([p[1] for p in DT_OCV], [p[0] / 1e6 for p in DT_OCV], "--", label="DT table")
        ax[0].set_xlabel("true SoC, %")
        ax[0].set_ylabel("V")
        ax[0].invert_xaxis()
        ax[0].legend()
        ax[1].plot(soc, drv, label="driver's level")
        ax[1].plot(soc, soc, ":", label="true")
        ax[1].set_xlabel("true SoC, %")
        ax[1].set_ylabel("%")
        ax[1].invert_xaxis()
        ax[1].legend()
        fig.tight_layout()
        fig.savefig(os.path.join(out, "fit.png"), dpi=110)
    except ImportError:
        pass
    return "\n".join(lines)


def fetch(host, out):
    got = []
    for name in ("battery.raw.prev", "battery.raw"):
        dst = os.path.join(out, name)
        with open(dst, "wb") as f:
            ok = subprocess.run(SSH + ["root@" + host, "cat /data/" + name], stdout=f).returncode == 0
        if ok and os.path.getsize(dst):
            got.append(dst)
        else:
            os.unlink(dst)
    for name, cmd in (("dmesg.txt", "dmesg"), ("bare_app.log", "cat /var/log/bare_app.log")):
        with open(os.path.join(out, name), "wb") as f:
            subprocess.run(SSH + ["root@" + host, cmd], stdout=f)
    if not got:
        sys.exit("no raw readings on %s" % host)
    return got


def selftest():
    """A made-up battery: 4500 mAh, 0.2 Ohm, the DT curve 30 mV up."""
    rng = np.random.default_rng(1)
    cap, r_ohm = 4500.0, 0.2
    curve = lambda s: np.interp(s, [p[1] for p in DT_OCV][::-1],
                                [p[0] / 1e6 + .03 for p in DT_OCV][::-1])
    rows, t, q = [], 0, 0.0
    rows.append(dict(real_ms=1700000000000, boot_ms=1000, mono_ms=1000, mv=4180, ma=-700, cap=100,
                     ocv_mv=0, state=0, flags=F_ONLINE | F_FULL, game=""))
    while True:
        t += 5000
        ma = -float(rng.choice([900, 1450, 1600])) + rng.normal(0, 30)
        q += -ma * 5 / 3600
        s = 100 * (1 - q / cap)
        mv = (curve(s) + r_ohm * ma / 1000 + rng.normal(0, .004)) * 1000
        rows.append(dict(real_ms=1700000000000 + t, boot_ms=1000 + t, mono_ms=1000 + t, mv=int(mv),
                         ma=int(ma), cap=max(0, int(100 - q / 40)), ocv_mv=0, state=1, flags=0,
                         game="test"))
        if mv < 3300 or s < 0:
            break
    res = analyse(rows)
    res.pop("_series")
    ok_cap = abs(res["capacity_mah"] - q) < 5
    ok_r = abs(res["r_mohm"] - 200) < 10
    # the fit's 0 % is the cut-off: p % of the fit is this true SoC
    true_soc = lambda p: 100 * (cap - (1 - p / 100) * q) / cap
    worst = max(abs(uv / 1e6 - float(curve(true_soc(p)))) for uv, p in res["ocv_table"]
                if 5 <= p <= 95)
    print("capacity %.0f (true %.0f), R %.1f mOhm, OCV worst %.1f mV" % (
        res["capacity_mah"], q, res["r_mohm"], worst * 1000))
    sys.exit(0 if ok_cap and ok_r and worst < .015 else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--host")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--current-offset-ma", type=int, default=0,
                    help="add this to every current reading: the error of the gauge's zero "
                         "found afterwards (the driver's charge balance, rk818 0036)")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    if not a.host and not a.files:
        ap.error("--host or files")
    out = a.out or os.path.join(SDK, "lab", "wip", "battery-%s" % (a.host or "local"),
                                datetime.date.today().isoformat())
    os.makedirs(out, exist_ok=True)
    files = fetch(a.host, out) if a.host else a.files
    rows = load(files)
    for r in rows:
        r["ma"] += a.current_offset_ma
    print(report(analyse(rows), out, files))
    print("saved in", out)


if __name__ == "__main__":
    main()
