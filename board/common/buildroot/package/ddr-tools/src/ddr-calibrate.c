/*
 * ddr-calibrate: measure the read eye of every data lane of the G12B DDR
 * PHY (Synopsys LPDDR4) at run time and find the lanes BL2's training
 * leaves off-centre against the others of their nibble (docs/boards/ogu.md,
 * "Память: подстройка задержек чтения").
 *
 *   ddr-calibrate [-w] [-d DBYTES] [-c ms] [-f ms] [-t steps]
 *
 * Memory checkers run on all CPUs (own buffers, random words, read back
 * over and over). For each lane:
 *   early edge  its own read delay (RxPBDly) later, step by step, until the
 *               first wrong word: E steps;
 *   late edge   its nibble's read strobe (RxClkDly) later until the first
 *               wrong word on this lane, the other three lanes held 20 steps
 *               later meanwhile so that they do not fail first: T strobe
 *               steps;
 * and per nibble the strobe step in RxPBDly steps, R: the early edge of one
 * lane again with the strobe a few steps earlier. At the first wrong word
 * every register goes back at once (also on a fatal signal). The lane's
 * centre is S = (E - R*T) / 2 steps later; what is kept is the lane against
 * its nibble, S - median(S of the nibble): the nibble's own position (its
 * strobe) is trained anew at every start, a lane's skew against its
 * neighbours is the same every time. Lanes off by -t steps or more (4) make
 * the ddr-tune line, from BL2's training (/chosen/ddr-tune says what U-Boot
 * moved at this start); -w keeps it (ddr-tune set), from the next start on.
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
#include <time.h>
#include <unistd.h>

#define PHY_BASE	0xfe000000UL
#define PHY_SIZE	0x200000UL
#define CSR_PBD(db, r)	(0x10000u | (db) << 12 | (r) << 8 | 0x68)
#define CSR_CLK(db, u)	(0x10000u | (db) << 12 | (u) << 8 | 0x8c)
#define CSR_LNSEL(db, b) (0x10000u | (db) << 12 | (0xa0 + (b)))
#define VMAX		0x3f
#define PROTECT		20	/* the other lanes of the nibble, late-edge scans */
#define LOG		"/data/ddr-calibrate.log"

