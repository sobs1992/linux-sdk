/*
 * ddr-calibrate: measure the read eye of every data lane of the G12B DDR
 * PHY (Synopsys LPDDR4) at run time and find the lanes BL2's training
 * leaves off-centre against the others of their nibble (docs/boards/ogu.md,
 * "Память: подстройка задержек чтения").
 *
 *   ddr-calibrate [-w] [-v] [-r] [-p] [-d DBYTES] [-c ms] [-f ms] [-t steps]
 *   ddr-calibrate -s     "unfinished N this|before|running": the nibbles the
 *                        last run did if it did not end; "this": it was
 *                        killed at this start (also "unfinished 0 this":
 *                        before a nibble ended; -R is due while its lock's
 *                        file is there, -r goes on with it after), "before": the
 *                        board went down in it, "running": it goes on now;
 *                        "unfinished 0": nothing
 *   ddr-calibrate -R     after a run that was killed (SIGKILL): the registers
 *                        as they were at its start (only at that same start)
 *                        and /data thawed
 *
 * Memory checkers run on all CPUs (own buffers, random words, read back
 * over and over). For each lane:
 *   early edge  its own read delay (RxPBDly) later, step by step, until the
 *               first wrong word: E steps;
 *   late edge   its own delay earlier until the first wrong word: T steps;
 *               for room below it the nibble is lifted first (its four
 *               delays later, its strobe later by as much, step by step:
 *               each lane samples where it did), see lift();
 * and per nibble the strobe step in RxPBDly steps, R (for the lift): the
 * early edge of one lane again with the strobe a few steps earlier. At the
 * first wrong word every register goes back at once (also on a fatal
 * signal). The lane's centre is S = (E - T) / 2 steps later. In the frame
 * of BL2's values (the line U-Boot applied does not change it) each lane's
 * offset is its centre minus BL2's value; a lane's place is its centre
 * minus the median of its three neighbours' offsets: it samples as the
 * typical neighbour does (the nibble's own position, its strobe, is
 * trained anew at every start, a lane's skew against its neighbours is
 * the same every time). A lane whose place is -t steps (4) or more from
 * what BL2 trained for it makes
 * an entry of the ddr-tune line, "CSR@+N" (and stays there once it is in
 * the line U-Boot read: the line must not depend on the start it was found
 * at): N from the median of what BL2
 * trained for the other three lanes of its nibble (U-Boot 0020 sets it
 * there at every start; BL2 trains a single lane differently now and then,
 * the median of the others stays). BL2's values and U-Boot's lift of this
 * start come from /chosen/ddr-tune and /chosen/ddr-tune-lift; a lane that
 * would go below 0 is U-Boot's to handle (it lifts the nibble). -w keeps
 * the line (ddr-tune set), from the next start on; -r goes on with an
 * interrupted run (the board went down) from its next nibble.
 *
 * A step at an edge reads wrong words; they can hit the kernel. /data is
 * frozen while measuring (a wrong line written back stays in RAM only), the
 * hardware watchdog (if free) resets a hung board. Log: /data/ddr-calibrate.log
 * (one block per run: "== DATE boot ID", a line per nibble, "ddr_tune=..."
 * at its end). A run takes some 8 minutes; no game should run.
 *
 * Every value written to a delay goes through put(): within 0..3f always.
 * A signal (SIGTERM: Stop) puts every register back, thaws /data and ends
 * the run's block ("ddr_tune= (stopped: signal N)"): nothing to go on with.
 * One run at a time: it holds a lock on /run/ddr-calibrate.saved, which
 * keeps the registers' values from its start for -R (a new run at the same
 * start puts them back first, as -R does).
 *
 * Built with -DDDR_SIM it runs against a simulated PHY instead (DDR_SIM_DIR,
 * ../test/sim-test.py): no /dev/mem, no /data, no watchdog.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <linux/watchdog.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define PHY_BASE	0xfe000000UL
#define PHY_SIZE	0x200000UL
#ifdef DDR_SIM
#define PHY_BASE_MAP	0
#else
#define PHY_BASE_MAP	PHY_BASE
#endif
#define CSR_PBD(db, r)	(0x10000u | (db) << 12 | (r) << 8 | 0x68)
#define CSR_CLK(db, u)	(0x10000u | (db) << 12 | (u) << 8 | 0x8c)
#define CSR_LNSEL(db, b) (0x10000u | (db) << 12 | (0xa0 + (b)))
#define VMAX		0x3f

static const char *path_log = "/data/ddr-calibrate.log",
	*path_chosen = "/proc/device-tree/chosen/ddr-tune",
	*path_lift = "/proc/device-tree/chosen/ddr-tune-lift",
	*path_line = "/proc/device-tree/chosen/ddr-tune-line",
	*path_saved = "/run/ddr-calibrate.saved",
	*path_boot = "/proc/sys/kernel/random/boot_id",
	*path_data = "/data",
	*path_wdt = "/dev/watchdog";

#ifdef __aarch64__
#define phy_sync()	__asm__ volatile("dsb sy" ::: "memory")
#else
#define phy_sync()	__sync_synchronize()
#endif

static volatile uint16_t *phy;
#ifndef DDR_SIM
static int data_fd = -1;
#endif
static int wdt_fd = -1, log_fd = -1, saved_fd = -1;
static char boot_id[40];
static atomic_int stop;
static atomic_ullong errbits;	/* XOR bits of the wrong words since the probe began */
static atomic_int nerr;
static int verbose;	/* -v: each edge and lift */

#ifdef DDR_SIM
static char sim_frozen[512];
static atomic_int sim_frozen_writes;	/* writes into /data while it is frozen: they would sleep */
#define DATA_WRITE() (access(sim_frozen, F_OK) == 0 ? (void)atomic_fetch_add(&sim_frozen_writes, 1) : (void)0)
#else
#define DATA_WRITE() ((void)0)
#endif
#ifdef DDR_SIM
static atomic_int sim_bad;	/* values out of 0..3f found in a register after a write */
static int sim_kill_probe;	/* DDR_SIM_KILL_PROBE: SIGKILL in that probe, its registers moved */
static double tscale = 0.05;	/* DDR_SIM_SCALE: waits that much shorter */
#else
#define tscale 1.0
#endif
static atomic_int clamped;	/* values put() had to bring into 0..3f: a bug */

