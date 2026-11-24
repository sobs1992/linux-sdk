/*
 * eyescan: a read-eye scan of the G12B DDR PHY (Synopsys) at run time.
 *
 *   eyescan [-t dwell_ms] [-m MB per cpu] [-n max steps] [-c cpus] [-s step]
 *           [-k] CSR[,CSR...] {+|-}
 *
 * Memory checkers run on the CPUs (own buffers, random 64-bit words, read
 * back over and over). Each step adds step*k (k = 1, 2, ...) to the given
 * CSRs' trained values (or subtracts) and waits dwell_ms; at the first wrong
 * word every CSR goes back to its trained value at once. With -k the scan
 * goes on after an error (restores, waits, next step) up to -n steps.
 * Wrong words: bit histogram (bit i of the 64-bit word, i.e. byte lane
 * i/8%4, beat (i/32) parity), and whether DRAM holds the right value after
 * the restore (dc civac, re-read).
 * CSR address: block<<16 | instance<<12 | r<<8 | reg; APB byte address
 * 0xfe000000 + (csr << 1), 16-bit.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define PHY_BASE 0xfe000000UL
#define PHY_SIZE 0x200000UL
#define MAXCSR 16
#define MAXERR 64

static volatile uint16_t *phy;
static unsigned ncsr, csr[MAXCSR], orig[MAXCSR];
static unsigned npre, pcsr[MAXCSR], pval[MAXCSR], porig[MAXCSR];
static atomic_int stop, nerr_total;
static atomic_ulong passes, words_checked;
static atomic_uint bits[64], bits_up[64], bits_down[64];
struct err { uint64_t *p, exp, got, again, dram; int cpu; };
static struct err errs[MAXERR];
static atomic_int nerrs;

static void restore(void)
{
	for (unsigned i = 0; i < ncsr; i++)
		phy[csr[i]] = orig[i];
	__asm__ volatile("dsb sy" ::: "memory");
}

static void restore_all(void)
{
	restore();
	for (unsigned i = 0; i < npre; i++)
		phy[pcsr[i]] = porig[i];
	__asm__ volatile("dsb sy" ::: "memory");
}

static void on_sig(int s)
{
	restore_all();
	static const char m[] = "eyescan: fatal signal, CSRs restored\n";
	write(1, m, sizeof m - 1);
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
	uint64_t seed = (uint64_t)w->cpu << 56;
	for (unsigned pass = 0; !atomic_load(&stop); pass++) {
		uint64_t sd = seed ^ mix(pass);
		for (size_t i = 0; i < w->words; i++)
			w->buf[i] = mix(i ^ sd);
		/* several read passes per fill: reads are what the scan moves */
		for (int r = 0; r < 4 && !atomic_load(&stop); r++) {
			for (size_t i = 0; i < w->words; i++) {
				uint64_t e = mix(i ^ sd), g = w->buf[i];
				if (g != e) {
					uint64_t x = g ^ e;
					for (int b = 0; b < 64; b++)
						if (x >> b & 1) {
							atomic_fetch_add(&bits[b], 1);
							atomic_fetch_add(g >> b & 1 ? &bits_up[b] : &bits_down[b], 1);
						}
					atomic_fetch_add(&nerr_total, 1);
					uint64_t again = *(volatile uint64_t *)&w->buf[i];
					__asm__ volatile("dc civac, %0\n dsb sy" :: "r"(&w->buf[i]) : "memory");
					uint64_t dram = *(volatile uint64_t *)&w->buf[i];
					int n = atomic_fetch_add(&nerrs, 1);
					if (n < MAXERR)
						errs[n] = (struct err){ &w->buf[i], e, g, again, dram, w->cpu };
					w->buf[i] = e;	/* count each word once */
				}
			}
			atomic_fetch_add(&words_checked, w->words);
		}
		atomic_fetch_add(&passes, 1);
	}
	return 0;
}

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec * 1e-9;
}

