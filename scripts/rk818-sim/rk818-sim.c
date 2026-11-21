/*
 * The RK818 gauge driver (kernel patches 0035, 0036) run on the PC: the
 * driver's own source with stub kernel headers (include/), called through
 * its entry points (probe, the monitor work, suspend/resume, shutdown, the
 * properties), over a model of the board:
 *
 *  - the PMIC: its registers in an array; the current ADC reads the true
 *    current plus (ZERO - COFFSET) codes, the coulomb counter integrates
 *    that reading; at a power-up from off it samples the OCV and counts the
 *    minutes off, the counter and COFFSET stay (ogu1, 2026-11-21); a reset
 *    (DEV_OFF_RST, reboot) sets BAT_CON and keeps the old OCV sample, a
 *    reset of the SoC alone (panic) changes nothing; a power-off with USB
 *    in leaves the PMIC on (U-Boot's wait, charging); the data registers
 *    survive all of it.
 *  - the cell: TRUE_CAP from the end of a charge to the brown-out, its
 *    rested OCV the device tree's table, 165 mOhm.
 *  - the charger: CC 2 A tapering to the end of the charge; after the end
 *    the battery may help the system (`helps`, 190 mA on a PC port) until
 *    it is topped up again at 2% less; a weak supply limits the charge.
 *  - bare_app: powers the device off at 0% for 10 s, off the charger.
 *
 *   rk818-sim [CELL...]     the scenario matrix (all cells by default);
 *                           VERBOSE=1 prints the driver's log
 * One line per cell, "PASS name" or "FAIL name: why"; exit 1 on a FAIL.
 */
#include "kstub.h"
#include <stdarg.h>
#include <math.h>
double now_ms; unsigned long jiffies;
void *sim_parent_drvdata;
enum system_states system_state;
#include DRIVER

/* ---------------------------------------------------------------- log */
static char logbuf[1 << 20]; static int loglen;
static int n_charge_finish, n_brownout_learn, n_not_brownout, n_balance;
void sim_log(char lvl, const char *fmt, ...)
{
	char line[512]; va_list ap;
	if (lvl == 'D' && !(getenv("VERBOSE") && atoi(getenv("VERBOSE")) >= 2)) return;
	va_start(ap, fmt); vsnprintf(line, sizeof(line), fmt, ap); va_end(ap);
	if (strstr(line, "charge finish")) n_charge_finish++;
	if (strstr(line, "to a brown-out") && strstr(line, "FCC") && !strstr(line, "out of range")) n_brownout_learn++;
	if (strstr(line, "not a brown-out")) n_not_brownout++;
	if (strstr(line, "charge balance:") && lvl != 'D') n_balance++;
	if (getenv("VERBOSE")) printf("[%8.1f] %c %s", now_ms / 1000.0, lvl, line);
	if (loglen < (int)sizeof(logbuf) - 600)
		loglen += snprintf(logbuf + loglen, sizeof(logbuf) - loglen, "[%8.1f] %c %s", now_ms / 1000.0, lvl, line);
}

/* ---------------------------------------------------------------- PMIC */
#define LSB_MA 3.012			/* 10 mOhm */
#define RAW_PER_MAH (CC_LSB_DENOM / 2)
static unsigned regs[256];
static double gas;			/* GASCNT, raw */
static int ioff = 0x80f;		/* IOFFSET, the PMIC's own part */
static int poff_true, zero_shift;	/* the board's part, true */
static int zero_code(void) { return ioff + poff_true + zero_shift; }	/* the ADC's code at no current */
static int cur_cache; static uint32_t gas_cache;
static double drift_ma;			/* an error of the counter (sleep) */
/* the cell */
static double cap_true = 3060, q;	/* mAh in it */
static double i_true;			/* mA, + into the battery */
/* the cell's polarisation beyond R: 30 mV per A, settling in 5 min */
/* the polarisation beyond R, two parts. Charging as the first unit's after
 * a 1.58 A charge (pol.txt, 2026-11-21: 25 mV in 5 min, 53 in 20, still
 * falling): 18 mV in 3 min and 73 mV in 30 min at 1.58 A. Discharging
 * less: 3741 -> 3770 mV in 35 min asleep after 1.67 A (slow 25 mV per A),
 * and the night fit's light-load points only some 11 mV under the rest */
static double eta1_mv, eta2_mv, eta_mv, relax_s;
/* the supply */
static int online, helps, supply_ma = 3000, load_ma = 360, chg;	/* chg: 0 none, 1 charging, 2 ended */
static int awake = 1;
static bool off;			/* the device is off */
static double end_jitter, end_off;	/* the end of a charge scatters (%) */
static unsigned rng = 12345;
static double rnd(void) { rng = rng * 1103515245 + 12345; return ((rng >> 8) & 0xffff) / 65535.0; }
static int ocv_bias;			/* the PMIC's OCV sample above the table */
static bool uboot_old;			/* a U-Boot without 0018 */
static bool timer_stops;		/* NON_ACT_TIMER_CNT stops at 255 (else wraps) */
static int term_delay = 20;		/* s from the end's level to TERMINATED */
static double term_at = -1;
static double off_left = -1;		/* true % left at bare_app's first power-off */

static const int truth_ocv[][2] = {
	{4082960,100},{4045980,95},{4009010,90},{3972010,85},{3934350,80},{3895710,75},{3862500,70},{3841170,65},
	{3818400,60},{3780330,55},{3739860,50},{3714430,45},{3700410,40},{3684780,35},{3664670,30},{3648220,25},
	{3640160,20},{3634280,15},{3624410,10},{3617000,5},{3610000,0}};
static struct power_supply_battery_ocv_table tab[ARRAY_SIZE(truth_ocv)];
static double soc_true(void) { return q / cap_true * 100; }
static int ocv_mv(double s)
{
	int n = ARRAY_SIZE(truth_ocv), k;
	if (s >= 100) return truth_ocv[0][0] / 1000 + (int)((s - 100) * 10);
	if (s <= 0) return 3610 + (int)(s * 10);
	for (k = 0; k < n - 1; k++)
		if (s >= truth_ocv[k + 1][1])
			return (int)((truth_ocv[k + 1][0] + (truth_ocv[k][0] - truth_ocv[k + 1][0]) * (s - truth_ocv[k + 1][1]) / 5) / 1000);
	return 3610;
}
static int v_bias;			/* the cell's voltage above the table */
static int v_mv(void) { return ocv_mv(soc_true()) + v_bias + (int)(165 * i_true / 1000 + eta_mv); }
static int coffset_now(void) { return regs[RK818_CAL_OFFSET_REGH] << 8 | regs[RK818_CAL_OFFSET_REGL]; }
static double zero_err_ma(void) { return (zero_code() - coffset_now()) * LSB_MA; }
/* BAT_CUR_AVG is an average: after a PMIC reset it still holds readings
 * with the zero of before for a moment (ogu1, 2026-11-21: -885 mA at the
 * probe after a reboot, on the charger) */
static int cur_glitch_reads, cur_glitch_ma;
/* in s2idle the gauge reads 210 mA above the true current (ogu1 with a
 * USB tester, 2026-11-21: 206 and 221 mA) */
static int sleep_err_ma = 215;
static int cur_code(void) { return (int)lround(i_true / LSB_MA) + zero_code() - coffset_now() + (int)lround(drift_ma / LSB_MA) + (awake ? 0 : (int)lround(sleep_err_ma / LSB_MA)); }

int regmap_read(struct regmap *m, unsigned reg, unsigned *val)
{
	switch (reg) {
	case RK818_GASCNT3_REG: gas_cache = (uint32_t)(int32_t)lround(gas); *val = gas_cache >> 24; return 0;
	case RK818_GASCNT2_REG: *val = (gas_cache >> 16) & 0xff; return 0;
	case RK818_GASCNT1_REG: *val = (gas_cache >> 8) & 0xff; return 0;
	case RK818_GASCNT0_REG: *val = gas_cache & 0xff; return 0;
	case RK818_BAT_CUR_AVG_REGH:
		cur_cache = (cur_code() + (cur_glitch_reads > 0 ? (int)lround(cur_glitch_ma / LSB_MA) : 0)) & 0xfff;
		if (cur_glitch_reads > 0) cur_glitch_reads--;
		*val = cur_cache >> 8; return 0;
	case RK818_BAT_CUR_AVG_REGL: *val = cur_cache & 0xff; return 0;
	case RK818_BAT_VOL_REGH: *val = v_mv() >> 8; return 0;
	case RK818_BAT_VOL_REGL: *val = v_mv() & 0xff; return 0;
	case RK818_IOFFSET_REGH: *val = ioff >> 8; return 0;
	case RK818_IOFFSET_REGL: *val = ioff & 0xff; return 0;
	}
	*val = regs[reg]; return 0;
}
static unsigned cal[4];
int regmap_write(struct regmap *m, unsigned reg, unsigned val)
{
	switch (reg) {
	case RK818_GASCNT_CAL_REG3: cal[3] = val; return 0;
	case RK818_GASCNT_CAL_REG2: cal[2] = val; return 0;
	case RK818_GASCNT_CAL_REG1: cal[1] = val; return 0;
	case RK818_GASCNT_CAL_REG0: gas = (int32_t)(cal[3] << 24 | cal[2] << 16 | cal[1] << 8 | (val & 0xff)); return 0;
	}
	if (reg == RK818_GGSTS_REG && !(val & RELAX_VOL12_UPD_MSK)) relax_s = 0;
	regs[reg] = val & 0xff; return 0;
}
int regmap_update_bits(struct regmap *m, unsigned reg, unsigned mask, unsigned val)
{ regs[reg] = (regs[reg] & ~mask) | (val & mask); return 0; }
int power_supply_batinfo_ocv2cap(struct power_supply_battery_info *info, int ocv, int temp)
{
	struct power_supply_battery_ocv_table *t = info->ocv_table[0]; int n = info->ocv_table_size[0], i, hi, lo;
	for (i = 0; i < n; i++) if (ocv > t[i].ocv) break;
	if (i == 0) hi = lo = 0; else if (i == n) hi = lo = n - 1; else hi = (lo = i) - 1;
	return fixp_linear_interpolate(t[lo].ocv, t[lo].capacity, t[hi].ocv, t[hi].capacity, ocv);
}
static struct power_supply_battery_info info;
static struct power_supply psys[64]; static int npsy;
struct power_supply *sim_psy_register(const struct power_supply_desc *de, const struct power_supply_config *c)
{
	struct power_supply *p = &psys[npsy++ % 64];
	p->battery_info = &info; p->drv_data = c->drv_data; return p;
}
static struct rk808 rk808; static struct regmap the_map;
suspend_state_t pm_suspend_target_state = PM_SUSPEND_TO_IDLE;	/* bare_app's s2idle */

static void pmic_sample_ocv(void) { int o = ocv_mv(soc_true()) + ocv_bias + (int)eta_mv; regs[RK818_BAT_OCV_REGH] = o >> 8; regs[RK818_BAT_OCV_REGL] = o & 0xff; }
/*
 * A power-up from off after `min` minutes, by the power key or on USB power:
 * a new OCV sample; ON_SOURCE says which (ogu1, 2026-11-21: 0x80 the key,
 * 0x40 USB). The counter and COFFSET stay (ogu1: across reboots, a power-off
 * with USB in, a power-off by U-Boot and a power-up by the key); only a
 * battery connected anew clears them (world()).
 */
/* any reset of the PMIC puts VB_MON's low-voltage field back to 3.2 V; the
 * driver keeps 3.0 V (3.4 V asleep); a reset of the SoC alone leaves it
 * (ogu1 dumps, 2026-11-21) */
static void vb_mon_reset(void) { regs[RK818_VB_MON_REG] = (regs[RK818_VB_MON_REG] & PLUG_IN_STS) | 0x14; }
static void pmic_power_up_by(int min, bool bat_con, bool usb)
{
	pmic_sample_ocv();
	regs[0xae] = usb ? 0x40 : 0x80;
	vb_mon_reset();
	/* minutes off, a byte: not measured whether it wraps or stops at
	 * 255 (timer_stops); two power-offs as long read the same either way */
	if (timer_stops && min > 255) min = 255;
	regs[RK818_NON_ACT_TIMER_CNT_REG] = min & 0xff;
	if (bat_con) regs[RK818_GGSTS_REG] |= BAT_CON;
}
static void pmic_power_up(int min, bool bat_con) { pmic_power_up_by(min, bat_con, false); }
/* DEV_OFF_RST before a reboot: no new OCV sample, the counter kept */
static void pmic_reset(void)
{
	vb_mon_reset();
	cur_glitch_reads = 3; cur_glitch_ma = -900;
	regs[RK818_GGSTS_REG] |= BAT_CON;
}

/* ---------------------------------------------------------------- kernel */
static struct platform_device pdev; static struct rk818_battery *di;
static int prop(enum power_supply_property p)
{ union power_supply_propval v = { 0 }; rk818_bat_get_property(di, p, &v); return v.intval; }
static int cap_pct(void) { return prop(POWER_SUPPLY_PROP_CAPACITY); }
static int fcc(void) { return prop(POWER_SUPPLY_PROP_CHARGE_FULL) / 1000; }
static bool uboot_waiting;	/* U-Boot is in its wait: the key leaves it (marks) */
static void uboot_mark_leave(void);
static void k_probe(void)
{
	if (uboot_waiting) { uboot_waiting = false; uboot_mark_leave(); }	/* the key in the wait */
	pdev.drvdata = NULL; npsy = 0;
	rk808.regmap = &the_map; sim_parent_drvdata = &rk808;
	regs[RK818_SUP_STS_REG] |= BAT_EXS;
	jiffies = (unsigned long)now_ms;	/* never 0, as in the kernel */
	int e = rk818_battery_probe(&pdev);
	if (e) { printf("probe failed: %d\n", e); exit(2); }
	di = platform_get_drvdata(&pdev);
	off = false; awake = 1;
	/* the probe sets the charger up again: a charge starts over (ogu2,
	 * 2026-11-21: 6 min of CV after a panic, full on the charger) */
	if (online) chg = 1;
}
static void k_set(enum power_supply_property p, int v)
{ union power_supply_propval pv = { .intval = v }; rk818_charger_set_property(di->charger_psy, p, &pv); }