/* The one way a register is written: the value within its field (0..3f) */
static void put(unsigned csr, int v)
{
	if (v < 0 || v > VMAX) {
		atomic_fetch_add(&clamped, 1);
		v = v < 0 ? 0 : VMAX;
	}
	phy[csr] = (uint16_t)v;
#ifdef DDR_SIM
	if (phy[csr] > VMAX)
		atomic_fetch_add(&sim_bad, 1);
#endif
}

/*
 * The probe in flight: the worker that reads the first wrong word puts its
 * registers back itself, at once - the fewer wrong words the rest of the
 * system (kernel, network, the display) reads meanwhile, the better.
 */
static unsigned armed_n, armed_csr[8], armed_back[8];
static atomic_int armed;
static atomic_int in_restore;	/* workers in disarm_restore(): on_sig waits for them */

/* every register this run may touch, with the value it had at the start */
static unsigned saved_csr[48], saved_val[48], nsaved;

#ifdef DDR_SIM
static int sim_sig_in_restore, sim_sig_sent;	/* DDR_SIM_SIG_IN_RESTORE: SIGTERM while a worker restores */

static int sim_moved(unsigned c, unsigned v)	/* v is not the run's start value of c */
{
	for (unsigned i = 0; i < nsaved; i++)
		if (saved_csr[i] == c)
			return saved_val[i] != v;
	return 0;
}
#endif

/*
 * A worker that saw a wrong word: the probe's registers back. Whoever takes
 * armed writes them; on_sig takes it too and then waits until no worker is
 * inside, so no worker writes a probe's value after on_sig put all back.
 */
static void disarm_restore(void)
{
	atomic_fetch_add(&in_restore, 1);
	if (atomic_exchange(&armed, 0)) {
#ifdef DDR_SIM
		if (sim_sig_in_restore && !sim_sig_sent && sim_moved(armed_csr[0], armed_back[0])) {
			sim_sig_sent = 1;
			kill(getpid(), SIGTERM);
			usleep(50000);
		}
#endif
		for (unsigned i = 0; i < armed_n; i++)
			put(armed_csr[i], armed_back[i]);
		phy_sync();
	}
	atomic_fetch_sub(&in_restore, 1);
}

static void save(unsigned csr)
{
	saved_csr[nsaved] = csr;
	saved_val[nsaved++] = phy[csr];
}

static void restore_all(void)
{
	for (unsigned i = 0; i < nsaved; i++)
		put(saved_csr[i], saved_val[i]);
	phy_sync();
}

/* async-signal-safe: on_sig thaws too */
static void thaw(void)
{
#ifdef DDR_SIM
	unlink(sim_frozen);
#else
	if (data_fd < 0)
		data_fd = open(path_data, O_RDONLY | O_CLOEXEC);
	if (data_fd >= 0)
		ioctl(data_fd, FITHAW, 0);
#endif
}

static void freeze(void)
{
#ifdef DDR_SIM
	close(open(sim_frozen, O_WRONLY | O_CREAT | O_CLOEXEC, 0600));
#else
	sync();
	if (data_fd < 0)
		data_fd = open(path_data, O_RDONLY | O_CLOEXEC);
	if (data_fd >= 0 && ioctl(data_fd, FIFREEZE, 0) && errno != EBUSY)
		perror("freeze /data");
#endif
}

static void wdt_close(void)
{
	if (wdt_fd >= 0) {
		if (write(wdt_fd, "V", 1) != 1) { }
		close(wdt_fd);
		wdt_fd = -1;
	}
}

/*
 * A signal: every register back, /data thawed, the run's block in the log
 * ended (a stopped run is not one to go on with), the lock's file gone.
 * The workers block the signals that come from outside, so this runs in
 * the main thread, which then writes no register itself; a worker still
 * putting a probe back is waited for (disarm_restore) before restore_all().
 */
static void on_sig(int s)
{
	char m[48] = "ddr_tune= (stopped: signal ";
	int n = sizeof "ddr_tune= (stopped: signal " - 1;
	struct timespec t0, t;

	/* a worker putting a probe back finishes first; a fault inside
	 * disarm_restore itself (SIGBUS) must not wait for ever: 200 ms */
	atomic_store(&armed, 0);
	clock_gettime(CLOCK_MONOTONIC, &t0);
	while (atomic_load(&in_restore)) {
		clock_gettime(CLOCK_MONOTONIC, &t);
		if ((t.tv_sec - t0.tv_sec) * 1000 + (t.tv_nsec - t0.tv_nsec) / 1000000 > 200)
			break;
		sched_yield();
	}
	restore_all();
#ifdef DDR_SIM
	if (sim_sig_in_restore)
		usleep(100000);	/* as long as an fsync on the eMMC can take */
#endif
	thaw();
	if (log_fd >= 0) {
		if (s >= 10)
			m[n++] = '0' + s / 10 % 10;
		m[n++] = '0' + s % 10;
		m[n++] = ')';
		m[n++] = '\n';
		if (write(log_fd, m, n) < 0) { }
		fsync(log_fd);
	}
	unlink(path_saved);
	wdt_close();
	static const char e[] = "ddr-calibrate: stopped by a signal, registers restored\n";
	if (write(2, e, sizeof e - 1) < 0) { }
	_exit(128 + s);
}

/* the signals from outside, which on_sig handles in the main thread */
static void outside_signals(sigset_t *set)
{
	sigemptyset(set);
	sigaddset(set, SIGINT);
	sigaddset(set, SIGTERM);
	sigaddset(set, SIGHUP);
}

static inline uint64_t mix(uint64_t x)
{
	x ^= x >> 33; x *= 0xff51afd7ed558ccdULL;
	x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL;
	return x ^ (x >> 33);
}

struct worker { int cpu; size_t words; uint64_t *buf; };

#ifndef DDR_SIM
static void *work(void *a)
{
	struct worker *w = a;
	cpu_set_t s;

	CPU_ZERO(&s);
	CPU_SET(w->cpu, &s);
	sched_setaffinity(0, sizeof s, &s);
	/* below the main thread (it puts the registers back) and ssh */
	setpriority(PRIO_PROCESS, syscall(SYS_gettid), 10);
	for (unsigned pass = 0; !atomic_load(&stop); pass++) {
		uint64_t sd = (uint64_t)w->cpu << 56 ^ mix(pass);

		for (size_t i = 0; i < w->words; i++)
			w->buf[i] = mix(i ^ sd);
		for (int r = 0; r < 4 && !atomic_load(&stop); r++)
			for (size_t i = 0; i < w->words; i++) {
				uint64_t e = mix(i ^ sd), g = w->buf[i];

				if (g != e) {
					disarm_restore();
					atomic_fetch_or(&errbits, g ^ e);
					atomic_fetch_add(&nerr, 1);
					w->buf[i] = e;
				}
			}
	}
	return 0;
}
#endif