static volatile uint16_t *phy;
static int data_fd = -1, wdt_fd = -1;
static atomic_int stop;
static atomic_ullong errbits;	/* XOR bits of the wrong words since the probe began */
static atomic_int nerr;

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
	for (unsigned pass = 0; !atomic_load(&stop); pass++) {
		uint64_t sd = (uint64_t)w->cpu << 56 ^ mix(pass);

		for (size_t i = 0; i < w->words; i++)
			w->buf[i] = mix(i ^ sd);
		for (int r = 0; r < 4 && !atomic_load(&stop); r++)
			for (size_t i = 0; i < w->words; i++) {
				uint64_t e = mix(i ^ sd), g = w->buf[i];

				if (g != e) {
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
	for (int i = 0; i < n; i++)
		phy[csr[i]] = back[i];
	__asm__ volatile("dsb sy" ::: "memory");
	if (!bad)
		return 0;
	idle_ms(300);	/* the wrong words counted, the workers past them */
	return lanes_of(atomic_load(&errbits)) | 0x80000000u;
}

static int coarse_ms = 150, fine_ms = 1000;

/*
 * Edges are found one step at a time, never more: one step past an edge
 * reads a word wrong now and then, three or four steps past it nearly every
 * word of the lane, and before the registers go back such a burst can reach
 * the kernel. A pass with short waits (coarse_ms) stops at the first wrong
 * word; the two steps before it are tried again with long waits (fine_ms),
 * the edge being the first that reads wrong.
 */
static int edge(unsigned c, unsigned base, uint32_t lane, int *cens)
{
	unsigned v;
	int k;

	*cens = 2;
	for (k = 1; base + k <= VMAX; k++) {
		v = base + k;
		uint32_t l = probe(1, &c, &v, &base, coarse_ms);

		if (l) {
			*cens = l & lane ? 0 : 1;
			break;
		}
	}
	if (*cens == 2)
		return VMAX - base + 1;
	for (int kk = k - 2 > 0 ? k - 2 : 1; kk < k; kk++) {
		v = base + kk;
		uint32_t l = probe(1, &c, &v, &base, fine_ms);

		if (l) {
			*cens = l & lane ? 0 : 1;
			return kk;
		}
	}
	return k;
}

/* the early edge of lane (db, r): steps of its own delay to the first wrong word; *cens: none up to 3f */
static int early_edge(int db, int r, int *cens)
{
	unsigned c = CSR_PBD(db, r);
	int k = edge(c, phy[c], 1u << (db * 8 + r), cens);

	if (*cens == 1)	/* another lane read wrong: moving this one should not do that */
		*cens = 0;
	return k;
}

/*
 * The late edge of lane (db, 4u+i): steps of the nibble's strobe to its first
 * wrong word, the other lanes held later by hold[] meanwhile. *cens: another
 * lane failed first (1) or none up to 3f (2): the edge is at least that far.
 */
static int late_edge(int db, int u, int i, const int *hold, int *cens)
{
	unsigned c = CSR_CLK(db, u), base = phy[c], pc[4], pb[4], pv[4];
	int np = 0, k;

	for (int j = 0; j < 4; j++)
		if (j != i && hold[j] > 0) {
			pc[np] = CSR_PBD(db, 4 * u + j);
			pb[np] = phy[pc[np]];
			pv[np] = pb[np] + hold[j] > VMAX ? VMAX : pb[np] + hold[j];
			phy[pc[np]] = pv[np];
			np++;
		}
	__asm__ volatile("dsb sy" ::: "memory");
	k = edge(c, base, 1u << (db * 8 + 4 * u + i), cens);
	for (int j = 0; j < np; j++)
		phy[pc[j]] = pb[j];
	__asm__ volatile("dsb sy" ::: "memory");
	return k;
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
	int writeit = 0, thresh = 4, o, mb = 24;
	char dbytes[8] = "0123";

	while ((o = getopt(argc, argv, "wd:c:f:t:m:")) != -1)
		switch (o) {
		case 'w': writeit = 1; break;
		case 'd': snprintf(dbytes, sizeof dbytes, "%s", optarg); break;
		case 'c': coarse_ms = atoi(optarg); break;
		case 'f': fine_ms = atoi(optarg); break;
		case 't': thresh = atoi(optarg); break;
		case 'm': mb = atoi(optarg); break;
		default:
			fprintf(stderr, "usage: ddr-calibrate [-w] [-d DBYTES] [-c ms] [-f ms] [-t steps] [-m MB]\n");
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
	for (int db = 0; db < 4; db++) {
		for (int r = 0; r < 8; r++)
			save(CSR_PBD(db, r));
		save(CSR_CLK(db, 0));
		save(CSR_CLK(db, 1));
	}
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

	{
		FILE *f = fopen(LOG, "a");

		if (f) {
			fprintf(f, "== %s", ctime(&t0));
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
			int E[4], T[4], ce[4], ct[4], hold[4];
			double S[4], R = 2;
			char rnote[32] = "";

			for (int i = 0; i < 4; i++)
				E[i] = early_edge(db, 4 * u + i, &ce[i]);
			for (int i = 0; i < 4; i++)
				hold[i] = E[i] - 6 < PROTECT ? (E[i] - 6 > 0 ? E[i] - 6 : 0) : PROTECT;
			for (int i = 0; i < 4; i++)
				T[i] = late_edge(db, u, i, hold, &ct[i]);

			/* strobe step in delay steps: the lane with the most early margin, strobe d earlier */
			unsigned cc = CSR_CLK(db, u), cb = phy[cc];
			int x = 0, d = cb >= 4 ? 4 : cb, emin = VMAX;

			/* the strobe d earlier moves every lane ~2d steps towards its early edge: keep 6 clear */
			for (int i = 0; i < 4; i++)
				if (E[i] < emin)
					emin = E[i];
			while (d > 0 && 2 * d > emin - 6)
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

				if (!c2 && r >= 0.5 && r <= 5)
					R = r;
				else
					snprintf(rnote, sizeof rnote, " (R measured %.1f: 2 taken)", r);
			} else {
				snprintf(rnote, sizeof rnote, " (R not measured: 2 taken)");
			}

			int Sm[4], n = 0;

			for (int i = 0; i < 4; i++) {
				S[i] = (E[i] - R * T[i]) / 2;
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
				int moved = (int)cur - (int)trained(c), total = 0, put = 0;

				if (ok && (abs(reli) >= thresh || moved)) {
					total = moved + (abs(reli) >= thresh || moved ? reli : 0);
					put = 1;
				} else if (!ok && moved) {
					total = moved;
					put = 1;
				}
				if (put && total)
					nline += snprintf(line + nline, sizeof line - nline, "%s%05x%c%x",
							  nline ? " " : "", c, total < 0 ? '-' : '+', abs(total));
			}
			/* the nibble's result on disk before the next one */
			thaw();
			lg = fopen(LOG, "a");
			if (lg) {
				fprintf(lg, "%s\n", nib);
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