/* ---------------------------------------------------------------- world */
static int rises, max_up, brownouts, brownout_hi, poweroffs, steps_full_min;
static double zero_since;
static bool bare_app = true;

static void physics(double dt)
{
	double s = soc_true(); int tgt = di ? rk818_limit_pct(di) : 100;
	int load = off ? 0 : (awake ? load_ma : 150);	/* s2idle: 0.54 W, ogu1 */
	int avail = supply_ma - load;
	bool chg_en = regs[RK818_CHRG_CTRL_REG1] & RK818_CHRG_CTRL_REG1_CHRG_EN;
	if (!online) { chg = 0; i_true = -load; }
	else if (!chg_en) { chg = 0; i_true = fmin(0, avail); }	/* inhibited: the supply runs the board */
	else {
		/* plugged in, and at the end's level: the PMIC charges a little
		 * (term_delay) before it reports the end */
		if (chg == 0) { chg = 1; term_at = -1; }
		if (chg == 2 && s < tgt - 2) { chg = 1; end_off = -end_jitter * rnd(); }
		else if (chg == 1 && s >= tgt + end_off - 0.5) {
			if (term_at < 0) term_at = now_ms + term_delay * 1000.0;
			if (now_ms >= term_at) { chg = 2; term_at = -1; }
		}
		if (chg == 1) i_true = fmin(s >= tgt ? 0 : s < tgt - 5 ? 2000 : 200 + 1800 * (tgt - s) / 5, avail);
		else i_true = -helps + fmin(0, avail);
	}
	q += i_true * dt / 3600;
	if (q > cap_true * 1.001) q = cap_true * 1.001;
	eta1_mv += (0.0114 * i_true - eta1_mv) * fmin(dt / 180, 1);
	eta2_mv += ((i_true > 0 ? 0.046 : 0.025) * i_true - eta2_mv) * fmin(dt / 1800, 1);
	eta_mv = eta1_mv + eta2_mv;
	/* the PMIC's relaxed voltage: taken a minute after the driver cleared
	 * it, at any current (ogu1: 3934 mV during a 1.58 A charge), held */
	relax_s += dt;
	if (relax_s >= 60 && !(regs[RK818_GGSTS_REG] & RELAX_VOL12_UPD_MSK)) {
		int v = v_mv();
		regs[RK818_RELAX_VOL1_REGH] = regs[RK818_RELAX_VOL2_REGH] = v >> 8;
		regs[RK818_RELAX_VOL1_REGH + 1] = regs[RK818_RELAX_VOL2_REGH + 1] = v & 0xff;
		regs[RK818_GGSTS_REG] |= RELAX_VOL12_UPD_MSK;
	}
	/* the PMIC off counts nothing (ogu1: 2922 -> 2922 mAh over 2 min off);
	 * off on USB power it is on, U-Boot waiting */
	if (!off || online)
		gas += (cur_code() * LSB_MA) * dt / 3600 * RAW_PER_MAH;
	regs[RK818_SUP_STS_REG] = BAT_EXS | (chg == 1 ? RK818_CHG_STS_CC_OR_CV : chg == 2 ? RK818_CHG_STS_TERMINATED : 0);
	regs[RK818_VB_MON_REG] = (regs[RK818_VB_MON_REG] & ~PLUG_IN_STS) | (online ? PLUG_IN_STS : 0);
	now_ms += dt * 1000; jiffies = (unsigned long)now_ms;
}
/* the device off for `min` minutes (charging if the charger is in) */
static void stay_off(int min)
{
	off = true;
	for (int k = 0; k < min * 12; k++) physics(5);
}
static void uboot_wait_enter(void);
static void uboot_wait(int secs);
static void uboot_charge_s(int before, int secs);
/* a power-off; with USB power in the PMIC does not go off (ogu1: no new OCV,
 * no time off) and the board is in U-Boot's wait at once */
static void k_power_off(void)
{
	system_state = SYSTEM_POWER_OFF; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
	/* on USB power: a reset of the PMIC (VB_MON back to 3.2 V), no new OCV
	 * sample, U-Boot's wait (ogu1, 2026-11-21) */
	if (online) { regs[0xae] = 0x40; vb_mon_reset(); uboot_wait_enter(); off = true; }
}
static void power_off(int min) { system_state = SYSTEM_POWER_OFF; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING; poweroffs++; stay_off(min); pmic_power_up(min, false); k_probe(); }
/* a brown-out; on USB power the PMIC comes up again at once on it: U-Boot's
 * wait, charging, then the key */
static void brown_out(int min)
{
	brownouts++;
	if (online) { pmic_power_up_by(0, false, true); uboot_wait_enter(); uboot_wait(min * 60); k_probe(); return; }
	stay_off(min); pmic_power_up(min, false); k_probe();
}
static void reboot(void) { system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING; pmic_reset(); physics(5); k_probe(); }
static void panic_reset(void) { physics(10); k_probe(); }
static void panic_reset_quiet(void) { physics(10); }	/* the SoC reset, Linux not up yet */

/* runs `sec` seconds awake; stops at a brown-out or bare_app's power-off (returns 1, 2) */
static int run(double sec)
{
	double end = now_ms + sec * 1000;
	while (now_ms < end) {
		int before = cap_pct();
		physics(5);
		if (!online && q <= 0.5) {
			if (cap_pct() > 5) brownout_hi++;
			return 1;
		}
		rk818_battery_work(&di->work.work);
		int after = cap_pct();
		if (after > before) { if (!online) rises++; if (after - before > max_up) max_up = after - before; }
		if (bare_app && !online && after == 0) {
			if (zero_since < 0) zero_since = now_ms;
			if (now_ms - zero_since >= 10000) {
				zero_since = -1;
				if (off_left < 0) off_left = soc_true();
				return 2;
			}
		} else zero_since = -1;
	}
	return 0;
}
/* a game: 10 min at 1.6 A, 10 min at 0.36 A, until a brown-out or 0% */
static int discharge(void)
{
	online = 0;
	for (;;) {
		load_ma = 1600; int r = run(600); if (r) return r;
		load_ma = 360; r = run(600); if (r) return r;
	}
}
static void charge_full(void) { online = 1; load_ma = 360; while (chg != 2) run(60); run(120); }
/* the end of a discharge: off at 0% or a brown-out, then off/rest `min` */
static void end_cycle(int r, int min) { if (r == 2) power_off(min); else brown_out(min); }

static void world(double cap, double soc0, int poff, int poff_reg, bool balanced, int fcc_reg, bool first)
{
	memset(regs, 0, sizeof(regs)); memset(di ? (void *)0 : (void *)0, 0, 0);
	now_ms += 3600e3; cap_true = cap; q = cap * soc0 / 100; ioff = 0x80f; poff_true = poff; zero_shift = 0;
	online = 0; helps = 0; supply_ma = 3000; load_ma = 360; chg = 0; drift_ma = 0; cur_glitch_reads = 0;
	end_jitter = end_off = 0; ocv_bias = 0; eta_mv = eta1_mv = eta2_mv = 0; relax_s = 0; sleep_err_ma = 215; uboot_old = false; timer_stops = false; uboot_waiting = false; term_delay = 20; term_at = -1; off_left = -1;
	rises = max_up = brownouts = brownout_hi = poweroffs = 0; zero_since = -1; bare_app = true;
	n_charge_finish = n_brownout_learn = n_not_brownout = n_balance = 0; loglen = 0;
	regs[RK818_VCALIB0_REGH] = 3000 >> 8; regs[RK818_VCALIB0_REGL] = 3000 & 0xff;
	regs[RK818_VCALIB1_REGH] = 4200 >> 8; regs[RK818_VCALIB1_REGL] = 4200 & 0xff;
	regs[RK818_POFFSET_REG] = poff_reg & 0xff;
	if (balanced) regs[RK818_UPDAT_LEVE_REG] = 0xb1;
	if (fcc_reg) { regs[RK818_NEW_FCC_REG1] = fcc_reg >> 8; regs[RK818_NEW_FCC_REG0] = fcc_reg & 0xff; }
	gas = first ? 0 : gas; regs[RK818_CAL_OFFSET_REGH] = 0x08; regs[RK818_CAL_OFFSET_REGL] = 0x32;
	if (!first) gas = q * RAW_PER_MAH;	/* a board that ran before: its counter at the charge */
	pmic_power_up(first ? 0 : 200, first);
	k_probe();
}
/* a calibrated board, FCC right */
static void good_world(double soc0) { world(3060, soc0, 30, 30, true, 3060, false); }

/* the end of a s2idle: the driver's resume reads the sleep's averages
 * (the current still SLEEP_ZERO high), then the board is awake */
static void wake(void) { rk818_battery_resume(&pdev); awake = 1; }

/* ---------------------------------------------------------------- cells */
static char why[512];
#define CHECK(c, ...) do { if (!(c)) { snprintf(why, sizeof(why), __VA_ARGS__); return false; } } while (0)
static bool near(double a, double b, double pct) { return fabs(a - b) <= b * pct / 100; }
static double true_level(void) { return (soc_true() - RESERVE_PCT) * 100.0 / (100 - RESERVE_PCT); }
#define CHECK_LEVEL(tol, what) CHECK(fabs(cap_pct() - true_level()) <= (tol), "%s: level %d, true %.0f", what, cap_pct(), true_level())
/* the level the battery's charge in mAh gives with the driver's FCC: for a
 * board whose FCC is still off, the charge is what must be right */
static double fcc_level(void) { double f = fcc(), r = f * RESERVE_PCT / 100.0; return fmin(100, fmax(0, (q - r) * 100 / (f - r))); }
#define CHECK_CHARGE(tol, what) CHECK(fabs(cap_pct() - fcc_level()) <= (tol), "%s: level %d, the charge gives %.0f (FCC %d)", what, cap_pct(), fcc_level(), fcc())

static bool A1_fresh_strong(void)
{
	world(3060, 50, 30, 0, false, 0, true);
	online = 1; helps = 0; run(4 * 3600);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off", zero_err_ma());
	return true;
}
static bool A2_fresh_weak(void)
{
	world(3060, 50, 30, 0, false, 0, true);
	online = 1; helps = 190; run(4 * 3600);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off", zero_err_ma());
	return true;
}
static bool A3_legacy_byte(void)
{
	world(3060, 60, 30, 0xdf, false, 3060, false);	/* -33 as a byte, ogu2 */
	CHECK(fabs(zero_err_ma()) <= 200, "at boot the zero %.0f mA off", zero_err_ma());
	run(600);
	CHECK(fabs(zero_err_ma()) <= 200, "after a periodic calibration %.0f mA off", zero_err_ma());
	online = 1; helps = 190; run(4 * 3600);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off after 4 h on the charger", zero_err_ma());
	return true;
}
static bool A4_limit_in_window(void)
{
	double worst = 0;
	good_world(90);
	online = 1; helps = 190;
	while (chg != 2) run(60);
	run(300);
	k_set(POWER_SUPPLY_PROP_CHARGE_CONTROL_END_THRESHOLD, 90);
	for (int k = 0; k < 6 * 60; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 15, "zero up to %.0f mA off after the limit changed", worst);
	return true;
}
/* the PMIC's IOFFSET moves (it measures it every 8 min): COFFSET follows */
static bool A5_ioffset_moves(void)
{
	world(3060, 50, 30, 0, false, 0, true);
	online = 1; helps = 190;
	for (int k = 0; k < 16; k++) { run(900); ioff += (k & 1) ? -2 : 2; }
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off with IOFFSET moving", zero_err_ma());
	return true;
}
/* a game on the charger after the first end: the zero is found again in
 * the middle of a balance, which then must not count */
static bool A6_zero_found_again(void)
{
	int bal0;
	world(3060, 50, 30, 0, false, 0, true);
	online = 1; helps = 190;
	while (chg != 2) run(60);
	run(600);			/* the first zero: hides the 190 mA */
	helps = 400;			/* the next end reads -210 mA */
	bal0 = n_balance;
	for (int k = 0; k < 5 * 60; k++) {
		double before = fabs(zero_err_ma()); int nb = n_balance;
		run(60);
		CHECK(n_balance == nb || fabs(zero_err_ma()) <= before + 3,
		      "a balance moved the zero away: %.0f -> %.0f mA off", before, fabs(zero_err_ma()));
	}
	CHECK(n_balance > bal0, "no charge balance");
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off", zero_err_ma());
	return true;
}
/* the zero found at the end of a charge is POFFSET 0: a real value */
/* the zero found again at an end inside a balance, the right one this
 * time (the battery stopped helping): the balance over both zeros must not
 * move it */
static bool A6b_zero_found_right_inside(void)
{
	world(3060, 50, 30, 0, false, 0, true);
	online = 1; helps = 190;
	while (chg != 2) run(60);	/* the first zero hides the 190 mA */
	run(60);
	helps = 0;
	double after2 = -1, moved = 0;
	for (int c = 0; c < 8; c++) {
		online = 0; load_ma = 1000; run(540);	/* 150 mAh out, then charged back */
		online = 1; load_ma = 360;
		for (;;) {
			double before = fabs(zero_err_ma()); int nb = n_balance;
			run(30);
			if (n_balance != nb) moved = fmax(moved, fabs(zero_err_ma()) - before);
			if (chg == 2) break;
		}
		run(30);
		if (after2 < 0 && c == 0) after2 = fabs(zero_err_ma());
	}
	CHECK(moved <= 3, "a balance moved the zero %.0f mA away", moved);
	CHECK(after2 <= 15, "the second zero %.0f mA off", after2);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off after balances over both zeros", zero_err_ma());
	return true;
}
/* this board's sleep zero 40 mA off the driver's: 8 h asleep on the charger
 * inside a balance window must not move the zero */