static double now(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec * 1e-9;
}

static void wdt_ping(void)
{
	static double last;

	if (wdt_fd >= 0 && now() - last > 1) {
		ioctl(wdt_fd, WDIOC_KEEPALIVE, 0);
		last = now();
	}
}

static void idle_ms(int ms)
{
	double end = now() + ms * tscale / 1000.0;

	while (now() < end) {
		wdt_ping();
		usleep(10000);
	}
}

/* lanes: index db*8+r; the CPU bits each one carries (bit b of byte db and db+4) */
static int lnsel[4][8];

static uint32_t lanes_of(uint64_t bits)
{
	uint32_t l = 0;

	for (int bit = 0; bit < 64; bit++)
		if (bits >> bit & 1) {
			int db = bit / 8 % 4, b = bit % 8;

			l |= 1u << (db * 8 + lnsel[db][b]);
		}
	return l;
}

static int cpu_bit(int db, int r)	/* the odd-beat bit of lane r, as memcheck logs show it */
{
	for (int b = 0; b < 8; b++)
		if (lnsel[db][b] == r)
			return 32 + db * 8 + b;
	return -1;
}

#ifdef DDR_SIM
/*
 * The simulated lanes: lane (db, r) samples at x = its delay - R * its
 * nibble's strobe and reads wrong outside [lo, hi] (DDR_SIM_DIR/spec:
 * "R 2.5", "eye DB R LO HI"); wrong words carry the lane's odd-beat bit.
 */
static double sim_R = 2.5, sim_lo[4][8], sim_hi[4][8] = { { 0 } };

static void *work(void *a)
{
	(void)a;
	while (!atomic_load(&stop)) {
		uint64_t bits = 0;

		for (int db = 0; db < 4; db++)
			for (int r = 0; r < 8; r++) {
				double x = phy[CSR_PBD(db, r)] - sim_R * phy[CSR_CLK(db, r / 4)];
				int b = cpu_bit(db, r);

				if ((x > sim_hi[db][r] || x < sim_lo[db][r]) && b >= 0)
					bits |= 1ull << b;
			}
		if (bits) {
			disarm_restore();
			atomic_fetch_or(&errbits, bits);
			atomic_fetch_add(&nerr, 1);
		}
		usleep(100);
	}
	return 0;
}

static int sim_probes;
#endif

/*
 * Set n registers to val[] for up to ms; back to back[] at once at the first
 * wrong word. Returns the lanes that read wrong (0: none).
 */
static uint32_t probe(int n, const unsigned *csr, const unsigned *val, const unsigned *back, int ms)
{
	atomic_store(&errbits, 0);
	int before = atomic_load(&nerr);

	armed_n = n;
	for (int i = 0; i < n; i++) {
		armed_csr[i] = csr[i];
		armed_back[i] = back[i];
	}
	atomic_store(&armed, 1);
	for (int i = 0; i < n; i++)
		put(csr[i], val[i]);
	phy_sync();
#ifdef DDR_SIM
	if (sim_kill_probe && ++sim_probes == sim_kill_probe)
		kill(getpid(), SIGKILL);
#endif
	double end = now() + ms * tscale / 1000.0;
	int bad = 0;

	while (now() < end) {
		if (atomic_load(&nerr) != before) {
			bad = 1;
			break;
		}
		wdt_ping();
		usleep(200);
	}
	atomic_store(&armed, 0);
	for (int i = 0; i < n; i++)
		put(csr[i], back[i]);
	phy_sync();
	if (!bad)
		return 0;
	idle_ms(300);	/* the wrong words counted, the workers past them */
	if (verbose)
		printf("  %05x=%02x: wrong bits %016llx\n", csr[0], val[0], (unsigned long long)atomic_load(&errbits));
	return lanes_of(atomic_load(&errbits)) | 0x80000000u;
}

static int coarse_ms = 150, fine_ms = 1000;

/*
 * Edges are found one step at a time, never more: one step past an edge
 * reads a word wrong now and then, three or four steps past it nearly every
 * word of the lane, and before the registers go back such a burst can reach
 * the kernel. That rules out the strobe for it: one strobe step is two or
 * three delay steps. A pass with short waits (coarse_ms) stops at the first
 * wrong word; the two steps before it are tried again with long waits
 * (fine_ms), the edge being the first that reads wrong. dir: +1 the delay
 * later (towards the early edge), -1 earlier (the late edge).
 */
static int edge(unsigned c, unsigned base, int dir, uint32_t lane, int *cens)
{
	unsigned v;
	int k;

	*cens = 2;
	for (k = 1; dir > 0 ? base + k <= VMAX : (int)base - k >= 0; k++) {
		v = base + dir * k;
		uint32_t l = probe(1, &c, &v, &base, coarse_ms);

		if (l) {
			*cens = l & lane ? 0 : 1;
			break;
		}
	}
	if (*cens == 2)
		return dir > 0 ? VMAX - (int)base + 1 : (int)base + 1;
	for (int kk = k - 2 > 0 ? k - 2 : 1; kk < k; kk++) {
		v = base + dir * kk;
		uint32_t l = probe(1, &c, &v, &base, fine_ms);

		if (l) {
			*cens = l & lane ? 0 : 1;
			return kk;
		}
	}
	return k;
}

/* the edge of lane (db, r) its own delay reaches moving dir: steps to the first wrong word */
static int lane_edge(int db, int r, int dir, int *cens)
{
	unsigned c = CSR_PBD(db, r);
	int k = edge(c, phy[c], dir, 1u << (db * 8 + r), cens);

	if (*cens == 1)	/* another lane read wrong: moving this one should not do that */
		*cens = 0;
	return k;
}

static int early_edge(int db, int r, int *cens)
{
	return lane_edge(db, r, +1, cens);
}

/*
 * The late edge needs room below a lane's delay, which is often 0. The
 * nibble is lifted first, s times: its four delays later by R's share of a
 * strobe step (towards the early edges, far off), then its strobe one step
 * later (back): every lane samples where it did, give or take R's error
 * (the same for the four, so it drops out of a lane against its nibble).
 * Lowered the other way round: the strobe first. A wrong word on the way:
 * -1, back where it began.
 */
