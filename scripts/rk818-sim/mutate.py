#!/usr/bin/env python3
"""Mutation check of the rk818 driver against the simulator's matrix: each
fix (and each threshold at the edges of its range) undone in turn in a copy
of the driver, run.sh over it, the cells that fail listed. A mutation no
cell catches is a fix the matrix does not protect.

  scripts/rk818-sim/mutate.py [NAME...]     all mutations by default
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(os.path.dirname(HERE))
DRV = os.path.join(SDK, "output/ogu/linux-src/drivers/power/supply/rk818_battery.c")

# (name, the text in the driver, what it becomes)
M = [
    ("poffset read unsigned", "\treturn (s8)val;\n}", "\treturn (int)val;\n}"),
    ("no charge balance", "\tif (!di->bal_open && !end)\n\t\treturn;", "\treturn;"),
    ("balance kept across a charge voltage change",
     "\telse if (di->bal_open && di->chg_volt_uv != di->bal_chg_volt_uv)", "\telse if (0)"),
    ("balance kept across a POFFSET change",
     "\tif (di->bal_open && di->poffset != di->bal_poffset)", "\tif (0)"),
    ("balance dropped on a COFFSET change",
     "\tif (di->bal_open && di->poffset != di->bal_poffset)",
     "\tif (di->bal_open && abs(rk818_get_coffset(di) - (di->bal_poffset + 0x80f)) > 1)"),
    ("an end right after a sleep", "\tbool end = di->charger_online && !di->chrg_status_old &&",
     "\tbool end = di->charger_online &&"),
    ("an end of a charge begun before the voltage change",
     "\t\t   !ktime_before(di->chg_since, di->volt_since) &&\n", ""),
    ("an end after any charge",
     "\t\t   di->chg_in_raw >= (s64)di->fcc_mah * BAL_CHARGE_MIN_PCT / 100 *",
     "\t\t   1 ||"),
    ("balance sign flipped", "\t\tif (rk818_save_poffset(di, poffset + step)) {",
     "\t\tstep = -step;\n\t\tif (rk818_save_poffset(di, poffset + step)) {"),
    ("zeroing even when balanced", "\t    state < 0 || state == CALIB_BALANCED ||", "\t    state < 0 ||"),
    ("zeroed state not kept", "\t\t\trk818_write(di, CALIB_STATE_REG, CALIB_ZEROED);\n", ""),
    ("accounting in mAh", "\ts32 now = rk818_get_gascnt(di);\n\n\tif (di->cc_tracking) {",
     "\ts32 now = rk818_get_coulomb_cap(di) * rk818_raw_per_mah(di);\n\n\tif (di->cc_tracking) {"),
    ("rise by the current's sign", "\tif (!di->charger_online && step > 0)", "\tif (di->current_avg_ma < 0 && step > 0)"),
    ("jump at the end of a charge", "\t\tdi->dsoc += clamp(limit - di->dsoc, -DSOC_DELTA_MAX,\n\t\t\t\t  DSOC_DELTA_MAX);",
     "\t\tdi->dsoc = limit;"),
    ("charge finish logged each time", "\t\tif (!di->full_latched)\n\t\t\tdev_info(di->dev, \"charge finish",
     "\t\tif (1)\n\t\t\tdev_info(di->dev, \"charge finish"),
    ("no adopt on restore", "\t\t    gen != di->boot_gen) {", "\t\t    0) {"),
    ("no sleep correction", "#define SLEEP_ZERO_MA\t\t\t210", "#define SLEEP_ZERO_MA\t\t\t0"),
    ("SLEEP_ZERO_MA 420", "#define SLEEP_ZERO_MA\t\t\t210", "#define SLEEP_ZERO_MA\t\t\t420"),
    ("balance kept over a sleep", "\t\trk818_balance_drop(di, \"a sleep\");\n", ""),
    ("no rest re-anchor", "\t\trk818_set_coulomb_cap(di, vol_to_cap(di, ocv_mv));\n\t}", "\t}"),
    ("rest without the sleep's current", "\t\tint i_ma = min(di->current_avg_ma - SLEEP_ZERO_MA, 0);", "\t\tint i_ma = 0;"),
    ("REST_SLEEP_MIN 240", "#define REST_SLEEP_MIN\t\t\t60", "#define REST_SLEEP_MIN\t\t\t240"),
    ("level after a sleep only off the charger", "\t/* the level comes down to the counter at once, never up */\n\tdi->dsoc = min(di->dsoc, di->rsoc);",
     "\tif (!rk818_charger_online(di))\n\t\tdi->dsoc = min(di->dsoc, di->rsoc);"),
    ("relax re-anchor while awake", "\tdi->remain_cap_mah = rk818_get_coulomb_cap(di);\n\tdi->rsoc = rk818_cap_to_soc(di, di->remain_cap_mah);\n\n\t/*\n\t * With the charger plugged in",
     "\t{ u8 st = rk818_read(di, RK818_GGSTS_REG); if ((st & RELAX_VOL12_UPD_MSK) == RELAX_VOL12_UPD_MSK) { rk818_set_coulomb_cap(di, vol_to_cap(di, rk818_read_vol(di, RK818_RELAX_VOL1_REGH))); rk818_restart_relax(di); } }\n\tdi->remain_cap_mah = rk818_get_coulomb_cap(di);\n\tdi->rsoc = rk818_cap_to_soc(di, di->remain_cap_mah);\n\n\t/*\n\t * With the charger plugged in"),
    ("OCV level after 30 min", "#define OCV_LEVEL_REST_MIN\t\t120", "#define OCV_LEVEL_REST_MIN\t\t30"),
    ("REST_SLEEP_MIN 40", "#define REST_SLEEP_MIN\t\t\t60", "#define REST_SLEEP_MIN\t\t\t40"),
    ("a charge seen not in the cycle", "\tif (counter_ok && charged) {\n\t\tdi->drawn_raw", "\tif (0) {\n\t\tdi->drawn_raw"),
    # what happened since the last run, read (rk818_init_soc())
    ("the SoC reset taken for a PMIC reset", "\treturn f != RK818_VBAT_LOW_3V0 && f != RK818_VBAT_LOW_3V4;", "\treturn true;"),
    ("a PMIC reset never seen", "\treturn f != RK818_VBAT_LOW_3V0 && f != RK818_VBAT_LOW_3V4;", "\treturn false;"),
    ("a reboot not saved", "(system_state == SYSTEM_RESTART ? BOOT_REBOOT :", "(0 ? BOOT_REBOOT :"),
    ("off on the charger not saved", "rk818_charger_online(di) ? BOOT_OFF_CHARGER : 0));", "0 ? BOOT_OFF_CHARGER : 0));"),
    ("a new sample after a reboot or off on USB", "(bs_ok ? !(bs & (BOOT_REBOOT | BOOT_OFF_CHARGER)) : !clean);", "(bs_ok ? 1 : !clean);"),
    ("no boot state: a new sample after a clean end", "(bs_ok ? !(bs & (BOOT_REBOOT | BOOT_OFF_CHARGER)) : !clean);", "(bs_ok ? !(bs & (BOOT_REBOOT | BOOT_OFF_CHARGER)) : 1);"),
    ("U-Boot's wait not a charge", 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & (BOOT_WAITED | BOOT_OFF_CHARGER))) || up_on_usb);', 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & BOOT_OFF_CHARGER)) || up_on_usb);'),
    ('off on the charger not a charge', 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & (BOOT_WAITED | BOOT_OFF_CHARGER))) || up_on_usb);', 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & BOOT_WAITED)) || up_on_usb);'),
    ('a power-up on USB not a charge', 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & (BOOT_WAITED | BOOT_OFF_CHARGER))) || up_on_usb);', 'explained = !marks_void &&\n\t\t    ((bs_ok && (bs & (BOOT_WAITED | BOOT_OFF_CHARGER))));'),
    ("any change of the counter a charge", "(abs(live - saved_cap) <= CHARGE_SEEN_MAH || explained);", "1;"),
    ('no sample before the charge', '\t\tbefore = explained && bs_ok && (bs & BOOT_FIRST_WAIT);', '\t\tbefore = 0;'),
    ('any sample on USB before the charge', '\t\tbefore = explained && bs_ok && (bs & BOOT_FIRST_WAIT);', '\t\tbefore = up_on_usb;'),
    ("a sample by the key not after the charge", "\t\tafter = !up_on_usb;", "\t\tafter = 0;"),
    ('learning over a counter not explained', '\tif (end_ok && !unexplained && bs_ok)', '\tif (end_ok && bs_ok)'),
    
    
    ('not explained: the voltage as the OCV', 'vol_to_cap(di, rk818_ocv_of(di, rk818_read_vol(di, RK818_BAT_VOL_REGH),\n\t\t\t\t\t min(rk818_read_cur(di, RK818_BAT_CUR_AVG_REGH), 0))))', 'vol_to_cap(di, rk818_read_vol(di, RK818_BAT_VOL_REGH)))'),
    ('the boot state kept after the boot', '\trk818_write(di, BOOT_STATE_REG, BOOT_MAGIC);\n\trk818_write(di, BOOT_GAS_REG,', '\trk818_write(di, BOOT_GAS_REG,'),
    ("no save at the end of the boot", "\t/* the state now saved: the next boot counts from here */\n\trk818_save_dsoc(di);\n\trk818_save_remain_cap(di);\n\trk818_save_learn(di, true);", ""),
    ("a sample on USB of unknown place: the counter", "\t} else if (counter_ok && new_ocv && up_on_usb && !before &&\n", "\t} else if (0 &&\n"),
    ("the saved charge not below 0", "clamp(di->remain_cap_mah, -rk818_fcc_max(di), rk818_fcc_max(di));", "clamp(di->remain_cap_mah, 0, rk818_fcc_max(di));"),
    ("the shutdown saves the last cycle's charge", "\t/* the charge now, not the last work cycle's (up to 5 s before) */\n\tdi->remain_cap_mah = rk818_get_coulomb_cap(di);\n", ""),
    ("the sleep fix at any suspend", "\tdi->sleep_s2idle      = state.event == PM_EVENT_SUSPEND &&\n\t\t\t\tpm_suspend_target_state == PM_SUSPEND_TO_IDLE;", "\tdi->sleep_s2idle      = true;"),
    ("3V4 not the driver's", "\treturn f != RK818_VBAT_LOW_3V0 && f != RK818_VBAT_LOW_3V4;", "\treturn f != RK818_VBAT_LOW_3V0;"),
    ("an adopted state without its boot", "\tdi->boot_gen = rk818_read(di, BOOT_GEN_REG);\n\tdev_info(di->dev,\n\t\t \"resume: another kernel ran", "\tdev_info(di->dev,\n\t\t \"resume: another kernel ran"),
    ("up on USB with no new sample", "\tup_on_usb = new_ocv && (rk818_read(di, RK818_ON_SOURCE_REG) & RK818_ON_PLUG_IN);", "\tup_on_usb = (rk818_read(di, RK818_ON_SOURCE_REG) & RK818_ON_PLUG_IN);"),
    ("U-Boot's marks without the counter check", "\t\tmarks_void = abs((s8)(u8)(now - at)) > BOOT_GAS_TOL;", "\t\tmarks_void = 0;"),
    ("BOOT_GAS_TOL 0", "#define BOOT_GAS_TOL\t\t\t1", "#define BOOT_GAS_TOL\t\t\t0"),
    ("BOOT_GAS_TOL 40", "#define BOOT_GAS_TOL\t\t\t1", "#define BOOT_GAS_TOL\t\t\t40"),
    ("0035's cycle kept", "\t\trk818_cycle_unknown(di, \"counted by an older driver\");\n", ""),
    ("0035's FCC kept", "\t\tif (di->fcc_mah > rk818_initial_fcc(di)) {", "\t\tif (0) {"),
    ("learning from 0035's counting", "\tif (end_ok && !unexplained && bs_ok)", "\tif (end_ok && !unexplained)"),
    ("not explained, no new OCV: the counter left out", "\t\tdi->remain_cap_mah = abs(live) <= rk818_fcc_max(di) ? min(live, est) : est;", "\t\tdi->remain_cap_mah = est;"),
    ("a new sample after a power-off on USB", "(bs_ok ? !(bs & (BOOT_REBOOT | BOOT_OFF_CHARGER)) : !clean);", "(bs_ok ? !(bs & BOOT_REBOOT) : !clean);"),
    ("U-Boot's counter mark kept at the boot", "\trk818_write(di, BOOT_GAS_REG, (u8)(((u32)rk818_get_gascnt(di) >> 16) + 128));", ""),
    ("no OCV bound after a power lost", "\t\tif (top < di->remain_cap_mah) {", "\t\tif (0) {"),
    ('the OCV bound without the charge', '\t\tint top = ocv_cap + chg;', '\t\tint top = ocv_cap;'),
    ("no bound after a power lost when U-Boot's marks do not stand", "\tif (!bottom && (flags & LEARN_RUNNING) && new_ocv) {", "\tif (!bottom && !unexplained && (flags & LEARN_RUNNING) && new_ocv) {"),
    ("no charge in the bound when U-Boot's marks do not stand", "\t\tint chg = unexplained ? max(live - saved_cap, 0) : charged;", "\t\tint chg = charged;"),
    ("no bound by the first wait's kept OCV", '\t\tif (bs_ok && (bs & BOOT_STASHED) && !before)', '\t\tif (0)'),
    ("0% learns without a rest", "\tbool zero = !(flags & LEARN_RUNNING) && (flags & LEARN_ZERO) && rested;", "\tbool zero = !(flags & LEARN_RUNNING) && (flags & LEARN_ZERO);"),
    ("0% learns only below 50%", "\tbool zero = !(flags & LEARN_RUNNING) && (flags & LEARN_ZERO) && rested;", "\tbool zero = !(flags & LEARN_RUNNING) && (flags & LEARN_ZERO) && rested && ocv_pct < 50;"),
    ("a cycle learnt from twice", "\tdi->learn_valid = false;\t/* the cycle is used */\n", ""),
    ("the counter left above the FCC", "\t/* Clamp coulomb counter to [0, fcc] */\n\tif (di->remain_cap_mah > di->fcc_mah) {", "\t/* Clamp coulomb counter to [0, fcc] */\n\tif (0) {"),
    ("FCC_MAX_PCT 400", "#define FCC_MAX_PCT\t\t\t150", "#define FCC_MAX_PCT\t\t\t400"),
    ("no charge added to a rest OCV of a plug-in", "\t\tdi->remain_cap_mah = ocv_cap + (before ? charged : 0);", "\t\tdi->remain_cap_mah = ocv_cap;"),
    ("the charge added to a rest OCV by the key", "\t\tdi->remain_cap_mah = ocv_cap + (before ? charged : 0);", "\t\tdi->remain_cap_mah = ocv_cap + charged;"),
    ("the end's OCV level without the charge after it", "\t\tdi->remain_cap_mah = vol_to_cap(di, end_mv) + (end_pre ? charged : 0);", "\t\tdi->remain_cap_mah = vol_to_cap(di, end_mv);"),
    ("no level from the cycle's end", "\tif (bottom) {\n\t\tdi->remain_cap_mah", "\tif (0) {\n\t\tdi->remain_cap_mah"),
    ('a power lost learns without a rest', '\t\tif (!rested) {\n\t\t\trk818_cycle_unknown(di, "off without a shutdown, not rested");', '\t\tif (0) {\n\t\t\trk818_cycle_unknown(di, "off without a shutdown, not rested");'),
    ("CHARGE_SEEN_MAH 0", "#define CHARGE_SEEN_MAH\t\t\t10", "#define CHARGE_SEEN_MAH\t\t\t0"),
    ("CHARGE_SEEN_MAH 200", "#define CHARGE_SEEN_MAH\t\t\t10", "#define CHARGE_SEEN_MAH\t\t\t200"),
    ("OCV_LEVEL_REST_MIN 600", "#define OCV_LEVEL_REST_MIN\t\t120", "#define OCV_LEVEL_REST_MIN\t\t600"),
    ("INITIAL_FCC_PCT 100", "#define INITIAL_FCC_PCT\t\t\t75", "#define INITIAL_FCC_PCT\t\t\t100"),
    ("INITIAL_FCC_PCT 50", "#define INITIAL_FCC_PCT\t\t\t75", "#define INITIAL_FCC_PCT\t\t\t50"),
    ("BAL_MIN_MIN 240", "#define BAL_MIN_MIN\t\t\t60", "#define BAL_MIN_MIN\t\t\t240"),
    ("BAL_MIN_MIN 10", "#define BAL_MIN_MIN\t\t\t60", "#define BAL_MIN_MIN\t\t\t10"),
    ("BAL_STEP_MAX 8", "#define BAL_STEP_MAX\t\t\t64", "#define BAL_STEP_MAX\t\t\t8"),
    ("BAL_STEP_MAX 127", "#define BAL_STEP_MAX\t\t\t64", "#define BAL_STEP_MAX\t\t\t127"),
    ("BAL_CHARGE_MIN_PCT 2", "#define BAL_CHARGE_MIN_PCT\t\t1", "#define BAL_CHARGE_MIN_PCT\t\t2"),
    ("BAL_STEP_MAX 72", "#define BAL_STEP_MAX\t\t\t64", "#define BAL_STEP_MAX\t\t\t72"),
    ("BAL_CHARGE_MIN_PCT 5", "#define BAL_CHARGE_MIN_PCT\t\t1", "#define BAL_CHARGE_MIN_PCT\t\t5"),
    ("BROWNOUT_PCT 5", "#define BROWNOUT_PCT\t\t\t10", "#define BROWNOUT_PCT\t\t\t5"),
    ("BROWNOUT_PCT 20", "#define BROWNOUT_PCT\t\t\t10", "#define BROWNOUT_PCT\t\t\t20"),
    ("FULL_KEEP_PCT 20", "#define FULL_KEEP_PCT\t\t5", "#define FULL_KEEP_PCT\t\t20"),
    ("RESERVE_PCT 0", "#define RESERVE_PCT\t\t\t3", "#define RESERVE_PCT\t\t\t0"),
    ("ZERO_UNCERT_PCT 0", "#define ZERO_UNCERT_PCT\t\t\t5", "#define ZERO_UNCERT_PCT\t\t\t0"),
    ("FCC_MAX_PCT 100", "#define FCC_MAX_PCT\t\t\t150", "#define FCC_MAX_PCT\t\t\t100"),
    ("FULL_KEEP_PCT 0", "#define FULL_KEEP_PCT\t\t5", "#define FULL_KEEP_PCT\t\t0"),
    ("LEARN_REST_MIN 5", "#define LEARN_REST_MIN\t\t\t30", "#define LEARN_REST_MIN\t\t\t5"),
    ("LEARN_REST_MIN 160", "#define LEARN_REST_MIN\t\t\t30", "#define LEARN_REST_MIN\t\t\t160"),
    ("DISCHARGE_POL_MV_PER_A 0", "#define DISCHARGE_POL_MV_PER_A\t\t36", "#define DISCHARGE_POL_MV_PER_A\t\t0"),
    ("DISCHARGE_POL_MV_PER_A 150", "#define DISCHARGE_POL_MV_PER_A\t\t36", "#define DISCHARGE_POL_MV_PER_A\t\t150"),
    ("SLEEP_ZERO_MA 150", "#define SLEEP_ZERO_MA\t\t\t210", "#define SLEEP_ZERO_MA\t\t\t150"),
    ("SLEEP_ZERO_MA 270", "#define SLEEP_ZERO_MA\t\t\t210", "#define SLEEP_ZERO_MA\t\t\t270"),
    ("RESERVE_PCT 15", "#define RESERVE_PCT\t\t\t3", "#define RESERVE_PCT\t\t\t15"),
    ("ZERO_UNCERT_PCT 15", "#define ZERO_UNCERT_PCT\t\t\t5", "#define ZERO_UNCERT_PCT\t\t\t15"),
]

# the model of U-Boot 0018 in the simulator: (name, text in rk818-sim.c, what it becomes)
MS = [
    ("U-Boot's first wait again in a later one", '\tif (!(bs & BIT(2))) {\n\t\tbs |= BIT(4);', '\tif (1) {\n\t\tbs |= BIT(4);'),
    ('U-Boot keeps OFF_CHARGER at its power-off', '\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(1) | BIT(4));', '\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(4));'),
    ('U-Boot keeps FIRST_WAIT at its power-off', '\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(1) | BIT(4));', '\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(1));'),
    ("U-Boot does not say it waited", "\tregs[RK818_MISC_MARK_REG] = bs | BIT(2);", "\tregs[RK818_MISC_MARK_REG] = bs;"),
    ("U-Boot marks nothing when the key leaves the wait", "\tif (uboot_waiting) { uboot_waiting = false; uboot_mark_leave(); }", "\tif (uboot_waiting) { uboot_waiting = false; }"),
    ("U-Boot marks nothing at its power-off", "\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(1) | BIT(4));\n\t\tuboot_mark_leave();", "\t\tregs[RK818_MISC_MARK_REG] = bs & ~(BIT(1) | BIT(4));"),
    ("U-Boot keeps a sample with no PMIC reset", "\t\tif (f != 2 && f != 6) {\t\t/* the PMIC reset: STASHED */", "\t\tif (1) {"),
    ("U-Boot keeps no sample", "\t\t\tbs |= BIT(3);\n", ""),
    ("U-Boot leaves no counter mark", "static void uboot_mark_leave(void) { if (!uboot_old)", "static void uboot_mark_leave(void) { if (0)"),
    ("U-Boot marks nothing", "\tif (uboot_old || (bs & 0xe0) != 0xc0) return;", "\treturn;"),
    ("the MFD sets VB_MON before the driver (no 0037)", "\tint e = rk818_battery_probe(&pdev);", "\tregs[RK818_VB_MON_REG] = (regs[RK818_VB_MON_REG] & PLUG_IN_STS) | 0x17;\n\tint e = rk818_battery_probe(&pdev);"),
]
SIM = os.path.join(HERE, "rk818-sim.c")


def main():
    srcs = {"DRIVER": open(DRV).read(), "SIM": open(SIM).read()}
    want = sys.argv[1:]
    missed = 0
    with tempfile.TemporaryDirectory(prefix="rk818-mut.") as tmp:
        for var, (name, a, b) in [("DRIVER", m) for m in M] + [("SIM", m) for m in MS]:
            if want and not any(w in name for w in want):
                continue
            src = srcs[var]
            if src.count(a) != 1:
                print("%-50s PATTERN x%d" % (name, src.count(a)), flush=True)
                missed += 1
                continue
            mut = os.path.join(tmp, "mut.c")
            open(mut, "w").write(src.replace(a, b))
            env = dict(os.environ, TMPDIR=tmp)
            env[var] = mut
            r = subprocess.run(["sh", "-c", "ulimit -v 2000000; sh %s/run.sh" % HERE],
                               capture_output=True, text=True, env=env)
            fails = [l.split()[1].rstrip(":") for l in r.stdout.splitlines() if l.startswith("FAIL ")]
            if fails:
                print("%-50s caught by %s" % (name, ", ".join(fails[:4]) + (" ..." if len(fails) > 4 else "")), flush=True)
            else:
                print("%-50s NOT CAUGHT %s" % (name, r.stderr.strip()[-200:]), flush=True)
                missed += 1
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