static bool A16_sleep_zero_differs(void)
{
	double worst = 0;
	good_world(80);
	online = 1; helps = 190; charge_full(); run(3 * 3600);
	sleep_err_ma = 250;
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 8 * 720; k++) physics(5);
	wake();
	for (int k = 0; k < 180; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 15, "zero up to %.0f mA off after a sleep, its zero 40 mA off", worst);
	return true;
}
static bool A7_zeroed_to_zero(void)
{
	world(3060, 50, 0, 0, false, 0, true);
	online = 1; helps = 0; run(3 * 3600);
	reboot(); run(60);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off after a reboot", zero_err_ma());
	return true;
}

static bool A9_sleep_on_charger(void)
{
	good_world(80);
	online = 1; helps = 190; charge_full(); run(3 * 3600);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 8 * 720; k++) physics(5);
	wake();
	double worst = 0;
	for (int k = 0; k < 180; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 15, "zero up to %.0f mA off after 8 h asleep on the charger", worst);
	return true;
}
/* asleep while charging: the charge ends in the sleep, top-ups follow */
static bool A10_charge_ends_asleep(void)
{
	for (int extra = 0; extra <= 28; extra += 7) {
		good_world(40);
		online = 1; helps = 190; run(600);
		rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
		for (int k = 0; k < 8 * 720 + extra * 12; k++) physics(5);
		wake();
		double worst = 0;
		for (int k = 0; k < 150; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
		CHECK(worst <= 15, "slept %d min more: zero up to %.0f mA off", extra, worst);
		end_cycle(discharge(), 150);
		CHECK(near(fcc(), 3060, 3), "slept %d min more: FCC %d after the cycle", extra, fcc());
	}
	return true;
}
/* nothing saved, the vendor default right: it stays right */
static bool A11_default_right(void)
{
	double worst = 0;
	world(3060, 50, 42, 0, false, 0, true);
	online = 1; helps = 3;
	for (int k = 0; k < 44 * 60; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 15, "zero up to %.0f mA off with POFFSET_DEFAULT right", worst);
	return true;
}
static bool A12_limit_lowered_charging(void)
{
	double worst = 0;
	good_world(80);
	online = 1; helps = 190;
	while (chg != 2) run(60);
	run(600);
	online = 0; load_ma = 1000; while (soc_true() > 60) run(60);
	online = 1; load_ma = 360; while (soc_true() < 95) run(60);
	k_set(POWER_SUPPLY_PROP_CHARGE_CONTROL_END_THRESHOLD, 90);
	for (int k = 0; k < 4 * 60; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 15, "zero up to %.0f mA off after the limit was lowered during a charge", worst);
	return true;
}
/* the ends of a charge scatter over 1% (30 mAh): up to 60 mA per balance */
static bool A13_ends_scatter(void)
{
	double sum = 0, worst = 0; int n = 0;
	world(3060, 50, 30, 0xdf, false, 3060, false);
	online = 1; helps = 190; end_jitter = 1.0;
	run(4 * 3600);
	for (int k = 0; k < 4 * 60; k++) { run(60); double e = fabs(zero_err_ma()); sum += e; n++; worst = fmax(worst, e); }
	CHECK(sum / n <= 15 && worst <= 30, "zero %.0f mA off on average, up to %.0f", sum / n, worst);
	return true;
}
/* the limit lowered off the charger, plugged in above it: the PMIC shows
 * a charge for a moment and then the end, with the battery above it */
static bool A14_plugged_above_limit(void)
{
	static const int delays[] = { 20, 90, 300 };
	for (int d = 0; d < 3; d++) {
		double worst = 0;
		good_world(80);
		term_delay = delays[d];
		online = 1; helps = 190; charge_full(); run(3600);
		online = 0; load_ma = 360; run(600);
		k_set(POWER_SUPPLY_PROP_CHARGE_CONTROL_END_THRESHOLD, 90);
		online = 1;
		for (int k = 0; k < 4 * 60; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
		CHECK(worst <= 15, "end %d s late: zero up to %.0f mA off after a plug-in above the limit", delays[d], worst);
	}
	return true;
}
/* one end 12% early (something the balance cannot see): one window's harm */
static bool A15_one_odd_end(void)
{
	double worst = 0;
	good_world(80);
	online = 1; helps = 190; charge_full(); run(2 * 3600);
	online = 0; load_ma = 1000; while (soc_true() > 60) run(60);
	end_off = -12; online = 1; load_ma = 360;
	for (int k = 0; k < 5 * 60; k++) { run(60); worst = fmax(worst, fabs(zero_err_ma())); }
	CHECK(worst <= 200, "one odd end moved the zero %.0f mA", worst);
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off at the end", zero_err_ma());
	return true;
}
/* full on a PC port: the battery helps the system and is topped up every
 * 20-30 min; the level stays 100 for 3 h */
static bool A17_full_stays_full(void)
{
	good_world(50);
	online = 1; helps = 190; charge_full();
	run(600);
	int low = 100;
	for (int k = 0; k < 180; k++) { run(60); if (cap_pct() < low) low = cap_pct(); }
	CHECK(low == 100, "full on the charger: the level went down to %d", low);
	return true;
}
/* full on a PC port, a top-up begun, and a game a little over the charger
 * for 10 min (1% lost): still full */
static bool A18_full_top_up_with_a_game(void)
{
	good_world(50);
	online = 1; helps = 190; charge_full();
	while (chg == 2) run(60);
	supply_ma = 700; load_ma = 900; run(600);
	CHECK(cap_pct() == 100, "a top-up with a game a little over the charger: level %d", cap_pct());
	return true;
}
/* a reboot under a game: the drawn charge goes on across it, counted once
 * (the shutdown saves the counter of now, not of the last work cycle) */
static bool A19_drawn_across_a_reboot(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 2300;
	run(600);
	double q0 = q; int d0 = di->drawn_mah;	/* at the last work cycle */
	physics(4);			/* 4 s after it */
	reboot();
	CHECK(abs(di->drawn_mah - d0 - (int)lround(q0 - q)) <= 1, "drawn %d -> %d across a reboot (the battery gave %.1f mAh)", d0, di->drawn_mah, q0 - q);
	return true;
}
static bool B1_panic_midway(void)
{
	good_world(0.1);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	int c0 = cap_pct(), f0 = fcc();
	panic_reset();
	run(10);
	CHECK(abs(cap_pct() - c0) <= 2, "level %d -> %d after a panic", c0, cap_pct());
	CHECK(fcc() == f0, "FCC %d -> %d after a panic", f0, fcc());
	end_cycle(discharge(), 150);
	CHECK(near(fcc(), 3060, 3), "FCC %d after the cycle (true 3060)", fcc());
	return true;
}
static bool B2_panic_full_on_charger(void)
{
	good_world(0.1);
	online = 1; helps = 190; charge_full(); run(3600);
	panic_reset();
	int lo = 100;
	for (int k = 0; k < 60; k++) { run(10); if (cap_pct() < lo) lo = cap_pct(); }
	CHECK(lo >= 99, "the level fell to %d after a panic full on the charger", lo);
	return true;
}
static bool B3_reboot_midway(void)
{
	good_world(80);
	online = 0; load_ma = 1000; run(1800);
	int c0 = cap_pct(); reboot(); run(10);
	CHECK(abs(cap_pct() - c0) <= 2, "level %d -> %d after a reboot", c0, cap_pct());
	return true;
}
static bool B4_brownout_teaches(void)
{
	world(3060, 30, 30, 30, true, 4000, false);
	charge_full();
	int r = discharge();
	CHECK(r == 1, "no brown-out with the FCC too large");
	brown_out(150);
	CHECK(near(fcc(), 3060, 3), "FCC %d after a brown-out (true 3060)", fcc());
	return true;
}
static bool B5_forced_off_15(void)
{
	static const int mins[] = { 2, 10, 2 };
	for (int m = 0; m < 3; m++) {
		good_world(30);
		charge_full(); online = 0; load_ma = 1000;
		while (soc_true() > 15) run(60);
		int f0 = fcc();
		if (m == 2) { uboot_charge_s(mins[m], 600); k_probe(); }	/* the charger in */
		else brown_out(mins[m]);	/* the power key held: off, no shutdown */
		CHECK(fcc() == f0, "FCC %d -> %d after a forced power-off at 15%% and %d min off%s", f0, fcc(), mins[m], m == 2 ? ", the charger in" : "");
	}
	return true;
}
/* the OCV at rest after a brown-out a little above the table's 0% */
static bool B8_brownout_rest_higher(void)
{
	world(3060, 30, 30, 30, true, 4000, false);
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC too large");
	ocv_bias = 12;
	brown_out(300);
	CHECK(near(fcc(), 3060, 3), "FCC %d after a brown-out, OCV 12 mV above the table", fcc());
	return true;
}
/* two brown-outs in a row, the same OCV at rest after each: a new sample */
static bool B9_two_brownouts(void)
{
	world(3060, 30, 30, 30, true, 4000, false);
	charge_full(); CHECK(discharge() == 1, "no first brown-out"); brown_out(150);
	k_set(POWER_SUPPLY_PROP_CHARGE_FULL, 4000000);
	charge_full(); CHECK(discharge() == 1, "no second brown-out"); brown_out(150);
	CHECK(near(fcc(), 3060, 3), "FCC %d after the second brown-out (true 3060)", fcc());
	return true;
}
/* charged in U-Boot's wait, started by the power key: the OCV of the
 * plug-in is from before the charge */
static void uboot_charge(int before, int min);
static void uboot_charge_s(int before, int secs);
static void uboot_mark_leave(void);
static void uboot_wait(int secs);
static void uboot_charge_s(int before, int secs);
static void uboot_unplugged(void);
static void key_power_up(int min);
static void usb_up_key_at_once(int before);
static bool B10_uboot_charge_then_key(void)
{
	good_world(60);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge(150, 70);
	double t0 = true_level();
	k_probe(); run(10);
	CHECK(cap_pct() >= t0 - 20 && cap_pct() <= t0 + 3, "level %d at the start, true %.0f", cap_pct(), t0);
	online = 0; load_ma = 360; off_left = -1;
	int r = discharge();
	CHECK(r == 2 && off_left <= 15, "off at 0%% with %.0f%% left (r %d)", off_left, r);
	return true;
}
/* on the charger at once after a game (2 min off): the battery polarised,
 * no charge since the sample */
static bool B11_power_on_charging_after_game(void)
{
	good_world(80);
	charge_full();
	online = 0; load_ma = 1600; run(1800);
	k_power_off(); stay_off(2);
	online = 1; pmic_power_up_by(2, false, true);
	double t = true_level();
	physics(5); physics(5);
	k_probe(); run(10);
	CHECK(fabs(cap_pct() - t) <= 5, "level %d on the charger after a game (true %.0f)", cap_pct(), t);
	CHECK(di->learn_valid, "the learning cycle dropped at a power-on on the charger");
	return true;
}
/* the power key held at 15%, off for an hour: rested, still not a brown-out */
static bool B12_forced_off_15_rested(void)
{
	good_world(30);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 15) run(60);
	int f0 = fcc();
	brown_out(60);
	CHECK(fcc() == f0, "FCC %d -> %d after a forced power-off at 15%% and an hour off", f0, fcc());
	return true;
}
/* a short charge in U-Boot's wait, the power key: 5 to 20 min, below what
 * the voltage alone shows */
static bool B13_uboot_short_charge_key(void)
{
	for (int m = 5; m <= 20; m += 5) {
		good_world(60);
		charge_full();
		CHECK(discharge() == 2, "no 0%% power-off");
		k_power_off();
		double t0 = true_level();	/* before U-Boot's charge */
		uboot_charge(150, m);
		double t = true_level();
		k_probe(); run(10);
		/* the counter counted the charge in the wait */
		CHECK(cap_pct() >= t0 - 3 && cap_pct() <= t + 3, "%d min in U-Boot: level %d at the start, true %.0f (%.0f before it)", m, cap_pct(), t, t0);
	}
	return true;
}
/* 22 to 34 min in U-Boot's wait: no brown-out before 0% after it */
static bool B14_uboot_charge_then_play(void)
{
	for (int m = 22; m <= 34; m += 4) {
		good_world(60);
		charge_full();
		CHECK(discharge() == 2, "no 0%% power-off");
		k_power_off();
		uboot_charge(150, m);
		k_probe(); run(10);
		online = 0;
		CHECK(discharge() == 2, "%d min in U-Boot: a brown-out before 0%% (level %d)", m, cap_pct());
	}
	return true;
}
/* an older U-Boot: 70 min in its wait, the power key: the voltage shows it */
static bool B15_old_uboot_charge_key_level(void)
{
	for (int m = 40; m <= 70; m += 30) {
		good_world(60);
		uboot_old = true;
		charge_full();
		CHECK(discharge() == 2, "no 0%% power-off");
		k_power_off();
		uboot_charge(150, m);
		double t = true_level();
		k_probe(); run(10);
		CHECK(cap_pct() >= t - 20 && cap_pct() <= t + 3, "older U-Boot, %d min: level %d at the start, true %.0f", m, cap_pct(), t);
	}
	return true;
}
/* a reboot on the charger midway through a cycle, the current read just
 * after it still the one of before: no "charged since the sample" */
static bool B16_reboot_on_charger_stale_current(void)
{
	world(3060, 90, 30, 30, true, 2700, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	online = 1; run(600);
	int c0 = cap_pct();
	reboot(); run(60);
	CHECK(di->learn_valid, "the learning cycle dropped at a reboot on the charger");
	CHECK(abs(cap_pct() - c0) <= 3, "level %d -> %d at a reboot on the charger", c0, cap_pct());
	end_cycle(discharge(), 150);
	CHECK(fcc() > 2720, "FCC %d: the cycle with a reboot on the charger taught nothing (was 2700)", fcc());
	return true;
}
/* off at 25, 40, 60%, plugged in after 30 min, the power key 5, 60, 180 s
 * into U-Boot's wait: never above the battery's, low at most by what 30 min
 * after a load leaves in the voltage (some 9 mV: 6-8% in the flat 20-30%),
 * and 0% with at most 15% left */
static bool B17_uboot_wait_short(void)
{
	static const int start[] = { 25, 40, 60 }, wait[] = { 5, 60, 180 };
	for (int a = 0; a < 3; a++)
		for (int w = 0; w < 3; w++) {
			good_world(100);
			online = 0; load_ma = 1000;
			while (soc_true() > start[a]) run(60);
			k_power_off();
			uboot_charge_s(30, wait[w]);
			double t = true_level();
			k_probe(); run(10);
			CHECK(cap_pct() >= t - 10 && cap_pct() <= t + 3, "off at %d%%, %d s in U-Boot: level %d, true %.0f", start[a], wait[w], cap_pct(), t);
			online = 0; off_left = -1;
			int r = discharge();
			CHECK(r == 2 && off_left <= 15, "off at %d%%, %d s in U-Boot: 0%% with %.0f%% left (r %d)", start[a], wait[w], off_left, r);
		}
	return true;
}
/* a game, the power-off, the charger in 2 min later and the power key after
 * a few minutes in U-Boot's wait: the voltage estimate under the charge is
 * low (its polarisation not grown yet): not below the level before it */
static bool B18_game_then_short_uboot_charge(void)
{
	for (int m = 4; m <= 16; m += 4) {
		good_world(90);
		online = 0; load_ma = 1600;
		while (soc_true() > 50) run(60);
		k_power_off();
		double t0 = true_level();
		uboot_charge(2, m);
		double t = true_level();
		k_probe(); run(10);
		CHECK(cap_pct() >= t0 - 3 && cap_pct() <= t + 3, "a game, %d min in U-Boot: level %d, true %.0f (%.0f before it)", m, cap_pct(), t, t0);
	}
	return true;
}
/* the FCC 18% too large, a clean power-off at half, 3 h off: the OCV after
 * the rest puts the level right (the counter's would be the FCC's) */
static bool B20_long_rest_wrong_fcc(void)
{
	world(3060, 50, 30, 30, true, 3600, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	power_off(180); run(10);
	CHECK_LEVEL(6, "3 h off at half with the FCC 3600 for 3060");
	return true;
}
/* a power-off on the charger at 40%, 30 min in U-Boot's wait, the charger
 * pulled, the key the next morning (121 min): the charge counted once */
static bool B21_off_on_charger_key_next_morning(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 40) run(60);
	online = 1; run(60);
	k_power_off(); uboot_wait(1800);
	uboot_unplugged(); key_power_up(121); run(10);
	CHECK_LEVEL(5, "a power-off on the charger, 30 min in the wait, unplugged, the key 121 min later");
	return true;
}
/* a game down to 25%, a clean power-off, the key 40 min later: the voltage
 * not back after the load yet (some 9 mV, 6-8% in the flat): the counter */
static bool B22_game_off_40_min(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1600;
	while (soc_true() > 25) run(60);
	power_off(40); run(10);
	CHECK_LEVEL(4, "a game, a power-off, the key 40 min later");
	return true;
}
/* off at 40%, the charger in 30 min later for 30 min, pulled, in again
 * 150 min later for 20 min, the key from the wait: this OCV sample is
 * between the charges, neither before nor after them */
static bool B23_two_plug_ins_long_gap(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 40) run(60);
	k_power_off();
	uboot_charge_s(30, 1800); uboot_unplugged();
	uboot_charge_s(150, 1200);
	k_probe(); run(10);
	CHECK_LEVEL(5, "two plug-ins 150 min apart, the key from the wait");
	return true;
}
/* off at 40%, the charger in 150 min later for 30 min, the key from the
 * wait: the OCV rested and before the charge, the charge on top */
static bool B24_plug_in_after_long_rest(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 40) run(60);
	k_power_off();
	uboot_charge_s(150, 1800);
	k_probe(); run(10);
	CHECK_LEVEL(5, "the charger in after 150 min off, the key from the wait");
	return true;
}
/* another system's gauge set the counter (an SD card with another OS) to
 * its own 20% while the battery holds 60%: the counter far under the saved
 * charge is not the charge */