static int lift_step(double R, int j)
{
	return (int)(R * j + 0.5) - (int)(R * (j - 1) + 0.5);
}

static int lift(int db, int u, double R, int s, int up)
{
	unsigned cc = CSR_CLK(db, u);
	int done = 0, bad = 0;

	for (int j = 1; j <= s && !bad; j++, done++) {
		int jj = up ? j : s - j + 1, inc = lift_step(R, jj), before = atomic_load(&nerr);

		if (!up)
			put(cc, phy[cc] - 1);
		for (int i = 0; i < 4; i++)
			put(CSR_PBD(db, 4 * u + i), phy[CSR_PBD(db, 4 * u + i)] + (up ? inc : -inc));
		if (up)
			put(cc, phy[cc] + 1);
		phy_sync();
		idle_ms(30);
		bad = atomic_load(&nerr) != before;
	}
	if (!bad)
		return 0;
	/* undo what was done, strobe first going down */
	for (int j = done; j >= 1; j--) {
		int jj = up ? j : s - j + 1, inc = lift_step(R, jj);

		if (up)
			put(cc, phy[cc] - 1);
		for (int i = 0; i < 4; i++)
			put(CSR_PBD(db, 4 * u + i), phy[CSR_PBD(db, 4 * u + i)] + (up ? -inc : inc));
		if (!up)
			put(cc, phy[cc] + 1);
		phy_sync();
	}
	idle_ms(300);
	return -1;
}

/* BL2's value of a register: /chosen/ddr-tune "CSR:trained>now ..." if U-Boot moved it */
static unsigned trained(unsigned csr)
{
	static char buf[1024];	/* 44 CSRs (36 delays, 8 strobes) of "CSR:was>now " */
	static int read_once;
	char key[8];

	if (!read_once) {
		FILE *f = fopen(path_chosen, "r");

		if (f) {
			size_t n = fread(buf, 1, sizeof buf - 1, f);

			buf[n] = 0;
			fclose(f);
		}
		read_once = 1;
	}
	snprintf(key, sizeof key, "%05x:", csr);
	char *p = strstr(buf, key);

	return p ? strtoul(p + 6, 0, 16) : phy[csr];
}

static double med3d(double a, double b, double c)
{
	if (a > b) {
		double t = a;

		a = b;
		b = t;
	}
	return c < a ? a : c > b ? b : c;
}

static int med3(int a, int b, int c)
{
	if (a > b) {
		int t = a;

		a = b;
		b = t;
	}
	return c < a ? a : c > b ? b : c;
}

/* the line U-Boot read at this start (/chosen/ddr-tune-line), "" none */
static const char *line_read(void)
{
	static char buf[600];
	static int read_once;

	if (!read_once) {
		FILE *f = fopen(path_line, "r");

		if (f) {
			size_t n = fread(buf, 1, sizeof buf - 1, f);

			buf[n] = 0;
			fclose(f);
		}
		read_once = 1;
	}
	return buf;
}

/* csr has a "CSR@+N" in the line U-Boot read at this start */
static int read_at(unsigned csr)
{
	const char *buf = line_read(), *p;
	char key[8];

	snprintf(key, sizeof key, "%05x@", csr);
	for (p = buf; (p = strstr(p, key)); p++)
		if (p == buf || p[-1] == ' ')
			return 1;
	return 0;
}

/* U-Boot's lift of nibble (db, u) at this start: /chosen/ddr-tune-lift "1<db><u>8c+L ..." */
static int uboot_lift(int db, int u)
{
	static char buf[128];
	static int read_once;
	char key[8];

	if (!read_once) {
		FILE *f = fopen(path_lift, "r");

		if (f) {
			size_t n = fread(buf, 1, sizeof buf - 1, f);

			buf[n] = 0;
			fclose(f);
		}
		read_once = 1;
	}
	snprintf(key, sizeof key, "%05x+", CSR_CLK(db, u));
	char *p = strstr(buf, key);

	return p ? (int)strtoul(p + 6, 0, 16) : 0;
}

/*
 * The last run in the log, if it did not end (the board went down, or it
 * was killed): its nibbles done[][], their "keep:" parts of the line
 * appended to line, the boot ID of its last part into boot. Returns the
 * nibbles done, 0: nothing to go on with. -r goes on with it;
 * a lane against its nibble does not depend on the start, so nibbles of
 * runs from different starts add up.
 */
static int unfinished(int done[4][2], char *line, size_t size, int *nline, int say, char *boot, size_t bsize)
{
	FILE *f = fopen(path_log, "r");
	char l[512], blk[16][512];
	int nb = 0, open = 0, n = 0;

	if (boot)
		boot[0] = 0;
	while (f && fgets(l, sizeof l, f)) {
		char *b = strstr(l, " boot ");

		if (boot && (!strncmp(l, "== ", 3) || !strncmp(l, "-- resumed ", 11)))
			snprintf(boot, bsize, "%.*s", b ? (int)strcspn(b + 6, " \n") : 0, b ? b + 6 : "");
		if (!strncmp(l, "== ", 3)) {
			nb = 0;
			open = 1;
		} else if (!strncmp(l, "ddr_tune=", 9)) {
			open = 0;
		} else if (open && !strncmp(l, "dbyte ", 6) && nb < 16) {
			snprintf(blk[nb++], sizeof blk[0], "%s", l);
		}
	}
	if (f)
		fclose(f);
	if (!open)
		return 0;
	for (int i = 0; i < nb; i++) {
		int db, u;
		char *k = strstr(blk[i], " keep:");

		if (sscanf(blk[i], "dbyte %d nibble %d:", &db, &u) != 2 || db < 0 || db > 3 || u < 0 || u > 1 ||
		    done[db][u])
			continue;
		done[db][u] = 1;
		n++;
		for (char *t = k ? strtok(k + 6, " \n") : NULL; t && line; t = strtok(NULL, " \n"))
			*nline += snprintf(line + *nline, size - *nline, "%s%s", *nline ? " " : "", t);
		if (say)
			printf("dbyte %d nibble %d: done before (%s)\n", db, u, k ? k + 1 : "keep: nothing");
	}
	return n;
}

/* -p: "progress PERCENT" of the whole run (nibbles done, the part of this one) */
static int progress, nib_done, nib_total;

static void say_progress(int part)
{
	if (progress && nib_total)
		printf("progress %d\n", (nib_done * 100 + part) / nib_total);
}

