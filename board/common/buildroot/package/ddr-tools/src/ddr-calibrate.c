/*
 * ddr-calibrate: measure the read eye of every data lane of the G12B DDR
 * PHY (Synopsys LPDDR4) at run time and find the lanes BL2's training
 * leaves off-centre against the others of their nibble (docs/boards/ogu.md,
 * "Память: подстройка задержек чтения").
 *
 *   ddr-calibrate [-w] [-v] [-r] [-d DBYTES] [-c ms] [-f ms] [-t steps]
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
 * signal). The lane's centre is S = (E - T) / 2 steps later; what is kept is the lane against
 * its nibble, S - median(S of the nibble): the nibble's own position (its
 * strobe) is trained anew at every start, a lane's skew against its
 * neighbours is the same every time. Lanes off by -t steps or more (4) make
 * the ddr-tune line, from BL2's training (/chosen/ddr-tune says what U-Boot
 * moved at this start); a lane that would go below 0 lifts its whole nibble
 * instead. -w keeps the line (ddr-tune set), from the next start on; -r goes
 * on with an interrupted run (the board went down) from its next nibble.
 *
 * A step at an edge reads wrong words; they can hit the kernel. /data is
 * frozen while measuring (a wrong line written back stays in RAM only), the
 * hardware watchdog (if free) resets a hung board. Log: /data/ddr-calibrate.log
 * (one block per run, a line per nibble). A run takes some 10 minutes; no
 * game should run.
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
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define PHY_BASE	0xfe000000UL
#define PHY_SIZE	0x200000UL
#define CSR_PBD(db, r)	(0x10000u | (db) << 12 | (r) << 8 | 0x68)
#define CSR_CLK(db, u)	(0x10000u | (db) << 12 | (u) << 8 | 0x8c)
#define CSR_LNSEL(db, b) (0x10000u | (db) << 12 | (0xa0 + (b)))
#define VMAX		0x3f
#define LOG		"/data/ddr-calibrate.log"

static volatile uint16_t *phy;
static int data_fd = -1, wdt_fd = -1;
static atomic_int stop;
static atomic_ullong errbits;	/* XOR bits of the wrong words since the probe began */
static atomic_int nerr;
static int verbose;	/* -v: each edge and lift */

/*
 * The probe in flight: the worker that reads the first wrong word puts its
 * registers back itself, at once - the fewer wrong words the rest of the
 * system (kernel, network, the display) reads meanwhile, the better.
 */
static unsigned armed_n, armed_csr[8], armed_back[8];
static atomic_int armed;

static void disarm_restore(void)
{
	if (atomic_exchange(&armed, 0)) {
		for (unsigned i = 0; i < armed_n; i++)
			phy[armed_csr[i]] = armed_back[i];
		__asm__ volatile("dsb sy" ::: "memory");
	}
}

/* every register this run may touch, with the value it had at the start */
static unsigned saved_csr[48], saved_val[48], nsaved;

static void save(unsigned csr)
{
	saved_csr[nsaved] = csr;
	saved_val[nsaved++] = phy[csr];
}

static void restore_all(void)
{
	for (unsigned i = 0; i < nsaved; i++)
		phy[saved_csr[i]] = saved_val[i];
	__asm__ volatile("dsb sy" ::: "memory");
}

static void thaw(void)
{
	if (data_fd >= 0)
		ioctl(data_fd, FITHAW, 0);
}

static void freeze(void)
{
	sync();
	if (data_fd >= 0 && ioctl(data_fd, FIFREEZE, 0) && errno != EBUSY)
		perror("freeze /data");
}

static void wdt_close(void)
{
	if (wdt_fd >= 0) {
		if (write(wdt_fd, "V", 1) != 1) { }
		close(wdt_fd);
		wdt_fd = -1;
	}
}

static void on_sig(int s)
{
	restore_all();
	thaw();
	wdt_close();
	static const char m[] = "ddr-calibrate: fatal signal, registers restored\n";
	if (write(2, m, sizeof m - 1) < 0) { }
	_exit(128 + s);
}

static inline uint64_t mix(uint64_t x)
{
	x ^= x >> 33; x *= 0xff51afd7ed558ccdULL;
	x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL;
	return x ^ (x >> 33);
}