static bool B25_counter_set_by_another_system(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 60) run(60);
	k_power_off(); stay_off(60);
	gas = 600.0 * rk818_raw_per_mah(di);
	pmic_power_up(60, false); k_probe(); run(10);
	/* not the charge: a level not above the battery's, the cycle dropped */
	CHECK(cap_pct() <= true_level() + 3, "the counter set to 20%% by another system: level %d, true %.0f", cap_pct(), true_level());
	CHECK(!di->learn_valid, "the learning cycle kept over a counter set by another system");
	return true;
}
/* a power-off on the charger at 40%, 30 min in the wait, unplugged, 150 min
 * off, plugged in again and the key at once / after 10 min in the wait,
 * this U-Boot and an older one: that sample is after the first charge */
static bool B26_off_on_charger_replugged(void)
{
	for (int v = 0; v < 4; v++) {
		good_world(60);
		uboot_old = v & 2;
		charge_full(); online = 0; load_ma = 1000;
		while (soc_true() > 40) run(60);
		online = 1; run(60);
		k_power_off(); uboot_wait(1800);
		uboot_unplugged();
		if (v & 1) { uboot_charge_s(150, 600); k_probe(); }
		else usb_up_key_at_once(150);
		run(10);
		CHECK_LEVEL(5, v & 1 ? "off on the charger, replugged 150 min later, 10 min in the wait" :
			    "off on the charger, replugged 150 min later, the key at once");
	}
	return true;
}
/* after a power-off at full and 150 min off (NON_ACT 150), a game to half,
 * the charger in, a power-off, the key 5 s into the wait: the PMIC stayed
 * on, the sample is the old one (U-Boot keeps none of it) */
static bool B27_off_on_charger_key_at_once_after_rest(void)
{
	good_world(60);
	charge_full(); online = 0;
	power_off(150);
	load_ma = 1600;
	while (soc_true() > 50) run(60);
	online = 1; run(30);
	k_power_off(); uboot_wait(5);
	k_probe(); run(10);
	CHECK_LEVEL(4, "a power-off on the charger at half, the key at once");
	return true;
}
/* another system's gauge set the counter to its 95% for 60%: not a charge */
static bool B28_counter_set_high_by_another_system(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 60) run(60);
	k_power_off(); stay_off(60);
	gas = 2900.0 * rk818_raw_per_mah(di);
	pmic_power_up(60, false); k_probe(); run(10);
	CHECK_LEVEL(8, "the counter set to 95% by another system");
	CHECK(!di->learn_valid, "the learning cycle kept over a counter off the OCV");
	return true;
}
/* a brown-out, the charger in for 30 min, out, in again, the key from the
 * wait (U-Boot kept the first plug-in's OCV), and a panic at once, before
 * the driver saved: the kept OCV is taken once */
static bool B29_panic_right_after_kept_ocv(void)
{
	world(3060, 30, 30, 30, true, 3600, false);
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC 3600");
	brownouts++;
	uboot_charge_s(5, 300); uboot_unplugged();
	uboot_charge_s(10, 1200);
	k_probe();
	int f1 = fcc(), c1 = cap_pct();
	panic_reset(); run(10);
	CHECK(fcc() == f1, "FCC %d -> %d at a panic after a boot with U-Boot's OCV", f1, fcc());
	CHECK(abs(cap_pct() - c1) <= 2, "level %d -> %d at a panic after a boot with U-Boot's OCV", c1, cap_pct());
	return true;
}
/* a game down to 30% (25%), a power-off on the charger, 3 min in the wait,
 * unplugged, the key 35 (2) min later: the OCV still low after the game,
 * the charge counted: the counter stays */
static bool B30_game_off_on_charger_short_charge(void)
{
	static const int keys[] = { 35, 2 }, lvl[] = { 30, 25 };
	for (int k = 0; k < 2; k++) {
		good_world(60);
		charge_full(); online = 0; load_ma = 1600;
		while (soc_true() > lvl[k]) run(60);
		online = 1; run(10);
		k_power_off(); uboot_wait(180);
		uboot_unplugged(); key_power_up(keys[k]); run(10);
		CHECK_LEVEL(4, k ? "a game, off on the charger 3 min, the key 2 min later" :
			    "a game, off on the charger 3 min, the key 35 min later");
		CHECK(di->learn_valid, "the learning cycle dropped after a game and a short charge");
	}
	return true;
}
/* a reboot into another system (an SD card), whose gauge set the counter
 * to 10% (95%), and back by a reboot: no new OCV, the one there from a
 * power-up at 95%; not above the battery's 30% (below it may be: the
 * user's rule, safe), the cycle dropped */
static bool B31_reboot_back_from_another_system(void)
{
	static const double set[] = { 300, 2900 };	/* its 10%, its 95% */
	for (int k = 0; k < 2; k++) {
		good_world(95);
		online = 0; load_ma = 1000;
		while (soc_true() > 30) run(60);
		system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
		pmic_reset(); gas = set[k] * rk818_raw_per_mah(di); physics(5);
		pmic_reset(); physics(5); k_probe(); run(10);
		CHECK(cap_pct() <= true_level() + 3,
		      "back from another system by a reboot, its counter at %.0f mAh: level %d, true %.0f", set[k], cap_pct(), true_level());
		/* its counter high: the saved charge and the voltage less the
		 * load's drop tell, not the loaded voltage (a third lower) */
		if (k) CHECK(cap_pct() >= true_level() - 10, "back from another system, its counter high: level %d, true %.0f", cap_pct(), true_level());
		CHECK(!di->learn_valid, "the learning cycle kept over a counter set by another system");
	}
	return true;
}
/* a brown-out, the charger in (the key at once, or 5 min in U-Boot's wait),
 * a full charge, down to 12-22% on the battery, a panic: a reset of the SoC
 * alone, no brown-out (review round 3: read as one, FCC -15%, level 0) */
static bool B33_panic_low_after_brownout_boot(void)
{
	static const int at[] = { 12, 15, 18, 22 };
	for (int w = 0; w < 2; w++)
		for (int k = 0; k < 4; k++) {
			world(3060, 30, 30, 30, true, 3060, false);
			charge_full(); bare_app = false;
			CHECK(discharge() == 1, "no brown-out");
			bare_app = true;
			if (w) { uboot_charge(150, 5); k_probe(); }
			else usb_up_key_at_once(150);
			charge_full(); online = 0; load_ma = 360;
			while (soc_true() > at[k]) run(60);
			int c0 = cap_pct(), f0 = fcc();
			panic_reset(); run(10);
			CHECK(abs(cap_pct() - c0) <= 2 && fcc() == f0, "a panic at %d%% after a boot from a brown-out%s: level %d -> %d, FCC %d -> %d",
			      at[k], w ? " and U-Boot's wait" : "", c0, cap_pct(), f0, fcc());
		}
	return true;
}
/* a FCC far above any cell's in the register (another system's driver, a
 * corrupt write: 9000 mAh for a 4000 mAh design): not taken */
static bool B34_fcc_register_far_off(void)
{
	world(3060, 50, 30, 30, true, 9000, false);
	CHECK(fcc() <= 4000, "FCC %d taken from a register holding 9000", fcc());
	return true;
}
/* the last power-up's OCV at 5%; at 50% on the battery the charger in and
 * a panic before the driver saw it: U-Boot waits on USB power 10 min (the
 * PMIC not reset: no new sample, none kept), the key */
static bool B35_panic_with_the_charger_in(void)
{
	for (int v = 0; v < 3; v++) {
		int asleep = v == 1;
		good_world(5);
		charge_full(); online = 0; load_ma = 1000;
		while (soc_true() > 50) run(60);
		int f0 = fcc();
		if (asleep) { rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0; }
		online = 1; physics(5);
		panic_reset_quiet();
		regs[0xae] = 0x40; uboot_wait_enter(); uboot_wait(600);
		if (v == 2) { uboot_unplugged(); key_power_up(20); }	/* out, the key later */
		else k_probe();
		run(10);
		CHECK(fcc() == f0, "FCC %d -> %d after a panic%s into U-Boot's wait", f0, fcc(), asleep ? " asleep" : "");
		CHECK_LEVEL(5, asleep ? "a panic asleep into U-Boot's wait" : "a panic into U-Boot's wait");
	}
	return true;
}
/* the FCC 18% too large; a power-off on the charger at 30%, 10 min in the
 * wait, unplugged (U-Boot powers the PMIC off), the key 3 h later: a new
 * OCV after a rest puts the level right */
static bool B36_off_on_charger_unplugged_long_rest_wrong_fcc(void)
{
	world(3060, 50, 30, 30, true, 3600, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 30) run(60);
	online = 1; run(30);
	k_power_off(); uboot_wait(600);
	uboot_unplugged(); key_power_up(180); run(10);
	CHECK_LEVEL(6, "off on the charger at 30%, unplugged, the key 3 h later, the FCC 3600 for 3060");
	return true;
}
/* another system booted through U-Boot's wait (WAITED, FIRST_WAIT
 * left), sets the counter high, powers off on the battery; ours by the key */
static bool B37_other_system_after_wait_high(void)
{
	for (int v = 0; v < 2; v++) {
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	if (v) { online = 1; run(60); k_power_off(); uboot_wait(60); }	/* off on USB, wait, key */
	else { k_power_off(); uboot_charge_s(30, 60); }		/* off on battery, USB in, wait, key */
	uboot_mark_leave(); uboot_waiting = false;	/* the key: U-Boot leaves, starts it */
	/* the other system runs: counter to 95%, then off on the battery */
	gas = 2900.0 * rk818_raw_per_mah(di);
	online = 0; off = false; for (int k = 0; k < 12 * 10; k++) physics(5);
	stay_off(10); pmic_power_up(10, false); k_probe(); run(10);
	CHECK(cap_pct() <= true_level() + 3, "v%d other system after U-Boot's wait set the counter high: level %d, true %.0f", v, cap_pct(), true_level());
	}
	return true;
}