static void read_boot_id(void)
{
	FILE *f = fopen(path_boot, "r");

	boot_id[0] = 0;
	if (f) {
		if (fgets(boot_id, sizeof boot_id, f))
			boot_id[strcspn(boot_id, "\n")] = 0;
		fclose(f);
	}
}

static int map_phy(void)
{
#ifdef DDR_SIM
	char path[512];
	int fd;

	snprintf(path, sizeof path, "%s/phy", getenv("DDR_SIM_DIR"));
	fd = open(path, O_RDWR | O_CLOEXEC);
#else
	int fd = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
#endif
	if (fd < 0) { perror("/dev/mem"); return -1; }
	phy = mmap(0, PHY_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, PHY_BASE_MAP);
	if (phy == MAP_FAILED) { perror("mmap"); return -1; }
	if (phy[0xd0000] != 0) {
		fprintf(stderr, "ddr-calibrate: the PHY's registers are not open to the CPU (MicroContMuxSel)\n");
		return -1;
	}
	return 0;
}

/* A register a run may touch: a DBYTE's RxPBDly (lanes 0-8) or RxClkDly (nibbles 0-1) */
static int csr_ours(unsigned c)
{
	unsigned db = c >> 12 & 15, r = c >> 8 & 15, reg = c & 0xff;

	return c >> 16 == 1 && db <= 3 && ((reg == 0x68 && r <= 8) || (reg == 0x8c && r <= 1));
}