struct worker { int cpu; size_t words; uint64_t *buf; };

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
	double end = now() + ms / 1000.0;

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
		phy[csr[i]] = val[i];
	__asm__ volatile("dsb sy" ::: "memory");
	double end = now() + ms / 1000.0;
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
		phy[csr[i]] = back[i];
	__asm__ volatile("dsb sy" ::: "memory");
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
			phy[cc] -= 1;
		for (int i = 0; i < 4; i++)
			phy[CSR_PBD(db, 4 * u + i)] += up ? inc : -inc;
		if (up)
			phy[cc] += 1;
		__asm__ volatile("dsb sy" ::: "memory");
		idle_ms(30);
		bad = atomic_load(&nerr) != before;
	}
	if (!bad)
		return 0;
	/* undo what was done, strobe first going down */
	for (int j = done; j >= 1; j--) {
		int jj = up ? j : s - j + 1, inc = lift_step(R, jj);

		if (up)
			phy[cc] -= 1;
		for (int i = 0; i < 4; i++)
			phy[CSR_PBD(db, 4 * u + i)] += up ? -inc : inc;
		if (!up)
			phy[cc] += 1;
		__asm__ volatile("dsb sy" ::: "memory");
	}
	idle_ms(300);
	return -1;
}

/* BL2's value of a register: /chosen/ddr-tune "CSR:trained>now ..." if U-Boot moved it */
static unsigned trained(unsigned csr)
{
	static char buf[256];
	static int read_once;
	char key[8];

	if (!read_once) {
		FILE *f = fopen("/proc/device-tree/chosen/ddr-tune", "r");

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

static int cmp_int(const void *a, const void *b)
{
	return *(const int *)a - *(const int *)b;
}

int main(int argc, char **argv)
{
	int writeit = 0, thresh = 4, o, mb = 24, resume = 0, done[4][2] = { { 0 } };
	char dbytes[8] = "0123";

	while ((o = getopt(argc, argv, "wvrd:c:f:t:m:")) != -1)
		switch (o) {
		case 'w': writeit = 1; break;
		case 'v': verbose = 1; break;
		case 'r': resume = 1; break;
		case 'd': snprintf(dbytes, sizeof dbytes, "%s", optarg); break;
		case 'c': coarse_ms = atoi(optarg); break;
		case 'f': fine_ms = atoi(optarg); break;
		case 't': thresh = atoi(optarg); break;
		case 'm': mb = atoi(optarg); break;
		default:
			fprintf(stderr, "usage: ddr-calibrate [-w] [-v] [-r] [-d DBYTES] [-c ms] [-f ms] [-t steps] [-m MB]\n");
			return 2;
		}

	int fd = open("/dev/mem", O_RDWR | O_SYNC);

	if (fd < 0) { perror("/dev/mem"); return 1; }
	phy = mmap(0, PHY_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, PHY_BASE);
	if (phy == MAP_FAILED) { perror("mmap"); return 1; }
	if (phy[0xd0000] != 0) {
		fprintf(stderr, "ddr-calibrate: the PHY's registers are not open to the CPU (MicroContMuxSel)\n");
		return 1;
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
	static const int sigs[] = { SIGINT, SIGTERM, SIGHUP, SIGABRT, SIGSEGV, SIGBUS, SIGILL };

	for (unsigned i = 0; i < sizeof sigs / sizeof sigs[0]; i++)
		signal(sigs[i], on_sig);
	signal(SIGPIPE, SIG_IGN);
	setvbuf(stdout, 0, _IOLBF, 0);

	data_fd = open("/data", O_RDONLY);
	wdt_fd = open("/dev/watchdog", O_WRONLY);
	if (wdt_fd >= 0) {
		int t = 30;

		ioctl(wdt_fd, WDIOC_SETTIMEOUT, &t);
	}

	struct worker ws[8];
	pthread_t th[8];
	int nw = 0;
	long ncpu = sysconf(_SC_NPROCESSORS_ONLN);

	for (int c = 0; c < ncpu && nw < 8; c++, nw++) {
		ws[nw].cpu = c;
		ws[nw].words = (size_t)mb << 17;
		ws[nw].buf = mmap(0, (size_t)mb << 20, PROT_READ | PROT_WRITE,
				  MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
		if (ws[nw].buf == MAP_FAILED) { perror("mmap"); return 1; }
		mlock(ws[nw].buf, (size_t)mb << 20);
	}

	FILE *lg = NULL;
	time_t t0 = time(0);
	char line[512] = "";
	int nline = 0;

	/*
	 * -r: go on with the last run in the log if it did not end (the board went
	 * down): its nibbles are done, their "keep:" parts of the line are taken.
	 * A lane against its nibble does not depend on the start, so nibbles of
	 * runs from different starts add up.
	 */
	if (resume) {
		FILE *f = fopen(LOG, "r");
		char l[512], blk[16][512];
		int nb = 0, open = 0;

		while (f && fgets(l, sizeof l, f)) {
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
			nb = 0;
		for (int i = 0; i < nb; i++) {
			int db, u;
			char *k = strstr(blk[i], " keep:");

			if (sscanf(blk[i], "dbyte %d nibble %d:", &db, &u) != 2 || db < 0 || db > 3 || u < 0 || u > 1)
				continue;
			done[db][u] = 1;
			for (char *t = k ? strtok(k + 6, " \n") : NULL; t; t = strtok(NULL, " \n"))
				nline += snprintf(line + nline, sizeof line - nline, "%s%s", nline ? " " : "", t);
			printf("dbyte %d nibble %d: done before (%s)\n", db, u, k ? k + 1 : "keep: nothing");
		}
		if (!nb)
			resume = 0;
	}
	{
		FILE *f = fopen(LOG, "a");

		if (f) {
			fprintf(f, resume ? "-- resumed %s" : "== %s", ctime(&t0));
			fclose(f);
		}
	}
	freeze();
	for (int i = 0; i < nw; i++)
		pthread_create(&th[i], 0, work, &ws[i]);
	idle_ms(1000);
	if (atomic_load(&nerr)) {
		fprintf(stderr, "ddr-calibrate: wrong words at the trained values: stopping\n");
		goto out;
	}

	printf("lane  bit  now  early  late  S    vs nibble\n");
	for (const char *dp = dbytes; *dp; dp++) {
		int db = *dp - '0';

		if (db < 0 || db > 3)
			continue;
		for (int u = 0; u < 2; u++) {
			if (done[db][u])
				continue;
			int E[4], T[4], ce[4], ct[4], nline0 = nline, tot[4], put[4];
			unsigned bl2v[4];
			double S[4], R = 2.5;
			char rnote[64] = "";

			for (int i = 0; i < 4; i++)
				E[i] = early_edge(db, 4 * u + i, &ce[i]);

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

				phy[cc] = cb - d;
				__asm__ volatile("dsb sy" ::: "memory");
				int E2 = early_edge(db, 4 * u + x, &c2);

				phy[cc] = cb;
				__asm__ volatile("dsb sy" ::: "memory");
				double r = (double)(E[x] - E2) / d;

				if (!c2 && r >= 1 && r <= 4)
					R = r;
				else
					snprintf(rnote, sizeof rnote, " (R measured %.1f: 2.5 taken)", r);
			} else {
				snprintf(rnote, sizeof rnote, " (R not measured: 2.5 taken)");
			}

			/* lift the nibble as far as the highest delay allows (16 strobe steps at most) */
			int maxb = 0, lifted = 0;

			for (int i = 0; i < 4; i++)
				if (phy[CSR_PBD(db, 4 * u + i)] > (unsigned)maxb)
					maxb = phy[CSR_PBD(db, 4 * u + i)];
			int sl = (int)((VMAX - maxb) / (R + 0.5));

			for (sl = sl > 16 ? 16 : sl; sl >= 2; sl -= 3) {
				if (lift(db, u, R, sl, 1) == 0) {
					lifted = sl;
					break;
				}
				if (verbose)
					printf("  lift by %d read wrong: less\n", sl);
			}
			for (int i = 0; i < 4; i++)
				T[i] = lane_edge(db, 4 * u + i, -1, &ct[i]);
			if (lifted && lift(db, u, R, lifted, 0)) {
				fprintf(stderr, "ddr-calibrate: lowering dbyte %d nibble %d read wrong: stopping\n", db, u);
				goto out;
			}
			snprintf(rnote + strlen(rnote), sizeof rnote - strlen(rnote), ", lifted %d", lifted);

			int Sm[4], n = 0;

			for (int i = 0; i < 4; i++) {
				S[i] = (E[i] - T[i]) / 2.0;
				if (!ce[i] && !ct[i])
					Sm[n++] = (int)(S[i] >= 0 ? S[i] + 0.5 : S[i] - 0.5);
			}
			qsort(Sm, n, sizeof Sm[0], cmp_int);
			double med = n == 0 ? 0 : n % 2 ? Sm[n / 2] : (Sm[n / 2 - 1] + Sm[n / 2]) / 2.0;

			char nib[256];
			int nl = snprintf(nib, sizeof nib, "dbyte %d nibble %d: strobe %02x, R %.2f%s;", db, u,
					  phy[CSR_CLK(db, u)], R, rnote);

			for (int i = 0; i < 4; i++) {
				int r = 4 * u + i;
				unsigned c = CSR_PBD(db, r), cur = phy[c];
				double rel = S[i] - med;
				int reli = (int)(rel >= 0 ? rel + 0.5 : rel - 0.5);
				int ok = !ce[i] && !ct[i] && n >= 3;

				printf("%d.%d   %2d   %02x   %2d%s   %2d%s  %5.1f  %+5.1f%s\n", db, r, cpu_bit(db, r), cur,
				       E[i], ce[i] ? "+" : " ", T[i], ct[i] ? "+" : " ", S[i], rel,
				       ok ? (abs(reli) >= thresh ? "  <-" : "") : "  (edge not reached)");
				nl += snprintf(nib + nl, sizeof nib - nl, " r%d E%d%s T%d%s %+d", r, E[i], ce[i] ? "+" : "",
					       T[i], ct[i] ? "+" : "", reli);
				/*
				 * Off-centre: the move from BL2's value to the centre. A lane
				 * moved at this start (ddr-tune) stays in the line: measured, its
				 * move is corrected; not measured, it is kept as it is.
				 */
				int moved = (int)cur - (int)trained(c);

				bl2v[i] = trained(c);
				put[i] = 0;
				tot[i] = 0;
				if (ok && (abs(reli) >= thresh || moved)) {
					tot[i] = moved + reli;
					put[i] = 1;
				} else if (!ok && moved) {
					tot[i] = moved;
					put[i] = 1;
				}
			}
			/*
			 * A delay cannot go below 0: a lane that needs to (BL2 left it at 0
			 * or near) gets there by its three neighbours going up as much -
			 * the same skew within the nibble; the nibble as a whole later,
			 * which is where the eyes' middles are (BL2 samples near the late
			 * edges, see docs).
			 */
			int lift_all = 0;

			for (int i = 0; i < 4; i++)
				if (put[i] && (int)bl2v[i] + tot[i] < -lift_all)
					lift_all = -((int)bl2v[i] + tot[i]);
			for (int i = 0; i < 4; i++) {
				unsigned c = CSR_PBD(db, 4 * u + i);

				if (lift_all) {
					tot[i] += lift_all;
					put[i] = 1;
				}
				if ((int)bl2v[i] + tot[i] > VMAX)
					tot[i] = VMAX - (int)bl2v[i];
				if (put[i] && tot[i])
					nline += snprintf(line + nline, sizeof line - nline, "%s%05x%c%x",
							  nline ? " " : "", c, tot[i] < 0 ? '-' : '+', abs(tot[i]));
			}
			if (lift_all)
				printf("dbyte %d nibble %d: a lane below 0, the nibble %d steps later\n", db, u, lift_all);
			/* the nibble's result on disk before the next one */
			thaw();
			lg = fopen(LOG, "a");
			if (lg) {
				fprintf(lg, "%s keep:%s%s\n", nib, nline > nline0 && nline0 ? "" : " ", line + nline0);
				fflush(lg);
				fsync(fileno(lg));
				fclose(lg);
			}
			freeze();
		}
	}

	if (nline)
		printf("ddr_tune=%s\n", line);
	else
		printf("ddr_tune= (nothing: every lane within %d steps of its nibble, none moved now)\n", thresh);
out:
	atomic_store(&stop, 1);
	for (int i = 0; i < nw; i++)
		pthread_join(th[i], 0);
	restore_all();
	thaw();
	wdt_close();
	lg = fopen(LOG, "a");
	if (lg) {
		fprintf(lg, "ddr_tune=%s (%ld s)\n", line, (long)(time(0) - t0));
		fclose(lg);
	}
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