/* older U-Boot, FCC too large, brown-out, two plug-ins, the key */
static bool D23_old_uboot_brownout_two_plug_ins(void)
{
	world(3060, 30, 30, 30, true, 3600, false);
	uboot_old = true;
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC 3600");
	uboot_charge_s(5, 1800); uboot_unplugged();
	uboot_charge_s(10, 1200);
	k_probe(); run(10);
	/* an older U-Boot leaves no sample from before the charge: the one
	 * after it reads high (polarisation) and the counter by the FCC's
	 * error; a known limit until 0018 is flashed: nothing learnt, the
	 * level not above the counter's */
	CHECK(fcc() == 3600, "old U-Boot, brown-out, two plug-ins: FCC 3600 -> %%d", fcc());
	CHECK(cap_pct() <= rk818_cap_to_soc(di, rk818_get_coulomb_cap(di)) + 1, "old U-Boot, brown-out, two plug-ins: level %%d above the counter's", cap_pct());
	return true;
}

/* older U-Boot, FCC too large, brown-out, plug-in, wait, key */
static bool D24_old_uboot_brownout_plug_unplug_key(void)
{
	world(3060, 30, 30, 30, true, 3600, false);
	uboot_old = true;
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC 3600");
	uboot_charge_s(5, 1800); uboot_unplugged(); key_power_up(30); run(10);
	/* an older U-Boot leaves no sample from before the charge: the one
	 * after it reads high (polarisation) and the counter by the FCC's
	 * error; a known limit until 0018 is flashed: nothing learnt, the
	 * level not above the counter's */
	CHECK(fcc() == 3600, "old U-Boot, brown-out, plug, unplug, key: FCC 3600 -> %%d", fcc());
	CHECK(cap_pct() <= rk818_cap_to_soc(di, rk818_get_coulomb_cap(di)) + 1, "old U-Boot, brown-out, plug, unplug, key: level %%d above the counter's", cap_pct());
	return true;
}

/* the same, the counter set low: the cycle must not learn from it */
static bool B38_other_system_after_wait_low(void)
{
	for (int v = 0; v < 2; v++) {
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	if (v) { online = 1; run(60); k_power_off(); uboot_wait(60); }
	else { k_power_off(); uboot_charge_s(30, 60); }
	uboot_mark_leave(); uboot_waiting = false;	/* the key: U-Boot leaves, starts it */
	gas = 600.0 * rk818_raw_per_mah(di);
	online = 0; off = false; for (int k = 0; k < 12 * 10; k++) physics(5);
	stay_off(10); pmic_power_up(10, false); k_probe(); run(10);
	int r = discharge(); end_cycle(r, 150);
	CHECK(fcc() <= 3060 * 1.03, "v%d another system after U-Boot's wait set the counter low: FCC %d learnt", v, fcc());
	}
	return true;
}

/* B33 with the SoC reset while asleep (VB_MON at 3.4 V) */
static bool B39_panic_asleep_after_brownout_boot(void)
{
	world(3060, 30, 30, 30, true, 3060, false);
	charge_full(); bare_app = false;
	CHECK(discharge() == 1, "no brown-out");
	bare_app = true;
	usb_up_key_at_once(150);
	charge_full(); online = 0; load_ma = 360;
	while (soc_true() > 15) run(60);
	int c0 = cap_pct(), f0 = fcc();
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 120; k++) physics(5);
	panic_reset(); run(10);
	/* the counter took the sleep's error in (no resume put it right):
	 * not known, safe (not above), and no brown-out read into it */
	CHECK(cap_pct() <= c0 + 3 && fcc() == f0, "a SoC reset asleep at 15%% after a boot from a brown-out: level %d -> %d, FCC %d -> %d", c0, cap_pct(), f0, fcc());
	return true;
}

/* a cycle begun full under 0035 (its zero 700 mA off for 1 h:
 * drawn +700 mAh), a reboot into this driver, the cycle's end */
static bool D25_cycle_from_0035(void)
{
	for (int v = 0; v < 2; v++) {
		world(3060, 50, 30, 30, true, 3060, false);
		charge_full(); online = 0; load_ma = 1000;
		if (v) {
			/* a brown-out under 0035, then this driver's first boot */
			bare_app = false;
			CHECK(discharge() == 1, "no brown-out");
			/* 0035's zero the other way: 700 mAh too little drawn */
			int d = (regs[RK818_CALC_REST_REGH] << 8 | regs[RK818_CALC_REST_REGL]) - 700;
			regs[RK818_CALC_REST_REGH] = d >> 8; regs[RK818_CALC_REST_REGL] = d & 0xff;
			regs[RK818_MISC_MARK_REG] = 0;
			brown_out(150); bare_app = true;
			/* not 0035's 2360 learnt; the initial one (or 3060 if lower) */
			CHECK(fcc() > 2600 && fcc() <= 3060, "FCC %d after a brown-out 0035 counted to (0035's drawn gives 2360)", fcc());
			continue;
		}
		while (soc_true() > 70) run(60);
		system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
		int d = (regs[RK818_CALC_REST_REGH] << 8 | regs[RK818_CALC_REST_REGL]) + 700;
		regs[RK818_CALC_REST_REGH] = d >> 8; regs[RK818_CALC_REST_REGL] = d & 0xff;
		regs[RK818_MISC_MARK_REG] = 0;
		pmic_reset(); physics(5); k_probe(); run(60);
		end_cycle(discharge(), 150);
		CHECK(fcc() <= 3060 * 1.03, "FCC %d learnt from a cycle 0035 counted", fcc());
	}
	return true;
}

/* a hibernation, then a 2 h s2idle sleep on the battery */
static bool E15_hibernate_then_sleep(void)
{
	world(3060, 50, 30, 30, true, 3060, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 70) run(60);
	struct rk818_battery *a = di, snap;
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_FREEZE });
	snap = *a; rk818_battery_resume(&pdev);
	for (int k = 0; k < 4; k++) physics(5);
	k_power_off(); stay_off(30); pmic_power_up(30, true); k_probe(); run(10);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_QUIESCE });
	*a = snap; pdev.drvdata = a; di = a; rk818_battery_resume(&pdev);
	run(60); load_ma = 360;
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 2 * 720; k++) physics(5);
	wake(); run(10);
	CHECK(fabs(cap_pct() - true_level()) <= 3, "a 2 h sleep after a hibernation: level %d, true %.0f", cap_pct(), true_level());
	return true;
}

/* B31 with the last power-up on USB power (ON_SOURCE 0x40 kept) */
static bool B40_reboot_back_last_up_on_usb(void)
{
	good_world(95);
	online = 0; load_ma = 1000;
	while (soc_true() > 60) run(60);
	power_off(10); 
	online = 1; k_power_off(); off = false;
	usb_up_key_at_once(5);
	online = 0;
	while (soc_true() > 30) run(60);
	system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
	pmic_reset(); gas = 2900.0 * rk818_raw_per_mah(di); physics(5);
	pmic_reset(); physics(5); k_probe(); run(10);
	CHECK(cap_pct() <= true_level() + 3, "back from another system by a reboot, up on USB before: level %d, true %.0f", cap_pct(), true_level());
	return true;
}

/* a reboot into another system that only runs (its gauge writes
 * nothing; the counter counts what it draws), back by a reboot */
static bool B41_reboot_other_system_draws(void)
{
	static const int mins[] = { 30, 60, 90 };
	for (int k = 0; k < 3; k++) {
	good_world(95);
	online = 0; load_ma = 1000;
	while (soc_true() > 80) run(60);
	system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
	pmic_reset(); off = false; load_ma = 1000;
	for (int j = 0; j < mins[k] * 12; j++) physics(5);
	pmic_reset(); physics(5); k_probe(); run(10);
	CHECK(cap_pct() <= true_level() + 3, "another system ran %d min, back by a reboot: level %d, true %.0f", mins[k], cap_pct(), true_level());
	}
	return true;
}

/* a reboot from 0035 into this driver (no boot state; its cycle counted
 * with the zero off, its FCC 4800 for a 3060 mAh cell): the level kept (the
 * OCV there is of a power-up at 90%), the cycle dropped, the FCC back to
 * the initial one */
static bool B42_first_boot_after_0035(void)
{
	world(3060, 90, 30, 30, true, 4800, false);
	online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	int c0 = cap_pct();
	system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
	regs[RK818_MISC_MARK_REG] = 0;
	pmic_reset(); physics(5); k_probe(); run(60);
	CHECK(abs(cap_pct() - c0) <= 3 || cap_pct() < c0, "level %d -> %d at the first boot after 0035", c0, cap_pct());
	CHECK(!di->learn_valid, "0035's learning cycle kept");
	CHECK(fcc() <= 3060, "0035's FCC %d kept (above the cell's 3060)", fcc());
	return true;
}
/* a power-off on the charger, the wait, the counter 0.1 mAh under a step
 * of its bits 23:16 when U-Boot leaves, the boot after it crossing the
 * step: still U-Boot's wait */
static bool B43_boot_crosses_a_counter_step(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	online = 1; run(60);
	k_power_off(); uboot_wait(600);
	gas = (double)((((uint32_t)(int32_t)lround(gas) >> 16) + 1) << 16) - 120;
	uboot_mark_leave(); uboot_waiting = false;	/* the key: U-Boot leaves */
	physics(5);			/* charging on, the kernel booting */
	k_probe(); run(10);
	CHECK(di->learn_valid, "the cycle dropped: U-Boot's marks taken for another system's");
	CHECK_LEVEL(5, "the boot crossing a counter step");
	return true;
}
/* the power key held 10 s in U-Boot's wait (the charger pulled first): no
 * U-Boot power-off, no mark where it left; the key later: safe, no FCC */
static bool B44_forced_off_in_the_wait(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	int f0 = fcc();
	online = 1; run(30);
	k_power_off(); uboot_wait(600);
	uboot_waiting = false; online = 0;	/* forced off: U-Boot marks nothing */
	stay_off(10); pmic_power_up_by(10, true, false); k_probe(); run(10);
	CHECK(cap_pct() <= true_level() + 3, "forced off in the wait: level %d, true %.0f", cap_pct(), true_level());
	CHECK(fcc() == f0, "forced off in the wait: FCC %d -> %d", f0, fcc());
	return true;
}
/* an older U-Boot, the FCC 18% too large: a clean power-off at 30% (on the
 * battery), 30 min off, the charger in for 20 min, the key: the sample of
 * no known place (no marks), the counter off by the FCC: the lower of it
 * and the sample plus the charge */
static bool B45_old_uboot_plug_in_wrong_fcc(void)
{
	world(3060, 50, 30, 30, true, 3600, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 30) run(60);
	uboot_old = true;
	k_power_off(); uboot_charge_s(30, 1200); k_probe(); run(10);
	CHECK(cap_pct() <= true_level() + 3, "an older U-Boot, the FCC 3600 for 3060, a plug-in: level %d, true %.0f", cap_pct(), true_level());
	return true;
}
/* the power key held (a hang) at 80, 50, 15%, the charger in 2 or 60 min
 * later, 10 min in the wait, the key: not a brown-out by the OCV; the level
 * the battery's (not "empty plus the charge"), nothing learnt, and 0% on
 * the battery before a brown-out (review round 3: 8% at 91%) */
static bool B46_key_held_then_charger(void)
{
	static const double at[] = { 80, 50, 15 };
	static const int before[] = { 2, 60 };
	for (int a = 0; a < 3; a++)
		for (int b = 0; b < 2; b++) {
			good_world(30);
			charge_full(); online = 0; load_ma = 1000;
			while (soc_true() > at[a]) run(60);
			int f0 = fcc();
			uboot_charge_s(before[b], 600); k_probe(); run(10);
			/* at 15% 2 min off the sample is not back from the load
			 * yet: at the flat bottom 20 mV are some 15% (low: safe) */
			CHECK(cap_pct() <= true_level() + 3 && cap_pct() >= true_level() - (at[a] < 20 ? 18 : 12),
			      "the key held at %.0f%%, the charger %d min later: level %d, true %.0f", at[a], before[b], cap_pct(), true_level());
			CHECK(fcc() == f0, "the key held at %.0f%%: FCC %d -> %d", at[a], f0, fcc());
			online = 0; load_ma = 360; off_left = -1;
			CHECK(discharge() == 2, "the key held at %.0f%%: a brown-out before 0%%", at[a]);
		}
	return true;
}
/* the kernel hung (no work, nothing saved) 10-120 s at a game's load at 70%,
 * the key held, on again 1 min later (or the charger in, 10 min): the level
 * the battery's, not 0 */
static bool B47_hang_then_key(void)
{
	static const int hang[] = { 10, 30, 120, 120 };
	for (int k = 0; k < 4; k++) {
		good_world(30);
		charge_full(); online = 0; load_ma = 1000;
		while (soc_true() > 70) run(60);
		int f0 = fcc();
		load_ma = 1600;
		for (int j = 0; j < hang[k] / 5; j++) physics(5);
		if (k == 3) { uboot_charge_s(1, 600); k_probe(); }
		else brown_out(1);
		run(10);
		CHECK(cap_pct() <= true_level() + 3 && cap_pct() >= true_level() - 12,
		      "hung %d s at 70%%%s, the key held: level %d, true %.0f", hang[k], k == 3 ? ", the charger in" : "", cap_pct(), true_level());
		CHECK(fcc() == f0, "hung %d s: FCC %d -> %d", hang[k], f0, fcc());
	}
	return true;
}
/* a s2idle sleep that did not wake (0036's note: the red LED) 35 or 120 min
 * at 50%, the key held, on again (or the charger in, 5 min): not 0 */