/* The lock of the one run: 0 taken, -1 another run holds it, -2 no file */
static int take_lock(void)
{
	for (int tries = 0; tries < 10; tries++) {
		struct stat a, b;

		saved_fd = open(path_saved, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
		if (saved_fd < 0)
			return -2;
		if (flock(saved_fd, LOCK_EX | LOCK_NB)) {
			close(saved_fd);
			saved_fd = -1;
			return -1;
		}
		/* the run before unlinked it between our open and flock: again */
		if (!fstat(saved_fd, &a) && !stat(path_saved, &b) && a.st_ino == b.st_ino && a.st_dev == b.st_dev)
			return 0;
		close(saved_fd);
	}
	saved_fd = -1;
	return -1;
}

/* the registers' values at the run's start into the lock's file, for -R */
static void write_saved(void)
{
	char b[64 + 48 * 12];
	int n = snprintf(b, sizeof b, "boot %s\n", boot_id);

	for (unsigned i = 0; i < nsaved; i++)
		n += snprintf(b + n, sizeof b - n, "%05x %04x\n", saved_csr[i], saved_val[i]);
	if (ftruncate(saved_fd, 0) || pwrite(saved_fd, b, n, 0) != n)
		perror(path_saved);
}

/*
 * The lock's file a killed run left (fd, locked): its registers into
 * csr[]/val[] in the order saved (the strobes first). Returns how many,
 * 0 nothing in it, -1 saved at another start (BL2 trained anew since).
 */
static int read_saved(int fd, unsigned *csr, unsigned *val, int max)
{
	char b[64 + 48 * 12 + 1], boot[40] = "", *l, *save = NULL;
	ssize_t len = pread(fd, b, sizeof b - 1, 0);
	int n = 0;

	if (len <= 0)
		return 0;
	b[len] = 0;
	l = strtok_r(b, "\n", &save);
	if (!l || strncmp(l, "boot ", 5))
		return 0;
	snprintf(boot, sizeof boot, "%s", l + 5);
	if (!boot_id[0] || strcmp(boot, boot_id))
		return -1;
	while ((l = strtok_r(NULL, "\n", &save)) && n < max)
		if (sscanf(l, "%x %x", &csr[n], &val[n]) == 2 && csr_ours(csr[n]) && val[n] <= VMAX)
			n++;
	return n;
}

static void write_all(int n, const unsigned *csr, const unsigned *val)
{
	for (int i = 0; i < n; i++)
		put(csr[i], val[i]);
	phy_sync();
}

/* -R: a killed run's registers back (saved at this start only), /data thawed */
static int restore_saved(void)
{
	int fd = open(path_saved, O_RDWR | O_CLOEXEC), n;
	unsigned csr[48], val[48];

	if (fd < 0) {
		thaw();
		printf("nothing to restore\n");
		return 0;
	}
	if (flock(fd, LOCK_EX | LOCK_NB)) {
		fprintf(stderr, "ddr-calibrate: a run goes on: not restored\n");
		close(fd);
		return 1;
	}
	n = read_saved(fd, csr, val, 48);
	if (n < 0) {
		printf("saved at another start: not restored\n");
	} else if (n == 0) {
		printf("nothing to restore\n");
	} else if (map_phy() == 0) {
		write_all(n, csr, val);
		printf("restored %d registers\n", n);
	} else {
		thaw();
		close(fd);
		return 1;
	}
	unlink(path_saved);
	thaw();
	close(fd);
	return 0;
}

#ifdef DDR_SIM
/* DDR_SIM_DIR: phy (the registers), spec, boot_id, ddr-calibrate.log, chosen, chosen-lift, chosen-line, run/, data/ */
static char sim_paths[7][512];

static int sim_setup(void)
{
	const char *d = getenv("DDR_SIM_DIR"), *k = getenv("DDR_SIM_KILL_PROBE"), *sc = getenv("DDR_SIM_SCALE");
	char spec[512], l[128];
	struct stat st;
	FILE *f;

	if (!d || !*d || stat(d, &st) || !S_ISDIR(st.st_mode)) {
		fprintf(stderr, "ddr-calibrate (sim): DDR_SIM_DIR is not a directory\n");
		return -1;
	}
	snprintf(sim_paths[0], 512, "%s/ddr-calibrate.log", d);
	snprintf(sim_paths[1], 512, "%s/chosen", d);
	snprintf(sim_paths[2], 512, "%s/run/ddr-calibrate.saved", d);
	snprintf(sim_paths[3], 512, "%s/boot_id", d);
	snprintf(sim_paths[4], 512, "%s/data", d);
	snprintf(sim_paths[5], 512, "%s/chosen-lift", d);
	snprintf(sim_frozen, sizeof sim_frozen, "%s/frozen", d);
	path_log = sim_paths[0];
	path_chosen = sim_paths[1];
	path_saved = sim_paths[2];
	path_boot = sim_paths[3];
	path_data = sim_paths[4];
	path_lift = sim_paths[5];
	snprintf(sim_paths[6], 512, "%s/chosen-line", d);
	path_line = sim_paths[6];
	path_wdt = "";
	sim_kill_probe = k ? atoi(k) : 0;
	sim_sig_in_restore = getenv("DDR_SIM_SIG_IN_RESTORE") != NULL;
	if (sc && *sc)
		tscale = atof(sc);
	snprintf(spec, sizeof spec, "%s/spec", d);
	if (!(f = fopen(spec, "r"))) {
		perror(spec);
		return -1;
	}
	for (int db = 0; db < 4; db++)
		for (int r = 0; r < 8; r++)
			sim_lo[db][r] = -1e9, sim_hi[db][r] = 1e9;
	while (fgets(l, sizeof l, f)) {
		int db, r;
		double lo, hi;

		if (sscanf(l, "R %lf", &lo) == 1)
			sim_R = lo;
		else if (sscanf(l, "eye %d %d %lf %lf", &db, &r, &lo, &hi) == 4 && db >= 0 && db < 4 && r >= 0 && r < 8)
			sim_lo[db][r] = lo, sim_hi[db][r] = hi;
	}
	fclose(f);
	return 0;
}
#endif

/* "== DATE boot ID" (a new run) or "-- resumed DATE boot ID" into the log */
static void log_begin(int resume, time_t t0)
{
	char b[128];
	int n = snprintf(b, sizeof b, "%s %.24s boot %s\n", resume ? "-- resumed" : "==", ctime(&t0),
			 boot_id[0] ? boot_id : "?");
	sigset_t set, old;

	/* no signal before the header: on_sig would end the block before it */
	outside_signals(&set);
	pthread_sigmask(SIG_BLOCK, &set, &old);
	DATA_WRITE();
	log_fd = open(path_log, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0644);
	if (log_fd >= 0 && (write(log_fd, b, n) != n || fsync(log_fd)))
		perror(path_log);
	pthread_sigmask(SIG_SETMASK, &old, NULL);
}

/* the run's block ended; no signal in between: on_sig would end it twice */
static void log_end(const char *line, long secs)
{
	sigset_t set, old;
	char b[640];
	int n = snprintf(b, sizeof b, "ddr_tune=%s (%ld s)\n", line, secs);

	outside_signals(&set);
	pthread_sigmask(SIG_BLOCK, &set, &old);
	if (log_fd >= 0) {
		DATA_WRITE();
		if (write(log_fd, b, n) != n)
			perror(path_log);
		fsync(log_fd);
		close(log_fd);
		log_fd = -1;
	}
	pthread_sigmask(SIG_SETMASK, &old, NULL);
}

int main(int argc, char **argv)
{
	int writeit = 0, thresh = 4, o, mb = 24, resume = 0, status = 0, restore = 0, done[4][2] = { { 0 } };
	char dbytes[8] = "0123";

	while ((o = getopt(argc, argv, "wvrpsRd:c:f:t:m:")) != -1)
		switch (o) {
		case 'w': writeit = 1; break;
		case 'v': verbose = 1; break;
		case 'r': resume = 1; break;
		case 'p': progress = 1; break;
		case 's': status = 1; break;
		case 'R': restore = 1; break;
		case 'd': snprintf(dbytes, sizeof dbytes, "%s", optarg); break;
		case 'c': coarse_ms = atoi(optarg); break;
		case 'f': fine_ms = atoi(optarg); break;
		case 't': thresh = atoi(optarg); break;
		case 'm': mb = atoi(optarg); break;
		default:
			fprintf(stderr, "usage: ddr-calibrate [-w] [-v] [-r] [-p] [-d DBYTES] [-c ms] [-f ms] [-t steps] [-m MB]\n"
					"       ddr-calibrate -s | -R\n");
			return 2;
		}
#ifdef DDR_SIM
	if (sim_setup())
		return 2;
	if (writeit) {
		fprintf(stderr, "ddr-calibrate (sim): no -w\n");
		return 2;
	}
#endif
	read_boot_id();

	if (status) {
		char ub[40];
		int n = unfinished(done, NULL, 0, &o, 0, ub, sizeof ub), fd = open(path_saved, O_RDWR | O_CLOEXEC);
		int running = fd >= 0 && flock(fd, LOCK_EX | LOCK_NB);
		unsigned c[48], v[48];
		/* its lock's file left at this start: killed, maybe before a nibble ended */
		int killed = fd >= 0 && !running && read_saved(fd, c, v, 48) > 0;

		if (fd >= 0)
			close(fd);
		if (running)
			printf("unfinished %d running\n", n);
		else if (killed)
			printf("unfinished %d this\n", n);
		else if (n)
			printf("unfinished %d %s\n", n, boot_id[0] && !strcmp(ub, boot_id) ? "this" : "before");
		else
			printf("unfinished 0\n");
		return 0;
	}
	if (restore)
		return restore_saved();

	switch (take_lock()) {
	case -1:
		fprintf(stderr, "ddr-calibrate: another run goes on\n");
		if (progress)
			printf("fail busy\n");
		return 1;
	case -2:
		perror(path_saved);
		return 1;
	}
	if (map_phy())
		return 1;
	/* a run killed at this start may have left /data frozen: every write
	 * there (the log) would sleep for good; the lock says no run freezes it */
	thaw();
	{
		/* a run killed at this start left its registers moved: back first */
		unsigned csr[48], val[48];
		int n = read_saved(saved_fd, csr, val, 48);

		if (n > 0) {
			write_all(n, csr, val);
			fprintf(stderr, "ddr-calibrate: %d registers of a killed run restored first\n", n);
		}
	}
	for (int db = 0; db < 4; db++)
		for (int b = 0; b < 8; b++)
			lnsel[db][b] = phy[CSR_LNSEL(db, b)] & 7;
	/* strobes first: put back in this order, a lifted nibble comes down by its early side */
	for (int db = 0; db < 4; db++) {
		save(CSR_CLK(db, 0));
		save(CSR_CLK(db, 1));
	}
	for (int db = 0; db < 4; db++)
		for (int r = 0; r < 8; r++)
			save(CSR_PBD(db, r));
	write_saved();
	static const int sigs[] = { SIGINT, SIGTERM, SIGHUP, SIGABRT, SIGSEGV, SIGBUS, SIGILL };

	for (unsigned i = 0; i < sizeof sigs / sizeof sigs[0]; i++)
		signal(sigs[i], on_sig);
	signal(SIGPIPE, SIG_IGN);
	setvbuf(stdout, 0, _IOLBF, 0);

	if (*path_wdt)
		wdt_fd = open(path_wdt, O_WRONLY | O_CLOEXEC);
	if (wdt_fd >= 0) {
		int t = 30;

		ioctl(wdt_fd, WDIOC_SETTIMEOUT, &t);
	}

	struct worker ws[8];
	pthread_t th[8];
	int nw = 0;
#ifdef DDR_SIM
	nw = 1;
	(void)ws;
	(void)mb;
#else
	long ncpu = sysconf(_SC_NPROCESSORS_ONLN);

	for (int c = 0; c < ncpu && nw < 8; c++, nw++) {
		ws[nw].cpu = c;
		ws[nw].words = (size_t)mb << 17;
		ws[nw].buf = mmap(0, (size_t)mb << 20, PROT_READ | PROT_WRITE,
				  MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
		if (ws[nw].buf == MAP_FAILED) {
			perror("mmap");
			unlink(path_saved);	/* nothing was moved: no run to restore */
			return 1;
		}
		mlock(ws[nw].buf, (size_t)mb << 20);
	}
#endif

	FILE *lg = NULL;
	time_t t0 = time(0);
	char line[512] = "";
	int nline = 0;

	if (resume && !unfinished(done, line, sizeof line, &nline, 1, NULL, 0))
		resume = 0;
	log_begin(resume, t0);
	freeze();
	{
		/* the workers never take the signals from outside: on_sig runs in this thread */
		sigset_t set, old;

		outside_signals(&set);
		pthread_sigmask(SIG_BLOCK, &set, &old);
		for (int i = 0; i < nw; i++)
#ifdef DDR_SIM
			pthread_create(&th[i], 0, work, NULL);
#else
			pthread_create(&th[i], 0, work, &ws[i]);
#endif
		pthread_sigmask(SIG_SETMASK, &old, NULL);
	}
	idle_ms(1000);
	if (atomic_load(&nerr)) {
		fprintf(stderr, "ddr-calibrate: wrong words at the trained values: stopping\n");
		if (progress)
			printf("fail trained\n");
		goto out;
	}
	for (const char *dp = dbytes; *dp; dp++)
		if (*dp >= '0' && *dp <= '3')
			for (int u = 0; u < 2; u++)
				nib_total++, nib_done += done[*dp - '0'][u];
	say_progress(0);
	printf("lane  bit  now  early  late  S    vs nibble\n");
	for (const char *dp = dbytes; *dp; dp++) {
		int db = *dp - '0';

		if (db < 0 || db > 3)
			continue;
		for (int u = 0; u < 2; u++) {
			if (done[db][u])
				continue;
			int E[4], T[4], ce[4], ct[4], nline0 = nline, want[4], okv[4];
			unsigned bl2v[4];
			double S[4], R = 2.5;
			char rnote[64] = "";

			for (int i = 0; i < 4; i++) {
				E[i] = early_edge(db, 4 * u + i, &ce[i]);
				say_progress(10 * (i + 1));
			}

			/* strobe step in delay steps: the lane with the most early margin, strobe d earlier */
			unsigned cc = CSR_CLK(db, u), cb = phy[cc];
			int x = 0, d = cb >= 4 ? 4 : cb, emin = VMAX;

			/* the strobe d earlier moves every lane ~2d steps towards its early edge: keep 6 clear */
			for (int i = 0; i < 4; i++)
				if (E[i] < emin)
					emin = E[i];
			while (d > 0 && 3 * d > emin - 6)
				d--;
			for (int i = 1; i < 4; i++)
				if (!ce[i] && (ce[x] || E[i] > E[x]))
					x = i;
			if (d >= 2 && !ce[x]) {
				int c2;

				put(cc, cb - d);
				phy_sync();
				int E2 = early_edge(db, 4 * u + x, &c2);

				put(cc, cb);
				phy_sync();
				double r = (double)(E[x] - E2) / d;

				if (!c2 && r >= 1 && r <= 4)
					R = r;
				else
					snprintf(rnote, sizeof rnote, " (R measured %.1f: 2.5 taken)", r);
			} else {
				snprintf(rnote, sizeof rnote, " (R not measured: 2.5 taken)");
			}

			/*
			 * lift the nibble as far as the highest delay and the strobe
			 * allow (16 strobe steps at most)
			 */
			int maxb = 0, lifted = 0;

			for (int i = 0; i < 4; i++)
				if (phy[CSR_PBD(db, 4 * u + i)] > (unsigned)maxb)
					maxb = phy[CSR_PBD(db, 4 * u + i)];
			int sl = (int)((VMAX - maxb) / (R + 0.5));

			if (sl > VMAX - (int)phy[cc])
				sl = VMAX - (int)phy[cc];
			for (sl = sl > 16 ? 16 : sl; sl >= 2; sl -= 3) {
				if (lift(db, u, R, sl, 1) == 0) {
					lifted = sl;
					break;
				}
				if (verbose)
					printf("  lift by %d read wrong: less\n", sl);
			}
			say_progress(50);
			for (int i = 0; i < 4; i++) {
				T[i] = lane_edge(db, 4 * u + i, -1, &ct[i]);
				say_progress(50 + 12 * (i + 1));
			}
			if (lifted && lift(db, u, R, lifted, 0)) {
				fprintf(stderr, "ddr-calibrate: lowering dbyte %d nibble %d read wrong: stopping\n", db, u);
				if (progress)
					printf("fail lowering\n");
				goto out;
			}
			snprintf(rnote + strlen(rnote), sizeof rnote - strlen(rnote), ", lifted %d", lifted);

			int n = 0;

			for (int i = 0; i < 4; i++) {
				S[i] = (E[i] - T[i]) / 2.0;
				n += !ce[i] && !ct[i];
			}

			char nib[256];
			int nl = snprintf(nib, sizeof nib, "dbyte %d nibble %d: strobe %02x, R %.2f%s;", db, u,
					  phy[CSR_CLK(db, u)], R, rnote);

			/*
			 * In the frame of BL2's values (without U-Boot's lift of this
			 * start: /chosen/ddr-tune-lift), which the line applied does not
			 * change: a lane's centre C = now - lift + S, its offset from
			 * BL2's value C - BL2. A lane's place = its centre minus the
			 * median of its three neighbours' offsets (the lane itself not
			 * counted): every lane sampling as the typical neighbour does.
			 * Half a step from BL2's value rounds towards it.
			 */
			int lift = uboot_lift(db, u);
			double C[4], off[4];

			for (int i = 0; i < 4; i++) {
				unsigned c = CSR_PBD(db, 4 * u + i);

				bl2v[i] = trained(c);
				C[i] = (int)phy[c] - lift + S[i];
				off[i] = C[i] - (int)bl2v[i];
			}
			for (int i = 0; i < 4; i++) {
				int r = 4 * u + i;
				unsigned c = CSR_PBD(db, r), cur = phy[c];
				double On[3], pr, rel, d;
				int k = 0, di, reli, ok;

				for (int j = 1; j < 4; j++)
					if (!ce[(i + j) % 4] && !ct[(i + j) % 4])
						On[k++] = off[(i + j) % 4];
				ok = !ce[i] && !ct[i] && n >= 3 && k > 0;
				pr = C[i] - (k == 3 ? med3d(On[0], On[1], On[2]) : k == 2 ? (On[0] + On[1]) / 2 : k ? On[0] : 0);
				d = pr - (int)bl2v[i];
				di = (int)d;	/* towards 0, then more than half a step away */
				di += d - di > 0.5 ? 1 : d - di < -0.5 ? -1 : 0;
				rel = pr - ((int)cur - lift);	/* how far it is from its place now */
				reli = (int)rel;
				reli += rel - reli > 0.5 ? 1 : rel - reli < -0.5 ? -1 : 0;

				printf("%d.%d   %2d   %02x   %2d%s   %2d%s  %5.1f  %+5.1f%s\n", db, r, cpu_bit(db, r), cur,
				       E[i], ce[i] ? "+" : " ", T[i], ct[i] ? "+" : " ", S[i], ok ? rel : 0.0,
				       ok ? (abs(di) >= thresh ? "  <-" : "") : "  (edge not reached)");
				nl += snprintf(nib + nl, sizeof nib - nl, " r%d E%d%s T%d%s %+d", r, E[i], ce[i] ? "+" : "",
					       T[i], ct[i] ? "+" : "", ok ? reli : 0);
				/* not measured: where it stands */
				want[i] = ok ? (int)bl2v[i] + di : (int)cur - lift;
				okv[i] = ok;
			}
			/*
			 * The line: a lane whose place is thresh or more from BL2's value
			 * is kept as "CSR@+N", N from the median of what BL2 trained for
			 * the other three lanes of the nibble (U-Boot 0020 sets it there
			 * at every start); so is one already in the line U-Boot read, and
			 * one not measured that does not stand at BL2's value.
			 */
			int nk = 0;
			char kept_note[96] = "";

			for (int i = 0; i < 4; i++) {
				unsigned c = CSR_PBD(db, 4 * u + i);
				int place = want[i], o, keepit;
				/*
				 * Once in the line, a lane stays: the line found must not
				 * depend on the start it was found at (calibrated where BL2
				 * trained the lane where it belongs, it would drop out and
				 * miss the next start BL2 does not). Not measured: where it
				 * is now (U-Boot put it there, or BL2 did).
				 */
				int had = read_at(c);

				keepit = (okv[i] ? abs(place - (int)bl2v[i]) >= thresh : place != (int)bl2v[i]) || had;
				if (!keepit)
					continue;
				o = place - med3(bl2v[(i + 1) % 4], bl2v[(i + 2) % 4], bl2v[(i + 3) % 4]);
				o = o < -VMAX ? -VMAX : o > VMAX ? VMAX : o;	/* a guard: values are 0..3f */
				nline += snprintf(line + nline, sizeof line - nline, "%s%05x@%c%x",
						  nline ? " " : "", c, o < 0 ? '-' : '+', abs(o));
				nk += snprintf(kept_note + nk, sizeof kept_note - nk, " r%d@%+d", 4 * u + i, o);
			}
			if (nk)
				printf("dbyte %d nibble %d: kept%s\n", db, u, kept_note);
			/* the nibble's result on disk before the next one */
			thaw();
			DATA_WRITE();
			lg = fopen(path_log, "a");
			if (lg) {
				fprintf(lg, "%s keep:%s%s\n", nib, nline > nline0 && nline0 ? "" : " ", line + nline0);
				fflush(lg);
				fsync(fileno(lg));
				fclose(lg);
			}
			freeze();
			nib_done++;
			say_progress(0);
		}
	}

	{
		/* -d: the entries of the DBYTEs not calibrated stay as U-Boot read them */
		char tmp[600];

		snprintf(tmp, sizeof tmp, "%s", line_read());
		for (char *save = NULL, *t = strtok_r(tmp, " \n", &save); t; t = strtok_r(NULL, " \n", &save)) {
			char d = t[1];

			if (strlen(t) > 6 && t[5] == '@' && !strchr(dbytes, d))
				nline += snprintf(line + nline, sizeof line - nline, "%s%s", nline ? " " : "", t);
		}
	}
	if (progress) {
		/* the line's lanes: CSR, the bit of the 64-bit word (odd beat), steps */
		char tmp[512];

		snprintf(tmp, sizeof tmp, "%s", line);
		for (char *t = strtok(tmp, " "); t; t = strtok(NULL, " ")) {
			unsigned c = strtoul(t, 0, 16);
			int steps = (int)strtol(t + 5 + (t[5] == '@'), 0, 16);	/* "@+b", "@-4", "+b" */

			printf("lane %05x %d %+d\n", c, cpu_bit(c >> 12 & 3, c >> 8 & 15), steps);
		}
		printf("result %s\n", line);
	}
	if (nline)
		printf("ddr_tune=%s\n", line);
	else
		printf("ddr_tune= (nothing: every lane within %d steps of BL2's value, none in the line read)\n", thresh);
out:
	atomic_store(&stop, 1);
	for (int i = 0; i < nw; i++)
		pthread_join(th[i], 0);
	restore_all();
	thaw();
	wdt_close();
	log_end(line, (long)(time(0) - t0));
	unlink(path_saved);
	close(saved_fd);
	if (atomic_load(&clamped))
		fprintf(stderr, "ddr-calibrate: %d values out of 0..3f were clamped: a bug\n", atomic_load(&clamped));
#ifdef DDR_SIM
	fprintf(stderr, "sim: clamped %d, out of field %d, frozen writes %d\n", atomic_load(&clamped),
		atomic_load(&sim_bad), atomic_load(&sim_frozen_writes));
#endif
	if (writeit) {
		if (!nline) {
			printf("nothing to keep: ddr-tune left as it is\n");
		} else {
			char cmd[600];

			snprintf(cmd, sizeof cmd, "ddr-tune set '%s'", line);
			return system(cmd) ? 1 : 0;
		}
	}
	return 0;
}