int main(int argc, char **argv)
{
	int dwell = 2000, mb = 24, maxsteps = 40, step = 1, keep = 0;
	char cpus[64] = "0,1,2,3,4,5";
	int o;
	while ((o = getopt(argc, argv, "t:m:n:c:s:kp:")) != -1)
		switch (o) {
		case 't': dwell = atoi(optarg); break;
		case 'm': mb = atoi(optarg); break;
		case 'n': maxsteps = atoi(optarg); break;
		case 'c': snprintf(cpus, sizeof cpus, "%s", optarg); break;
		case 's': step = atoi(optarg); break;
		case 'k': keep = 1; break;
		case 'p':
			if (npre < MAXCSR && sscanf(optarg, "%x=%x", &pcsr[npre], &pval[npre]) == 2) npre++;
			break;
		default: return 2;
		}
	if (argc - optind != 2) {
		fprintf(stderr, "usage: eyescan [-t ms] [-m MB] [-n steps] [-c cpus] [-s step] [-k] CSR[,CSR] +|-\n");
		return 2;
	}
	for (char *p = strtok(argv[optind], ","); p && ncsr < MAXCSR; p = strtok(0, ","))
		csr[ncsr++] = strtoul(p, 0, 16);
	int dir = argv[optind + 1][0] == '-' ? -1 : 1;

	int fd = open("/dev/mem", O_RDWR | O_SYNC);
	if (fd < 0) { perror("/dev/mem"); return 1; }
	phy = mmap(0, PHY_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, PHY_BASE);
	if (phy == MAP_FAILED) { perror("mmap"); return 1; }
	for (unsigned i = 0; i < ncsr; i++)
		orig[i] = phy[csr[i]];
	for (unsigned i = 0; i < npre; i++)
		porig[i] = phy[pcsr[i]];
	signal(SIGINT, on_sig); signal(SIGTERM, on_sig); signal(SIGHUP, on_sig);
	signal(SIGABRT, on_sig); signal(SIGSEGV, on_sig); signal(SIGBUS, on_sig); signal(SIGILL, on_sig);
	signal(SIGPIPE, SIG_IGN);
	setvbuf(stdout, 0, _IOLBF, 0);

	printf("csr:");
	for (unsigned i = 0; i < ncsr; i++) printf(" %05x=%04x", csr[i], orig[i]);
	for (unsigned i = 0; i < npre; i++) printf(" preset %05x=%04x(was %04x)", pcsr[i], pval[i], porig[i]);
	printf("  dir %c step %d dwell %d ms, %d MB/cpu on %s\n", dir > 0 ? '+' : '-', step, dwell, mb, cpus);

	struct worker ws[8]; pthread_t th[8]; int nw = 0;
	for (char *p = strtok(cpus, ","); p && nw < 8; p = strtok(0, ",")) {
		ws[nw].cpu = atoi(p);
		ws[nw].words = (size_t)mb << 17;
		ws[nw].buf = mmap(0, (size_t)mb << 20, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
		if (ws[nw].buf == MAP_FAILED) { perror("mmap buf"); return 1; }
		mlock(ws[nw].buf, (size_t)mb << 20);
		nw++;
	}
	for (unsigned i = 0; i < npre; i++) phy[pcsr[i]] = pval[i];
	__asm__ volatile("dsb sy" ::: "memory");
	for (int i = 0; i < nw; i++) pthread_create(&th[i], 0, work, &ws[i]);

	/* baseline at the trained values */
	usleep(dwell * 1000);
	printf("base: errors %d, words %lu\n", atomic_load(&nerr_total), atomic_load(&words_checked));
	int rc = 0;
	for (int k = 1; k <= maxsteps; k++) {
		int before = atomic_load(&nerr_total);
		unsigned long w0 = atomic_load(&words_checked);
		unsigned val[MAXCSR];
		int clip = 0;
		for (unsigned i = 0; i < ncsr; i++) {
			int v = (int)orig[i] + dir * step * k;
			if (v < 0) { v = 0; clip = 1; }
			if (v > 0x3f && (orig[i] & ~0x3fu) == 0) { v = 0x3f; clip = 1; }
			val[i] = v;
		}
		for (unsigned i = 0; i < ncsr; i++) phy[csr[i]] = val[i];
		__asm__ volatile("dsb sy" ::: "memory");
		double t0 = now(), tend = t0 + dwell / 1000.0, terr = 0;
		while (now() < tend) {
			if (atomic_load(&nerr_total) != before) { restore(); terr = now() - t0; break; }
			usleep(200);
		}
		if (!terr) restore();
		int got = atomic_load(&nerr_total) - before;
		printf("step %+d (", dir * step * k);
		for (unsigned i = 0; i < ncsr; i++) printf("%s%04x", i ? " " : "", val[i]);
		printf("): errors %d%s", got, clip ? " CLIPPED" : "");
		if (terr) printf(" after %.1f ms", terr * 1000);
		printf(", words %lu\n", atomic_load(&words_checked) - w0);
		if (got) {
			usleep(300 * 1000);	/* let the workers' counts settle at trained values */
			if (!keep) { rc = 1; break; }
		}
		if (clip) break;
	}
	restore_all();
	atomic_store(&stop, 1);
	for (int i = 0; i < nw; i++) pthread_join(th[i], 0);

	int n = atomic_load(&nerrs);
	printf("total wrong words %d\n", atomic_load(&nerr_total));
	if (n) {
		printf("bits (bit: count up/down, lane, beat):");
		for (int b = 0; b < 64; b++)
			if (bits[b])
				printf(" %d:%u+%u-%u(L%d,%s)", b, bits[b], bits_up[b], bits_down[b], b / 8 % 4, (b / 32) & 1 ? "odd" : "even");
		printf("\n");
		for (int i = 0; i < n && i < 12; i++) {
			printf("  cpu%d %p exp %016llx xor %016llx again %s dram %s\n", errs[i].cpu, (void *)errs[i].p,
			       (unsigned long long)errs[i].exp, (unsigned long long)(errs[i].exp ^ errs[i].got),
			       errs[i].again == errs[i].exp ? "right" : "WRONG", errs[i].dram == errs[i].exp ? "right" : "WRONG");
		}
	}
	return rc;
}