static bool B48_sleep_stuck_then_key(void)
{
	static const int mins[] = { 35, 35, 120 };
	for (int k = 0; k < 3; k++) {
		good_world(30);
		charge_full(); online = 0; load_ma = 1000;
		while (soc_true() > 50) run(60);
		load_ma = 360;
		rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
		for (int j = 0; j < mins[k] * 12; j++) physics(5);
		awake = 1;
		if (k == 1) { uboot_charge_s(1, 300); k_probe(); }
		else brown_out(1);
		run(10);
		CHECK(cap_pct() <= true_level() + 3 && cap_pct() >= true_level() - 12,
		      "stuck asleep %d min%s, the key held: level %d, true %.0f", mins[k], k == 1 ? ", the charger in" : "", cap_pct(), true_level());
	}
	return true;
}
/* U-Boot's counter mark from an earlier wait, the key held in a later one
 * (no new mark): taken for none; no FCC from the sample after the charge */
static bool B49_stale_counter_mark(void)
{
	good_world(60);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge_s(40, 100); k_probe(); run(10);	/* a short wait, the key: a mark */
	charge_full(); online = 0; load_ma = 1000;
	CHECK(discharge() == 2, "no second 0%% power-off");
	int f0 = fcc();
	k_power_off();
	uboot_charge_s(40, 100);
	uboot_waiting = false; online = 0;		/* the key held in the wait */
	stay_off(40); pmic_power_up_by(40, true, false); k_probe(); run(10);
	CHECK(fcc() == f0, "a stale counter mark: FCC %d -> %d learnt from a sample after the charge", f0, fcc());
	CHECK(cap_pct() <= true_level() + 3, "a stale counter mark: level %d, true %.0f", cap_pct(), true_level());
	return true;
}
/* the FCC too large (3600 for 3060) or right; a brown-out, the charger in
 * at once, 10 or 30 min in U-Boot's wait, the key held there (no mark where
 * it left), on again by the key 0-60 min later or by USB (U-Boot starts at
 * once): U-Boot's marks do not stand, its sample from before the charge
 * does: not above the battery's (review round 4: 20 for 8) */
static bool B50_brownout_charger_key_held_in_wait(void)
{
	static const int fccs[] = { 3060, 3600 }, waitm[] = { 10, 30 }, offm[] = { 0, 5, 60, -3 };
	for (int f = 0; f < 2; f++)
		for (int w = 0; w < 2; w++)
			for (int o = 0; o < 4; o++) {
				world(3060, 30, 30, 30, true, fccs[f], false);
				charge_full(); bare_app = false;
				CHECK(discharge() == 1, "no brown-out");
				bare_app = true; brownouts++;
				uboot_charge_s(0, waitm[w] * 60);
				uboot_waiting = false; online = 0;	/* the key held: forced off */
				if (offm[o] < 0) usb_up_key_at_once(-offm[o]);
				else key_power_up(offm[o]);
				run(10);
				/* not above the battery's; not below what the charge gives
				 * with the driver's FCC (a FCC too large shows it lower) */
				CHECK(cap_pct() <= true_level() + 3 && cap_pct() >= fcc_level() - 4, "FCC %d, %d min in the wait, the key held, on %s %d min later: level %d, true %.0f",
				      fccs[f], waitm[w], offm[o] < 0 ? "by USB" : "by the key", abs(offm[o]), cap_pct(), true_level());
				CHECK(fcc() == fccs[f], "FCC %d -> %d after a brown-out, the key held in the wait", fccs[f], fcc());
			}
	return true;
}
/* full under 0035 with its FCC 4800 (the counter at 4800) and still on the
 * charger, a reboot into this driver, the charger out at once: the level
 * follows the battery, not 100 for half of it (OGU2, 2026-11-21) */
static bool B51_first_boot_after_0035_full(void)
{
	world(3060, 50, 30, 30, true, 4800, false);
	charge_full();
	system_state = SYSTEM_RESTART; rk818_battery_shutdown(&pdev); system_state = SYSTEM_RUNNING;
	regs[RK818_MISC_MARK_REG] = 0;
	pmic_reset(); physics(5); k_probe(); run(10);
	online = 0; load_ma = 1000;
	for (int k = 0; k < 6; k++) {
		run(600);
		CHECK(cap_pct() <= true_level() + 3, "after the first boot from 0035 at full: level %d, true %.0f", cap_pct(), true_level());
	}
	return true;
}
static bool B6_new_console(void)
{
	world(3060, 60, 30, 0, false, 0, true);
	CHECK(abs(cap_pct() - 59) <= 5, "level %d at the first power-on (true 59)", cap_pct());
	for (int c = 0; c < 6; c++) {
		charge_full(); run(3600);
		end_cycle(discharge(), 150);
	}
	CHECK(!brownout_hi, "%d brown-outs above 5%%", brownout_hi);
	CHECK(off_left <= 30, "the first 0%% power-off with %.0f%% left", off_left);
	CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.03, "FCC %d after 6 cycles (true 3060)", fcc());
	return true;
}
static bool B7_stock_values(void)
{
	world(3060, 60, 30, 0xd3, false, 3900, false);	/* -45 as a byte, FCC 3900 */
	for (int c = 0; c < 5; c++) {
		charge_full(); run(3600);
		end_cycle(discharge(), 150);
	}
	CHECK(fabs(zero_err_ma()) <= 15, "zero %.0f mA off", zero_err_ma());
	CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.03, "FCC %d after 5 cycles (true 3060)", fcc());
	return true;
}
/* charging from 40%, then the charge inhibited on the charger for 20 min:
 * the relaxed voltage the PMIC takes then is the charge's polarisation */
static bool C5_inhibit_after_charge(void)
{
	good_world(40);
	online = 1;
	double worst = 0;
	for (int k = 0; k < 720; k++) { run(5); worst = fmax(worst, cap_pct() - true_level()); }
	k_set(POWER_SUPPLY_PROP_CHARGE_BEHAVIOUR, POWER_SUPPLY_CHARGE_BEHAVIOUR_INHIBIT_CHARGE);
	for (int k = 0; k < 240; k++) { run(5); worst = fmax(worst, cap_pct() - true_level()); }
	CHECK(worst <= 5, "the level up to %.0f%% above the battery's in a charge and its inhibit", worst);
	return true;
}
/* full on a weak charger, then a game bigger than it gives for 40 min:
 * not full any more, the level follows the battery down */
static bool C6_full_then_game_on_weak_charger(void)
{
	good_world(80);
	online = 1; charge_full();
	supply_ma = 700; load_ma = 1600; run(2400);
	double t = true_level();
	CHECK(cap_pct() <= t + 5, "level %d after 40 min of a game on a weak charger (true %.0f)", cap_pct(), t);
	return true;
}
static bool C1_up_on_charger_reading_negative(void)
{
	good_world(78);
	run(10);
	regs[RK818_SOC_REG] = 10;	/* the level a reset left */
	panic_reset();
	zero_shift = -133;		/* the zero 400 mA off, reads below 0 */
	online = 1; supply_ma = 360 + 150;	/* 150 mA into the battery */
	int c0 = cap_pct(); run(300);
	CHECK(cap_pct() >= c0 + 20, "level %d -> %d in 5 min on the charger", c0, cap_pct());
	return true;
}
static bool C2_no_rise_on_battery(void)
{
	good_world(100);
	for (int c = 0; c < 3; c++) { charge_full(); end_cycle(discharge(), 150); }
	CHECK(!rises, "the level rose %d times on the battery", rises);
	return true;
}
static bool C3_step_at_charge_end(void)
{
	world(3060, 50, 30, 30, true, 3500, false);
	online = 1; max_up = 0;
	while (chg != 2) run(60);
	run(600);
	CHECK(max_up <= 1, "the level jumped %d%% at once", max_up);
	CHECK(cap_pct() == 100, "level %d 10 min after the end of the charge", cap_pct());
	return true;
}
static bool C4_full_on_weak(void)
{
	good_world(80);
	online = 1; helps = 190; charge_full();
	int lo = 100;
	for (int k = 0; k < 180; k++) { run(60); if (cap_pct() < lo) lo = cap_pct(); }
	CHECK(lo >= 99, "the level fell to %d full on the charger", lo);
	return true;
}
static bool D1_zero_converges(void)
{
	world(3060, 50, 30, 30, true, 2500, false);
	for (int c = 0; c < 6; c++) { charge_full(); end_cycle(discharge(), 150); }
	CHECK(!brownouts, "%d brown-outs", brownouts);
	CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.03, "FCC %d after 6 cycles (true 3060)", fcc());
	return true;
}
static bool D2_zero_with_charger(void)
{
	good_world(60);
	charge_full(); bare_app = false; online = 0; load_ma = 1000;
	while (cap_pct() > 0) run(60);
	int f0 = fcc();
	online = 1; run(5);
	k_power_off(); uboot_wait(20 * 60);	/* U-Boot's wait, charging */
	uboot_unplugged(); key_power_up(200);
	CHECK(fcc() == f0, "FCC %d -> %d after a shutdown at 0%% on the charger", f0, fcc());
	run(10); CHECK_LEVEL(5, "charged 20 min in U-Boot after a shutdown at 0% on the charger, the key 200 min later");
	return true;
}
static bool D3_no_bare_app(void)
{
	world(3060, 50, 30, 30, true, 2500, false);
	charge_full(); bare_app = false;
	int r = discharge();
	CHECK(r == 1, "no brown-out");
	CHECK(cap_pct() == 0, "level %d at the brown-out", cap_pct());
	CHECK(!rises, "the level rose %d times on the battery", rises);
	brown_out(150);
	CHECK(near(fcc(), 3060, 3), "FCC %d after the brown-out (true 3060)", fcc());
	return true;
}
static bool D4_weak_charger_at_zero(void)
{
	world(3060, 50, 30, 30, true, 2500, false);
	charge_full(); bare_app = false; online = 0; load_ma = 1000;
	while (cap_pct() > 0) run(60);
	online = 1; supply_ma = 700; load_ma = 1000; run(1200);	/* charging, 300 mA out */
	int r = discharge();
	CHECK(r == 1, "no brown-out");
	brown_out(150);
	CHECK(near(fcc(), 3060, 3), "FCC %d after the brown-out (true 3060)", fcc());
	return true;
}
/* U-Boot's wait for the power key, charging (u-boot 0001), and 0018's marks
 * in MISC_MARK (0xee): WAITED; FIRST_WAIT (the first wait since Linux ran);
 * STASHED with the OCV sample kept in OCV_USED when the PMIC was reset; at
 * its leaving (the key, its power-off) the counter's bits 23:16 in 0xea */
/* leaving the wait (the key, its power-off): the counter's bits 23:16 */
static void uboot_mark_leave(void) { if (!uboot_old) regs[RK818_NON_ACT_TIMER_CNT_SAVE_REG] = ((uint32_t)(int32_t)lround(gas) >> 16) & 0xff; }
static void uboot_wait_enter(void)
{
	uint8_t bs = regs[RK818_MISC_MARK_REG], f = regs[RK818_VB_MON_REG] & 7;
	uboot_waiting = true;
	if (uboot_old || (bs & 0xe0) != 0xc0) return;
	if (!(bs & BIT(2))) {
		bs |= BIT(4);			/* FIRST_WAIT */
		if (f != 2 && f != 6) {		/* the PMIC reset: STASHED */
			regs[RK818_OCV_VOL_VALID_REG] = regs[RK818_BAT_OCV_REGH];
			regs[RK818_REBOOT_CNT_REG] = regs[RK818_BAT_OCV_REGL];
			bs |= BIT(3);
		}
	}
	regs[RK818_MISC_MARK_REG] = bs | BIT(2);	/* WAITED */
}
static void uboot_wait(int secs) { off = true; for (int k = 0; k < secs / 5; k++) physics(5); }
/* off `before` min, then plugged in: up on USB power, U-Boot waits charging */
static void uboot_charge_s(int before, int secs)
{
	stay_off(before);
	online = 1; pmic_power_up_by(before, false, true);
	uboot_wait_enter();
	uboot_wait(secs);
}
static void uboot_charge(int before, int min) { uboot_charge_s(before, min * 60); }
/* ... and the charger pulled: U-Boot powers the board off (a real off) */
static void uboot_unplugged(void)
{
	uint8_t bs = regs[RK818_MISC_MARK_REG];
	if (!uboot_old && (bs & 0xe0) == 0xc0) {
		regs[RK818_MISC_MARK_REG] = bs & ~(BIT(1) | BIT(4));
		uboot_mark_leave();
	}
	uboot_waiting = false;
	online = 0; physics(5);
}
/* later the power key (BAT_CON after a power-off by U-Boot, ogu1) */
static void key_power_up(int min)
{
	stay_off(min); pmic_power_up_by(min, true, false); k_probe();
}
/* up on USB power with the power key already pressed: U-Boot starts Linux
 * at once (no wait, nothing kept) */
static void usb_up_key_at_once(int before)
{
	stay_off(before);
	online = 1; pmic_power_up_by(before, false, true);
	k_probe();
}
static bool D5_charged_by_uboot_unplugged(void)
{
	static const int mins[] = { 3, 10, 30, 90, 10 }, keys[] = { 40, 40, 40, 40, 121 };
	for (int k = 0; k < 5; k++) {
		int chmin = mins[k];
		good_world(60);
		charge_full();
		CHECK(discharge() == 2, "no 0%% power-off");
		int f0 = fcc();
		k_power_off();
		uboot_charge(30, chmin); uboot_unplugged();
		key_power_up(keys[k]);
		CHECK(fcc() == f0, "charged %d min by U-Boot: FCC %d -> %d", chmin, f0, fcc());
		run(10); CHECK_LEVEL(5, "charged in U-Boot, unplugged, the key later");
	}
	return true;
}
static bool D6_charged_by_uboot_then_key(void)
{
	world(3060, 50, 30, 30, true, 2700, false);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge(150, 60);
	k_probe();		/* the power key: Linux on the OCV taken at the plug-in */
	CHECK(fcc() > 2720 && fcc() <= 3060 * 1.03, "FCC %d after a 0%% cycle and a charge in U-Boot (was 2700, true 3060)", fcc());
	run(10); CHECK_CHARGE(5, "60 min in U-Boot after 0%, the key from the wait");
	return true;
}
/* the FCC learnt 2% high: 0% still comes before the brown-out */
static bool D7_fcc_a_little_high(void)
{
	world(3060, 50, 30, 30, true, 3120, false);
	charge_full();
	int r = discharge();
	CHECK(r == 2, "a brown-out before 0%% with the FCC 2%% high");
	return true;
}
/* charged in U-Boot's wait, unplugged (U-Boot powers off), started later:
 * the cycle went on without counting that charge */
