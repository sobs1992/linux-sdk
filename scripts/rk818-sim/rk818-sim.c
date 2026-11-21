/*
 * The RK818 gauge (kernel patch 0035) run on the PC over a logged discharge:
 * the driver's own source with stub kernel headers (include/), its PMIC
 * registers in an array, the coulomb counter integrated from the log's
 * current. A cell of TRUE_CAP is charged full, discharged along the trace
 * (bare_app powers it off at 0% for 10 s, else the trace's end is the
 * brown-out), rests 150 min and boots: the driver's boot-time learning
 * runs on the OCV of the charge left. Built and run by run.sh.
 *
 *   rk818-sim TRACE FCC CYCLES      MID=1: a reboot and 20 min of charge
 *                                   halfway through the discharge;
 *                                   NO_BARE_APP=1: nothing powers it off
 */
#include "kstub.h"
double now_ms; unsigned long jiffies;
#include DRIVER

static unsigned regs[256]; static double cc_raw;	/* the counter, raw */
static unsigned cal[4];
int regmap_read(struct regmap *m, unsigned reg, unsigned *val)
{
	int32_t r = (int32_t)cc_raw;
	switch (reg) {
	case RK818_GASCNT3_REG: *val = ((uint32_t)r >> 24) & 0xff; return 0;
	case RK818_GASCNT2_REG: *val = ((uint32_t)r >> 16) & 0xff; return 0;
	case RK818_GASCNT1_REG: *val = ((uint32_t)r >> 8) & 0xff; return 0;
	case RK818_GASCNT0_REG: *val = (uint32_t)r & 0xff; return 0;
	}
	*val = regs[reg]; return 0;
}
int regmap_write(struct regmap *m, unsigned reg, unsigned val)
{
	switch (reg) {
	case RK818_GASCNT_CAL_REG3: cal[3] = val; return 0;
	case RK818_GASCNT_CAL_REG2: cal[2] = val; return 0;
	case RK818_GASCNT_CAL_REG1: cal[1] = val; return 0;
	case RK818_GASCNT_CAL_REG0: cc_raw = (int32_t)(cal[3] << 24 | cal[2] << 16 | cal[1] << 8 | val); return 0;
	}
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
static struct power_supply_battery_ocv_table tab[] = {
	{4175000,100},{4129770,95},{4095880,90},{4048040,85},{4021150,80},{3971030,75},{3942980,70},{3900010,65},
	{3880530,60},{3865230,55},{3827770,50},{3805240,45},{3778450,40},{3770830,35},{3747940,30},{3744450,25},
	{3742390,20},{3728410,15},{3711170,10},{3696890,5},{3663180,0}};

static struct rk818_battery D, *di = &D; static struct power_supply_battery_info info; static struct power_supply psy;
static void setv(int mv, int ma, bool online, int sts)
{
	regs[RK818_BAT_VOL_REGH] = mv >> 8; regs[RK818_BAT_VOL_REGH + 1] = mv & 0xff;
	int raw = (int)((double)ma * 1000 / (2 * 1506) + (ma < 0 ? -0.5 : 0.5)) & 0xfff;
	regs[RK818_BAT_CUR_AVG_REGH] = raw >> 8; regs[RK818_BAT_CUR_AVG_REGH + 1] = raw & 0xff;
	regs[RK818_VB_MON_REG] = online ? PLUG_IN_STS : 0;
	regs[RK818_SUP_STS_REG] = BAT_EXS | sts;
}
/* the cell: true charge left (mAh) of TRUE_CAP; OCV from the table */
#define TRUE_CAP 4834.0
static double cell_mah;
static int ocv_of(double soc)
{
	int n = ARRAY_SIZE(tab), k;
	if (soc >= 100) return tab[0].ocv / 1000;
	if (soc <= 0) return 3610;
	for (k = 0; k < n - 1; k++)
		if (soc >= tab[k + 1].capacity)
			return (tab[k + 1].ocv + (tab[k].ocv - tab[k + 1].ocv) * (soc - tab[k + 1].capacity) / 5) / 1000;
	return 3610;
}
static void boot(int off_min)
{
	memset(di, 0, sizeof(*di));
	di->info = &info; di->charger_psy = &psy; di->res_div = 2; di->monitor_ms = 5000; di->sense_resist_mohm = 10;
	di->max_soc_offset_pct = 70;
	psy.drv_data = di;
	regs[RK818_NON_ACT_TIMER_CNT_REG] = off_min;
	regs[RK818_NON_ACT_TIMER_CNT_SAVE_REG] = off_min ? 0 : regs[RK818_NON_ACT_TIMER_CNT_REG];
	if (!off_min) regs[RK818_MISC_MARK_REG] |= FG_INIT; else regs[RK818_MISC_MARK_REG] &= ~FG_INIT;
	int ocv = ocv_of(cell_mah / TRUE_CAP * 100);
	regs[RK818_BAT_OCV_REGH] = ocv >> 8; regs[RK818_BAT_OCV_REGH + 1] = ocv & 0xff;
	printf("--- boot after %d min, cell %.0f mAh left, OCV %d\n", off_min, cell_mah, ocv);
	rk818_init_voltage_kb(di);
	rk818_init_soc(di);
	regs[RK818_MISC_MARK_REG] |= FG_INIT;	/* the driver marks it? */
}
/* the charger: until full */
static void charge(void)
{
	while (cell_mah < TRUE_CAP) {
		double ma = 2000; now_ms += 5000;
		cell_mah += ma * 5 / 3600.0; cc_raw += ma * 5 / 3.6e3 * CC_LSB_DENOM / 2;
		setv(4100, (int)ma, 1, RK818_CHG_STS_CC_OR_CV << 0);
		regs[RK818_SUP_STS_REG] = BAT_EXS | RK818_CHG_STS_CC_OR_CV;
		rk818_battery_work(&di->work.work);
	}
	cell_mah = TRUE_CAP;
	for (int k = 0; k < 24; k++) { now_ms += 5000; setv(4150, 0, 1, 0); regs[RK818_SUP_STS_REG] = BAT_EXS | RK818_CHG_STS_TERMINATED; rk818_battery_work(&di->work.work); }
	printf("full: dsoc %d cap %d fcc %d valid %d drawn %d\n", di->dsoc, di->remain_cap_mah, di->fcc_mah, di->learn_valid, di->drawn_mah);
}
static struct { double t; int mv, ma; } tr[20000]; static int ntr;
/* the discharge; bare_app powers off at 0% for 10 s; else the trace's end is the brown-out */
static int discharge(bool bare_app)
{
	int prev = di->dsoc, rises = 0; double zero_since = -1, t0 = now_ms, next = 0, last = tr[0].t;
	for (int k = 0; k < ntr; k++) {
		double dt = tr[k].t - last; last = tr[k].t;
		cell_mah += tr[k].ma * dt / 3.6e6; cc_raw += tr[k].ma * dt / 3.6e6 * CC_LSB_DENOM / 2;
		now_ms = t0 + tr[k].t; setv(tr[k].mv, tr[k].ma, 0, 0);
		if (getenv("MID") && k == ntr / 2) {
			printf("mid: drawn %d, cell %.0f\n", di->drawn_mah, cell_mah);
			rk818_battery_shutdown(&(struct platform_device){ .drvdata = di });
			boot(0);
			for (int j = 0; j < 240; j++) { now_ms += 5000; cell_mah += 1500 * 5 / 3600.0; cc_raw += 1500 * 5 / 3.6e3 * CC_LSB_DENOM / 2;
				setv(3900, 1500, 1, 0); regs[RK818_SUP_STS_REG] = BAT_EXS | RK818_CHG_STS_CC_OR_CV; rk818_battery_work(&di->work.work); }
			printf("after charge: drawn %d dsoc %d, cell %.0f\n", di->drawn_mah, di->dsoc, cell_mah);
			t0 += 240 * 5000;
		}
		if (tr[k].t < next) continue;
		next = tr[k].t + 5000;
		rk818_battery_work(&di->work.work);
		if (di->dsoc > prev) rises++;
		prev = di->dsoc;
		if (di->dsoc == 0) { if (zero_since < 0) zero_since = now_ms; } else zero_since = -1;
		if (bare_app && zero_since >= 0 && now_ms - zero_since >= 10000) {
			printf("bare_app off at 0%%: drawn %d, cell %.0f mAh left (%.1f%%), %.0f s before the brown-out\n",
			       di->drawn_mah, cell_mah, cell_mah / TRUE_CAP * 100, (tr[ntr-1].t - tr[k].t) / 1000);
			rk818_battery_shutdown(&(struct platform_device){ .drvdata = di });
			return rises;
		}
	}
	printf("brown-out: dsoc %d drawn %d, cell %.0f mAh left\n", di->dsoc, di->drawn_mah, cell_mah);
	return rises;
}
int main(int argc, char **argv)
{
	info.charge_full_design_uah = 4000000; info.voltage_min_design_uv = 3500000; info.voltage_max_design_uv = 4200000;
	info.factory_internal_resistance_uohm = 160000; info.constant_charge_voltage_max_uv = 4200000;
	info.ocv_table[0] = tab; info.ocv_table_size[0] = ARRAY_SIZE(tab); info.ocv_temp[0] = 20;
	psy.battery_info = &info;
	regs[RK818_VCALIB0_REGH] = 3000 >> 8; regs[RK818_VCALIB0_REGL] = 3000 & 0xff;
	regs[RK818_VCALIB1_REGH] = 4200 >> 8; regs[RK818_VCALIB1_REGL] = 4200 & 0xff;
	int fcc0 = atoi(argv[2]);
	regs[RK818_NEW_FCC_REG1] = fcc0 >> 8; regs[RK818_NEW_FCC_REG0] = fcc0 & 0xff;
	FILE *f = fopen(argv[1], "r"); int on, st;
	while (ntr < 20000 && fscanf(f, "%lf %d %d %d %d", &tr[ntr].t, &tr[ntr].mv, &tr[ntr].ma, &on, &st) == 5) if (!on) ntr++;
	double t0 = tr[0].t; for (int k = 0; k < ntr; k++) tr[k].t -= t0;
	/* the board's state now: some charge, the old FCC */
	cell_mah = 700; cc_raw = 700.0 * CC_LSB_DENOM / 2; regs[RK818_SOC_REG] = 15;
	boot(0);
	for (int c = 0; c < atoi(argv[3]); c++) {
		printf("===== cycle %d\n", c + 1);
		charge();
		int r = discharge(!getenv("NO_BARE_APP"));
		printf("rises on battery: %d\n", r);
		boot(150);
	}
	return 0;
}
