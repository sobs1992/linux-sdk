/* phyreg: read/write Synopsys DDR PHY CSRs on Amlogic G12B (APB at 0xfe000000, csr<<1, 16-bit) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#define BASE 0xfe000000UL
#define SIZE 0x200000UL
static volatile uint16_t *m;
static unsigned rd(unsigned csr) { return m[csr]; }          /* byte addr = csr<<1 */
static void wr(unsigned csr, unsigned v) { m[csr] = v; }
int main(int argc, char **argv)
{
	if (argc < 2) { fprintf(stderr, "phyreg rd CSR [N] | wr CSR VAL | dump\n"); return 2; }
	int fd = open("/dev/mem", O_RDWR | O_SYNC);
	if (fd < 0) { perror("/dev/mem"); return 1; }
	m = mmap(0, SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, BASE);
	if (m == MAP_FAILED) { perror("mmap"); return 1; }
	if (!strcmp(argv[1], "rd")) {
		unsigned c = strtoul(argv[2], 0, 16), n = argc > 3 ? strtoul(argv[3], 0, 0) : 1;
		for (unsigned i = 0; i < n; i++) printf("%05x %04x\n", c + i, rd(c + i));
	} else if (!strcmp(argv[1], "wr")) {
		unsigned c = strtoul(argv[2], 0, 16), v = strtoul(argv[3], 0, 16);
		wr(c, v); printf("%05x <- %04x, now %04x\n", c, v, rd(c));
	} else if (!strcmp(argv[1], "dump")) {
		static const struct { unsigned reg; const char *n; int lanes; } R[] = {
			{0x68, "RxPBDlyTg0", 9}, {0x69, "RxPBDlyTg1", 9}, {0x8c, "RxClkDlyTg0", 9},
			{0x8d, "RxClkDlyTg1", 9}, {0x80, "RxEnDlyTg0", 9}, {0xc0, "TxDqDlyTg0", 9},
			{0xd0, "TxDqsDlyTg0", 9}, {0x40, "VrefDAC0", 9}, {0x30, "VrefDAC1", 9},
		};
		for (unsigned k = 0; k < sizeof R / sizeof R[0]; k++)
			for (unsigned d = 0; d < 4; d++) {
				printf("%-12s db%u:", R[k].n, d);
				for (int r = 0; r < R[k].lanes; r++)
					printf(" %04x", rd((1 << 16) | (d << 12) | (r << 8) | R[k].reg));
				printf("\n");
			}
	}
	return 0;
}