static bool D8_uboot_charge_cycle_goes_on(void)
{
	good_world(60);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge(30, 60); uboot_unplugged();
	key_power_up(40);
	run(10); CHECK_LEVEL(5, "60 min in U-Boot, unplugged, the key 40 min later");
	online = 0; end_cycle(discharge(), 150);
	CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.03, "FCC %d a cycle after a charge in U-Boot (true 3060)", fcc());
	return true;
}
/* 10 min off at 0%, plugged in, U-Boot charges, the power key */
static bool D9_uboot_charge_short_pause_key(void)
{
	good_world(60);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge(10, 60);
	k_probe(); online = 0;
	end_cycle(discharge(), 150);
	CHECK(fcc() <= 3060 * 1.03, "FCC %d after a 0%% cycle and a U-Boot charge (true 3060)", fcc());
	return true;
}
/* D2 one cycle on: shut down at 0% on the charger, charged while off */
static bool D10_zero_with_charger_next_cycle(void)
{
	good_world(60);
	charge_full(); bare_app = false; online = 0; load_ma = 1000;
	while (cap_pct() > 0) run(60);
	online = 1; run(5);
	k_power_off(); uboot_wait(20 * 60);
	uboot_unplugged(); key_power_up(40);
	bare_app = true; online = 0; end_cycle(discharge(), 150);
	CHECK(fcc() <= 3060 * 1.03, "FCC %d a cycle after a shutdown at 0%% on the charger", fcc());
	return true;
}
/* a shutdown at 50%, 30 min charged in U-Boot, off, rest: not the cycle's */
static bool D11_halfway_shutdown_uboot_charge(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	k_power_off();
	uboot_charge(5, 30); uboot_unplugged();
	key_power_up(150);
	online = 0; end_cycle(discharge(), 150);
	CHECK(fcc() <= 3060 * 1.03, "FCC %d after a cycle with a charge in U-Boot (true 3060)", fcc());
	return true;
}
/* the OCV at rest a few mV off the table at the bottom: 10 cycles of 0% */
static bool D12_table_bottom_off(void)
{
	static const int bias[] = { -8, 8 };
	for (int b = 0; b < 2; b++) {
		world(3060, 50, 30, 30, true, 2900, false);
		for (int c = 0; c < 10; c++) {
			charge_full();
			int r = discharge();
			ocv_bias = bias[b]; end_cycle(r, 150); ocv_bias = 0;
		}
		CHECK(!brownouts, "OCV %+d mV off the table: %d brown-outs in 10 cycles", bias[b], brownouts);
		/* from below (0% leaves the reserve and ZERO_UNCERT), 1% above at most */
		CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.01, "OCV %+d mV off the table: FCC %d", bias[b], fcc());
	}
	return true;
}
/* an older U-Boot (no 0018): charged in its wait, the power key; the
 * voltage shows the charge */
static bool D13_old_uboot_charge_key(void)
{
	good_world(60);
	uboot_old = true;
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	k_power_off();
	uboot_charge(10, 60);
	k_probe(); online = 0;
	end_cycle(discharge(), 150);
	CHECK(fcc() <= 3060 * 1.03, "older U-Boot: FCC %d after a charge in its wait (true 3060)", fcc());
	return true;
}
/* an older U-Boot: powered off on the charger at 50%, charged, unplugged */
static bool D14_old_uboot_off_on_charger(void)
{
	good_world(60);
	uboot_old = true;
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	online = 1; run(5);
	k_power_off(); uboot_wait(30 * 60);
	uboot_unplugged(); key_power_up(150);
	online = 0; end_cycle(discharge(), 150);
	CHECK(fcc() <= 3060 * 1.03, "older U-Boot: FCC %d after a power-off on the charger (true 3060)", fcc());
	return true;
}
/* the FCC too large: a brown-out, the charger in after 5 or 20 min (U-Boot's
 * wait, then the power key): the brown-out teaches */
static bool D15_brownout_then_charger(void)
{
	/* in 5 or 20 min: not rested, not known whether a brown-out or a key
	 * held: nothing learnt (the user's rule); in 40: it teaches */
	static const int fccs[] = { 3600, 3300 }, mins[] = { 5, 20, 40 };
	for (int f = 0; f < 2; f++)
		for (int m = 0; m < 3; m++) {
			world(3060, 30, 30, 30, true, fccs[f], false);
			charge_full();
			CHECK(discharge() == 1, "no brown-out with the FCC %d", fccs[f]);
			brownouts++;
			uboot_charge_s(mins[m], 120);
			k_probe(); run(10);
			if (mins[m] >= LEARN_REST_MIN)
				CHECK(fcc() >= 3060 * 0.95 && fcc() <= 3060 * 1.03, "FCC %d, charger in %d min after the brown-out: FCC %d", fccs[f], mins[m], fcc());
			else
				CHECK(fcc() == fccs[f], "FCC %d, charger in %d min after the brown-out (not rested): FCC %d", fccs[f], mins[m], fcc());
			CHECK(cap_pct() <= 8, "FCC %d, charger in %d min after the brown-out: level %d", fccs[f], mins[m], cap_pct());
		}
	return true;
}
/* the FCC too large: a brown-out, the charger in 5 min later, U-Boot charges,
 * the charger out (U-Boot powers off), the key later: not rested before the
 * charge, nothing learnt; the level not above the charge's */
static bool D16_brownout_charge_unplug_key(void)
{
	world(3060, 30, 30, 30, true, 3600, false);
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC 3600");
	brownouts++;
	uboot_charge_s(5, 30 * 60); uboot_unplugged();
	key_power_up(20); run(10);
	CHECK(fcc() == 3600, "after a brown-out, charged in U-Boot, the key later: FCC 3600 -> %d (not rested before the charge)", fcc());
	CHECK(cap_pct() <= fcc_level() + 3, "after a brown-out, charged in U-Boot, the key later: level %d, the charge gives %.0f", cap_pct(), fcc_level());
	return true;
}
/* a power-off with the charger in (the PMIC stays up), 10 min in U-Boot's
 * wait, the key: the counter saw the charge, the cycle goes on */
static bool B19_power_off_on_charger_wait_key(void)
{
	good_world(60);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	online = 1; run(60);
	k_power_off(); uboot_wait(600);
	k_probe(); run(10);
	CHECK_LEVEL(3, "a power-off on the charger, 10 min in U-Boot's wait, the key");
	CHECK(di->learn_valid, "the learning cycle dropped");
	return true;
}
/* D5 with an older U-Boot (no OCV kept): the OCV after its charge is no
 * end of the cycle, nothing learnt from it */
static bool D17_old_uboot_charged_unplugged(void)
{
	static const int mins[] = { 10, 30 };
	for (int k = 0; k < 2; k++) {
		good_world(60);
		uboot_old = true;
		charge_full();
		CHECK(discharge() == 2, "no 0%% power-off");
		int f0 = fcc();
		k_power_off();
		uboot_charge(30, mins[k]); uboot_unplugged();
		key_power_up(40);
		CHECK(fcc() == f0, "older U-Boot, charged %d min, unplugged: FCC %d -> %d", mins[k], f0, fcc());
		run(10); CHECK_LEVEL(5, "older U-Boot, charged in its wait, unplugged, the key later");
	}
	return true;
}
/* the FCC too large, a brown-out, the charger in for 30 min, out, in again
 * 10 min later for 20 min, the key from the wait: U-Boot kept the first
 * plug-in's OCV; the brown-out teaches */
static bool D18_brownout_two_plug_ins(void)
{
	world(3060, 30, 30, 30, true, 3600, false);
	charge_full();
	CHECK(discharge() == 1, "no brown-out with the FCC 3600");
	brownouts++;
	uboot_charge_s(5, 1800); uboot_unplugged();
	uboot_charge_s(10, 1200);
	k_probe(); run(10);
	CHECK(fcc() == 3600, "FCC 3600 -> %d after a brown-out and two plug-ins (not rested)", fcc());
	CHECK(cap_pct() <= fcc_level() + 3, "after a brown-out and two plug-ins: level %d, the charge gives %.0f", cap_pct(), fcc_level());
	return true;
}
/* a shutdown at 0% on the charger, 20 min in the wait, unplugged, 60 min
 * off, plugged in again: 10 min in the wait or the key at once; no sample
 * before the charge: nothing learnt */
static bool D19_zero_on_charger_replugged(void)
{
	for (int v = 0; v < 2; v++) {
		good_world(60);
		charge_full(); bare_app = false; online = 0; load_ma = 1000;
		while (cap_pct() > 0) run(60);
		int f0 = fcc();
		online = 1; run(5);
		k_power_off(); uboot_wait(20 * 60);
		uboot_unplugged();
		if (v) { uboot_charge_s(60, 600); k_probe(); }
		else usb_up_key_at_once(60);
		run(10);
		CHECK(fcc() == f0, "0%% on the charger, replugged: FCC %d -> %d", f0, fcc());
		CHECK_LEVEL(5, "0% on the charger, replugged");
	}
	return true;
}
/* the FCC too large, a brown-out, the charger in under a minute, 20 min in
 * the wait, the key; this U-Boot and an older one */
static bool D20_brownout_charger_at_once(void)
{
	static const int fccs[] = { 3600, 3300 };
	for (int v = 0; v < 6; v++) {
		world(3060, 30, 30, 30, true, fccs[v & 1], false);
		charge_full();
		if (v >= 4) { online = 0; power_off(0); }	/* that boot < 1 min off too */
		CHECK(discharge() == 1, "no brown-out with the FCC %d", fccs[v & 1]);
		brownouts++;
		uboot_old = (v & 2) && v < 4;
		uboot_charge_s(0, 1200);
		k_probe(); run(10);
		/* not rested: nothing learnt (the user's rule) */
		CHECK(fcc() == fccs[v & 1], "%s U-Boot: FCC %d -> %d after a brown-out, the charger at once",
		      uboot_old ? "an older" : "this", fccs[v & 1], fcc());
		CHECK_CHARGE(6, "a brown-out, the charger at once");
	}
	return true;
}
/* a battery larger than the design (5000 mAh for 4000): the FCC learns it */
static bool D21_battery_above_design(void)
{
	world(5000, 50, 30, 30, true, 3600, false);
	for (int c = 0; c < 8; c++) { charge_full(); end_cycle(discharge(), 150); }
	CHECK(fcc() >= 5000 * 0.85 && fcc() <= 5000 * 1.03, "FCC %d after 8 cycles (true 5000)", fcc());
	return true;
}
/* if the minutes-off counter stops at 255: two shutdowns at 0%, each a
 * night off, each teaches (the second's FCC from the first's) */
static bool D22_nights_off_timer_stops(void)
{
	world(3060, 50, 30, 30, true, 2500, false);
	timer_stops = true;
	for (int c = 0; c < 6; c++) { charge_full(); end_cycle(discharge(), 600); }
	CHECK(!brownouts, "%d brown-outs", brownouts);
	CHECK(fcc() >= 3060 * 0.88 && fcc() <= 3060 * 1.03, "FCC %d after 6 cycles with nights off (true 3060)", fcc());
	return true;
}
/* a FCC far too small (1500 for 3060, a seed): 0% comes with half left;
 * the 0% cycles (30 min off each) raise it */
static bool D26_fcc_far_too_small(void)
{
	world(3060, 50, 30, 30, true, 1500, false);
	for (int c = 0; c < 6; c++) { charge_full(); end_cycle(discharge(), 60); }
	CHECK(!brownouts, "%d brown-outs", brownouts);
	CHECK(fcc() >= 3060 * 0.85 && fcc() <= 3060 * 1.01, "FCC %d after 6 cycles from 1500 (true 3060)", fcc());
	return true;
}
/* a 0% power-off, the key 10 min later: not rested, nothing learnt; a 0%
 * power-off rested teaches once: a part charge and 0% again teach nothing
 * (the cycle is used: it began full) */
static bool D27_zero_rest_and_once(void)
{
	world(3060, 50, 30, 30, true, 2600, false);
	charge_full();
	CHECK(discharge() == 2, "no 0%% power-off");
	int f0 = fcc();
	power_off(10);
	CHECK(fcc() == f0, "FCC %d -> %d from a 0%% power-off 10 min off", f0, fcc());
	online = 0; CHECK(discharge() == 2, "no 0%% power-off again");
	power_off(60);
	int f1 = fcc();
	CHECK(f1 > f0, "FCC %d -> %d: nothing learnt from a rested 0%% power-off", f0, f1);
	online = 1; while (soc_true() < 30) run(60);
	online = 0; CHECK(discharge() == 2, "no 0%% power-off after a part charge");
	power_off(60);
	CHECK(fcc() == f1, "FCC %d -> %d from a cycle already used", f1, fcc());
	return true;
}
static bool E2_sleep_on_battery(void)
{
	good_world(80);
	online = 0; run(60);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 2 * 720; k++) physics(5);
	wake(); run(10);
	double t = true_level();
	CHECK(fabs(cap_pct() - t) <= 3, "level %d after 2 h asleep (true %.0f)", cap_pct(), t);
	return true;
}
/* 3 h asleep off the charger: the level after it is the battery's */
static bool E9_long_sleep_on_battery(void)
{
	good_world(90);
	online = 0; run(60);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 3 * 720; k++) physics(5);
	wake(); run(10);
	double t = true_level();
	CHECK(fabs(cap_pct() - t) <= 3, "level %d after 3 h asleep (true %.0f)", cap_pct(), t);
	return true;
}
/* a cycle with three sleeps of 2 h: what it drew counts them right */
static bool E10_cycle_with_sleeps(void)
{
	world(3060, 50, 30, 30, true, 2700, false);
	charge_full(); online = 0;
	for (int k = 0; k < 3; k++) {
		load_ma = 1000; run(1800);
		rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
		for (int j = 0; j < 2 * 720; j++) physics(5);
		wake();
	}
	end_cycle(discharge(), 150);
	CHECK(fcc() > 2720 && fcc() <= 3060 * 1.03, "FCC %d after a cycle with sleeps (was 2700, true 3060)", fcc());
	return true;
}
/* the FCC 30% too large, 40 min asleep at half: the rest puts the level right */
static bool E11_rest_puts_the_level_right(void)
{
	world(3060, 50, 30, 30, true, 4000, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	load_ma = 360; run(120);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 75 * 12; k++) physics(5);
	wake(); run(300);
	double t = true_level();
	CHECK(fabs(cap_pct() - t) <= 6, "level %d after a rest (true %.0f, FCC 4000 for 3060)", cap_pct(), t);
	return true;
}
/* a game down to 25% (the flat part), then asleep 22 and 50 min: the
 * polarisation of the game is still in the voltage at the wake */
static bool E12_sleep_after_game(void)
{
	static const int mins[] = { 22, 50 };
	for (int m = 0; m < 2; m++) {
		good_world(90);
		online = 0; load_ma = 1600;
		while (soc_true() > 25) run(60);
		rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
		for (int k = 0; k < mins[m] * 12; k++) physics(5);
		wake(); run(10);
		double t = true_level();
		CHECK(cap_pct() >= t - 6 && cap_pct() <= t + 3, "%d min asleep after a game: level %d, true %.0f", mins[m], cap_pct(), t);
	}
	return true;
}
/* 90 min asleep at about 25% (the flat part): the rest's OCV within 4% */
static bool E13_rest_at_the_flat_part(void)
{
	world(3060, 50, 30, 30, true, 3400, false);
	charge_full(); online = 0; load_ma = 360;
	while (soc_true() > 26) run(60);
	run(1800);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 90 * 12; k++) physics(5);
	wake(); run(300);
	double t = true_level();
	CHECK(fabs(cap_pct() - t) <= 4, "level %d after 90 min asleep at the flat part (true %.0f, FCC 3400 for 3060)", cap_pct(), t);
	return true;
}
/* a hibernation's image written for 5 min after the thaw: no sleep's
 * correction over it (measured in s2idle only) */
static bool E14_thaw_no_sleep_fix(void)
{
	good_world(60);
	online = 0; load_ma = 360; run(60);
	double q0 = q; int d0 = di->drawn_mah;
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_FREEZE });
	for (int k = 0; k < 60; k++) physics(5);	/* awake, writing */
	rk818_battery_resume(&pdev); run(10);
	CHECK(fabs(di->drawn_mah - d0 - (q0 - q)) <= 3, "drawn %d -> %d over a thaw, the battery gave %.0f mAh", d0, di->drawn_mah, q0 - q);
	return true;
}
static bool E3_hibernate_midway(void)
{
	world(3060, 50, 30, 30, true, 2800, false);
	charge_full(); online = 0; load_ma = 1000;
	while (soc_true() > 50) run(60);
	struct rk818_battery *a = di, snap;
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_FREEZE });
	snap = *a;				/* the image */
	rk818_battery_resume(&pdev);		/* thaw */
	for (int k = 0; k < 4; k++) physics(5);	/* writing it */
	k_power_off();
	stay_off(150); pmic_power_up(150, true);	/* BAT_CON after it */
	k_probe();				/* the boot kernel */
	run(10);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_QUIESCE });
	*a = snap; pdev.drvdata = a; di = a;	/* the image restored */
	rk818_battery_resume(&pdev);
	CHECK(fcc() == (int)(regs[RK818_NEW_FCC_REG1] << 8 | regs[RK818_NEW_FCC_REG0]),
	      "the restored kernel's FCC %d is not the saved one", fcc());
	int r = discharge();
	double drawn_true = cap_true - q;
	CHECK(fabs(di->drawn_mah - drawn_true) <= cap_true * 0.03, "drawn %d, true %.0f", di->drawn_mah, drawn_true);
	end_cycle(r, 150);
	CHECK(fcc() > 2800, "FCC %d after the cycle with a hibernation (was 2800, true 3060): nothing learnt", fcc());
	return true;
}
/* a short sleep full on the charger (or the thaw of a hibernation): the
 * counter just under full is no drift, the cycle goes on */
static bool E4_short_sleep_full(void)
{
	world(3060, 50, 30, 30, true, 2700, false);
	online = 1; helps = 190; charge_full(); run(300);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 360; k++) physics(5);	/* 30 min: the battery gives some */
	wake();
	end_cycle(discharge(), 150);
	CHECK(fcc() > 2720, "FCC %d: the cycle after a short sleep full on the charger taught nothing (was 2700)", fcc());
	return true;
}
/* full on the charger, 30 min asleep, unplugged in it: no drift, the cycle
 * still teaches */
static bool E6_short_sleep_unplugged(void)
{
	world(3060, 50, 30, 30, true, 2700, false);
	online = 1; charge_full(); run(300);
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	for (int k = 0; k < 180; k++) physics(5);
	online = 0;
	for (int k = 0; k < 180; k++) physics(5);
	wake();
	end_cycle(discharge(), 150);
	CHECK(fcc() > 2720, "FCC %d: a short sleep, unplugged in it, dropped the cycle (was 2700)", fcc());
	return true;
}
/* full on the charger, unplugged in a sleep, 7 h on the battery, plugged
 * in again before the wake: what it gave is real */
static bool E7_unplugged_replugged_in_sleep(void)
{
	good_world(80);
	online = 1; charge_full();
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	online = 0;
	for (int k = 0; k < 7 * 720; k++) physics(5);
	online = 1; physics(5);
	wake(); run(120);
	double t = true_level();
	CHECK(cap_pct() <= t + 3, "level %d after the sleep, true %.0f", cap_pct(), t);
	online = 0;
	CHECK(discharge() == 2, "a brown-out before 0%%");
	return true;
}
/* full on the charger, unplugged in a sleep, 8% given; the OCV at rest
 * 20 mV above the table */
static bool E8_unplugged_in_sleep_table_high(void)
{
	good_world(80);
	online = 1; charge_full();
	rk818_battery_suspend(&pdev, (pm_message_t){ PM_EVENT_SUSPEND }); awake = 0;
	online = 0; load_ma = 360;
	for (int k = 0; k < 8 * 720; k++) physics(5);
	v_bias = 20; wake(); run(120); v_bias = 0;
	double t = true_level();
	CHECK(cap_pct() <= t + 3, "level %d after the sleep, true %.0f", cap_pct(), t);
	CHECK(discharge() == 2, "a brown-out before 0%%");
	return true;
}
static bool F1_log_once(void)
{
	good_world(80);
	online = 1; helps = 190; charge_full();
	int n0 = n_charge_finish;
	run(3 * 3600);
	CHECK(n_charge_finish - n0 <= 12, "%d 'charge finish' lines in 3 h", n_charge_finish - n0);
	return true;
}

static struct { const char *name; bool (*fn)(void); } cells[] = {
#define C(x) { #x, x }
	C(A1_fresh_strong), C(A2_fresh_weak), C(A3_legacy_byte), C(A4_limit_in_window),
	C(A5_ioffset_moves), C(A6_zero_found_again), C(A6b_zero_found_right_inside), C(A7_zeroed_to_zero), C(A16_sleep_zero_differs),
	C(A9_sleep_on_charger), C(A10_charge_ends_asleep), C(A11_default_right), C(A12_limit_lowered_charging),
	C(A13_ends_scatter), C(A14_plugged_above_limit), C(A15_one_odd_end), C(A17_full_stays_full), C(A18_full_top_up_with_a_game), C(A19_drawn_across_a_reboot),
	C(B1_panic_midway), C(B2_panic_full_on_charger), C(B3_reboot_midway), C(B4_brownout_teaches),
	C(B5_forced_off_15), C(B6_new_console), C(B7_stock_values), C(B8_brownout_rest_higher), C(B9_two_brownouts),
	C(B10_uboot_charge_then_key), C(B11_power_on_charging_after_game),
	C(B12_forced_off_15_rested),
	C(B13_uboot_short_charge_key), C(B14_uboot_charge_then_play),
	C(B15_old_uboot_charge_key_level), C(B16_reboot_on_charger_stale_current), C(B17_uboot_wait_short), C(B18_game_then_short_uboot_charge), C(B19_power_off_on_charger_wait_key), C(B20_long_rest_wrong_fcc),
	C(B21_off_on_charger_key_next_morning), C(B22_game_off_40_min),
	C(B23_two_plug_ins_long_gap), C(B24_plug_in_after_long_rest),
	C(B25_counter_set_by_another_system), C(B26_off_on_charger_replugged),
	C(B27_off_on_charger_key_at_once_after_rest), C(B28_counter_set_high_by_another_system),
	C(B29_panic_right_after_kept_ocv), C(B30_game_off_on_charger_short_charge), C(B31_reboot_back_from_another_system), C(B33_panic_low_after_brownout_boot), C(B34_fcc_register_far_off), C(B35_panic_with_the_charger_in), C(B36_off_on_charger_unplugged_long_rest_wrong_fcc),
	C(B42_first_boot_after_0035), C(B43_boot_crosses_a_counter_step), C(B44_forced_off_in_the_wait), C(B45_old_uboot_plug_in_wrong_fcc), C(B46_key_held_then_charger), C(B47_hang_then_key), C(B48_sleep_stuck_then_key), C(B49_stale_counter_mark), C(B50_brownout_charger_key_held_in_wait), C(B51_first_boot_after_0035_full), C(B37_other_system_after_wait_high), C(B38_other_system_after_wait_low), C(B39_panic_asleep_after_brownout_boot),
	C(B40_reboot_back_last_up_on_usb), C(B41_reboot_other_system_draws), C(D23_old_uboot_brownout_two_plug_ins),
	C(D24_old_uboot_brownout_plug_unplug_key), C(D25_cycle_from_0035), C(D26_fcc_far_too_small), C(D27_zero_rest_and_once), C(E15_hibernate_then_sleep),
	C(C1_up_on_charger_reading_negative), C(C5_inhibit_after_charge), C(C6_full_then_game_on_weak_charger), C(C2_no_rise_on_battery), C(C3_step_at_charge_end), C(C4_full_on_weak),
	C(D1_zero_converges), C(D2_zero_with_charger), C(D3_no_bare_app), C(D4_weak_charger_at_zero),
	C(D5_charged_by_uboot_unplugged), C(D6_charged_by_uboot_then_key), C(D7_fcc_a_little_high),
	C(D8_uboot_charge_cycle_goes_on), C(D9_uboot_charge_short_pause_key),
	C(D10_zero_with_charger_next_cycle), C(D11_halfway_shutdown_uboot_charge), C(D12_table_bottom_off),
	C(D13_old_uboot_charge_key), C(D14_old_uboot_off_on_charger), C(D15_brownout_then_charger), C(D16_brownout_charge_unplug_key), C(D17_old_uboot_charged_unplugged), C(D18_brownout_two_plug_ins),
	C(D19_zero_on_charger_replugged), C(D20_brownout_charger_at_once), C(D21_battery_above_design),
	C(D22_nights_off_timer_stops),
	C(E2_sleep_on_battery), C(E9_long_sleep_on_battery), C(E10_cycle_with_sleeps),
	C(E11_rest_puts_the_level_right), C(E12_sleep_after_game), C(E13_rest_at_the_flat_part), C(E14_thaw_no_sleep_fix), C(E3_hibernate_midway), C(E4_short_sleep_full), C(E6_short_sleep_unplugged),
	C(E7_unplugged_replugged_in_sleep), C(E8_unplugged_in_sleep_table_high),
	C(F1_log_once),
};

int main(int argc, char **argv)
{
	int fails = 0;
	info.charge_full_design_uah = 4000000; info.voltage_min_design_uv = 3500000; info.voltage_max_design_uv = 4200000;
	info.factory_internal_resistance_uohm = 165000; info.constant_charge_voltage_max_uv = 4200000;
	info.constant_charge_current_max_ua = 2000000; info.charge_term_current_ua = 200000;
	for (unsigned k = 0; k < ARRAY_SIZE(truth_ocv); k++) { tab[k].ocv = truth_ocv[k][0]; tab[k].capacity = truth_ocv[k][1]; }
	info.ocv_table[0] = tab; info.ocv_table_size[0] = ARRAY_SIZE(tab); info.ocv_temp[0] = 20;
	for (unsigned k = 0; k < ARRAY_SIZE(cells); k++) {
		bool want = argc < 2;
		for (int a = 1; a < argc; a++) if (!strncmp(cells[k].name, argv[a], strlen(argv[a]))) want = true;
		if (!want) continue;
		why[0] = 0; di = NULL;
		bool ok = cells[k].fn();
		if (ok && fcc() < MIN_FCC) { ok = false; snprintf(why, sizeof(why), "FCC %d", fcc()); }
		printf("%s %s%s%s\n", ok ? "PASS" : "FAIL", cells[k].name, ok ? "" : ": ", ok ? "" : why);
		if (!ok && getenv("LOG")) fwrite(logbuf, 1, loglen, stdout);
		fails += !ok;
	}
	return fails ? 1 : 0;
}
