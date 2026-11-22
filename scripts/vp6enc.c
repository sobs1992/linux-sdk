/*
 * vp6enc: re-encode the video of an Electronic Arts VP6 movie (.vp6: MVhd,
 * MV0K/MV0F video chunks between SCHl/SCCl/SCDl/SCEl audio chunks) at
 * another size, every frame a key frame. The audio chunks and their order
 * stay as they are; each video chunk is replaced by the next frame read.
 *
 *   ffmpeg -i in.vp6 -vf scale=848:480 -pix_fmt yuv420p -f rawvideo - |
 *       vp6enc in.vp6 out.vp6 848 480 QUANT
 *
 * Need for Speed: Most Wanted's movies are 1920x1088 VP6: its decoder,
 * x86 code under Box64 on the GO Ultra, managed ~13 of their 30 frames a
 * second. scripts/ea-vp6-shrink.py drives this for a directory.
 *
 * Key frames only, so nothing of the decoder's picture is needed here:
 * VP6 predicts a key frame's DC from the neighbours' quantised DC
 * levels, not from pixels. The bitstream: VP6.0 simple profile (as the
 * game's own files), coefficients in a second bool-coded partition,
 * coefficient probabilities sent per frame where they pay. The layout of
 * the frame, its contexts and its trees follow FFmpeg's VP6 decoder
 * (libavcodec/vp6.c, vp56.c; LGPL 2.1+), whose tables are copied below;
 * the bool coder is RFC 6386's.
 *
 * VP6 in EA's files is stored upside down (FFmpeg decodes AV_CODEC_ID_VP6
 * with a negative stride): the picture's bottom row is coded first.
 *
 * QUANT is VP6's quantiser index, 0..63, higher = finer (the game's own
 * movies use 60 at 1920x1088).
 */
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- tables (FFmpeg libavcodec/vp56data.c, vp6data.h, mathtables.c) ---- */

static const uint8_t zigzag_direct[64] = {
	0,   1,  8, 16,  9,  2,  3, 10,
	17, 24, 32, 25, 18, 11,  4,  5,
	12, 19, 26, 33, 40, 48, 41, 34,
	27, 20, 13,  6,  7, 14, 21, 28,
	35, 42, 49, 56, 57, 50, 43, 36,
	29, 22, 15, 23, 30, 37, 44, 51,
	58, 59, 52, 45, 38, 31, 39, 46,
	53, 60, 61, 54, 47, 55, 62, 63,
};

static const uint8_t coeff_parse_table[6][11] = {
	{ 159,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0 },
	{ 145, 165,   0,   0,   0,   0,   0,   0,   0,   0,   0 },
	{ 140, 148, 173,   0,   0,   0,   0,   0,   0,   0,   0 },
	{ 135, 140, 155, 176,   0,   0,   0,   0,   0,   0,   0 },
	{ 130, 134, 141, 157, 180,   0,   0,   0,   0,   0,   0 },
	{ 129, 130, 133, 140, 153, 177, 196, 230, 243, 254, 254 },
};
static const uint16_t coeff_bias[] = { 0, 1, 2, 3, 4, 5, 7, 11, 19, 35, 67 };
static const uint8_t coeff_bit_length[] = { 0, 1, 2, 3, 4, 10 };

static const uint8_t ac_dequant[64] = {
	94, 92, 90, 88, 86, 82, 78, 74,
	70, 66, 62, 58, 54, 53, 52, 51,
	50, 49, 48, 47, 46, 45, 44, 43,
	42, 40, 39, 37, 36, 35, 34, 33,
	32, 31, 30, 29, 28, 27, 26, 25,
	24, 23, 22, 21, 20, 19, 18, 17,
	16, 15, 14, 13, 12, 11, 10,  9,
	 8,  7,  6,  5,  4,  3,  2,  1,
};
static const uint8_t dc_dequant[64] = {
	47, 47, 47, 47, 45, 43, 43, 43,
	43, 43, 42, 41, 41, 40, 40, 40,
	40, 35, 35, 35, 35, 33, 33, 33,
	33, 32, 32, 32, 27, 27, 26, 26,
	25, 25, 24, 24, 23, 23, 19, 19,
	19, 19, 18, 18, 17, 16, 16, 16,
	16, 16, 15, 11, 11, 11, 10, 10,
	 9,  8,  7,  5,  3,  3,  2,  2,
};

static const uint8_t def_coeff_reorder[64] = {
	 0,  0,  1,  1,  1,  2,  2,  2,
	 2,  2,  2,  3,  3,  4,  4,  4,
	 5,  5,  5,  5,  6,  6,  7,  7,
	 7,  7,  7,  8,  8,  9,  9,  9,
	 9,  9,  9, 10, 10, 11, 11, 11,
	11, 11, 11, 12, 12, 12, 12, 12,
	12, 13, 13, 13, 13, 13, 14, 14,
	14, 14, 15, 15, 15, 15, 15, 15,
};
static const uint8_t def_runv_coeff_model[2][14] = {
	{ 198, 197, 196, 146, 198, 204, 169, 142, 130, 136, 149, 149, 191, 249 },
	{ 135, 201, 181, 154,  98, 117, 132, 126, 146, 169, 184, 240, 246, 254 },
};
static const uint8_t dccv_pct[2][11] = {
	{ 146, 255, 181, 207, 232, 243, 238, 251, 244, 250, 249 },
	{ 179, 255, 214, 240, 250, 255, 244, 255, 255, 255, 255 },
};
static const uint8_t runv_pct[2][14] = {
	{ 219, 246, 238, 249, 232, 239, 249, 255, 248, 253, 239, 244, 241, 248 },
	{ 198, 232, 251, 253, 219, 241, 253, 255, 248, 249, 244, 238, 251, 255 },
};
static const uint8_t ract_pct[3][2][6][11] = {
  { { { 227, 246, 230, 247, 244, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 209, 231, 231, 249, 249, 253, 255, 255, 255 },
      { 255, 255, 225, 242, 241, 251, 253, 255, 255, 255, 255 },
      { 255, 255, 241, 253, 252, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 248, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } },
    { { 240, 255, 248, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 240, 253, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } } },
  { { { 206, 203, 227, 239, 247, 255, 253, 255, 255, 255, 255 },
      { 207, 199, 220, 236, 243, 252, 252, 255, 255, 255, 255 },
      { 212, 219, 230, 243, 244, 253, 252, 255, 255, 255, 255 },
      { 236, 237, 247, 252, 253, 255, 255, 255, 255, 255, 255 },
      { 240, 240, 248, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } },
    { { 230, 233, 249, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 238, 238, 250, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 248, 251, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } } },
  { { { 225, 239, 227, 231, 244, 253, 243, 255, 255, 253, 255 },
      { 232, 234, 224, 228, 242, 249, 242, 252, 251, 251, 255 },
      { 235, 249, 238, 240, 251, 255, 249, 255, 253, 253, 255 },
      { 249, 253, 251, 250, 255, 255, 255, 255, 255, 255, 255 },
      { 251, 250, 249, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } },
    { { 243, 244, 250, 250, 255, 255, 255, 255, 255, 255, 255 },
      { 249, 248, 250, 253, 255, 255, 255, 255, 255, 255, 255 },
      { 253, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 },
      { 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255 } } }
};
static const int dccv_lc[3][5][2] = {
	{ { 122, 133 }, { 0, 1 }, { 78,  171 }, { 139, 117 }, { 168, 79 } },
	{ { 133,  51 }, { 0, 1 }, { 169,  71 }, { 214,  44 }, { 210, 38 } },
	{ { 142, -16 }, { 0, 1 }, { 221, -30 }, { 246,  -3 }, { 203, 17 } },
};
static const uint8_t coeff_groups[64] = {
	0, 0, 1, 1, 1, 2, 2, 2,
	2, 2, 2, 3, 3, 3, 3, 3,
	3, 3, 3, 3, 3, 3, 4, 4,
	4, 4, 4, 4, 4, 4, 4, 4,
	4, 4, 4, 4, 4, 5, 5, 5,
	5, 5, 5, 5, 5, 5, 5, 5,
	5, 5, 5, 5, 5, 5, 5, 5,
	5, 5, 5, 5, 5, 5, 5, 5,
};

/* trees: {val, prob_idx}; val > 0 jumps by val on a 1, a leaf is -symbol */
struct tree { int8_t val, prob_idx; };
static const struct tree pc_tree[] = {
	{ 4, 6},
	{ 2, 7}, {-0, 0}, {-1, 0},
	{ 4, 8},
	{ 2, 9}, {-2, 0}, {-3, 0},
	{ 2,10}, {-4, 0}, {-5, 0},
};
static const struct tree pcr_tree[] = {
	{ 8, 0},
	{ 4, 1},
	{ 2, 2}, {-1, 0}, {-2, 0},
	{ 2, 3}, {-3, 0}, {-4, 0},
	{ 8, 4},
	{ 4, 5},
	{ 2, 6}, {-5, 0}, {-6, 0},
	{ 2, 7}, {-7, 0}, {-8, 0},
	         {-0, 0},
};

/* ---- the path of each symbol through a tree ---- */

struct path { int n; uint8_t bit[8], prob_idx[8]; };

static int tree_path(const struct tree *t, int at, int sym, struct path *p)
{
	if (t[at].val <= 0)
		return -t[at].val == sym;
	p->prob_idx[p->n] = t[at].prob_idx;
	p->bit[p->n] = 0;
	p->n++;
	if (tree_path(t, at + 1, sym, p))
		return 1;
	p->bit[p->n - 1] = 1;
	if (tree_path(t, at + t[at].val, sym, p))
		return 1;
	p->n--;
	return 0;
}

static struct path pc_path[6], pcr_path[9];

/* ---- bool encoder (RFC 6386, 7.3) ---- */

struct bool_enc {
	uint8_t *buf;
	size_t len, cap;
	uint32_t range, bottom;
	int bit_count;
};

static void be_init(struct bool_enc *e)
{
	e->len = 0;
	e->range = 255;
	e->bottom = 0;
	e->bit_count = 24;
}

static void be_byte(struct bool_enc *e, uint8_t b)
{
	if (e->len == e->cap) {
		e->cap = e->cap ? e->cap * 2 : 1 << 16;
		e->buf = realloc(e->buf, e->cap);
		if (!e->buf) {
			perror("vp6enc");
			exit(1);
		}
	}
	e->buf[e->len++] = b;
}

static void be_carry(struct bool_enc *e)
{
	size_t i = e->len;

	while (i > 0 && e->buf[i - 1] == 255)
		e->buf[--i] = 0;
	if (i > 0)
		e->buf[i - 1]++;
}

static void be_put(struct bool_enc *e, int prob, int bit)
{
	uint32_t split = 1 + (((e->range - 1) * (uint32_t)prob) >> 8);

	if (bit) {
		e->bottom += split;
		e->range -= split;
	} else {
		e->range = split;
	}
	while (e->range < 128) {
		e->range <<= 1;
		if (e->bottom & (1u << 31))
			be_carry(e);
		e->bottom <<= 1;
		if (!--e->bit_count) {
			be_byte(e, (uint8_t)(e->bottom >> 24));
			e->bottom &= (1 << 24) - 1;
			e->bit_count = 8;
		}
	}
}

static void be_flush(struct bool_enc *e)
{
	int c = e->bit_count;
	uint32_t v = e->bottom;

	if (v & (1u << (32 - c)))
		be_carry(e);
	v <<= c & 7;
	c >>= 3;
	while (--c >= 0)
		v <<= 8;
	c = 4;
	while (--c >= 0) {
		be_byte(e, (uint8_t)(v >> 24));
		v <<= 8;
	}
}

static void be_bits(struct bool_enc *e, unsigned v, int n)
{
	while (n--)
		be_put(e, 128, (v >> n) & 1);
}

/* ---- bit costs (1/256 bit units) for choosing probabilities ---- */

static int cost0[256];	/* cost of a 0 coded with probability p (of a 0) */

static void init_costs(void)
{
	for (int p = 1; p < 256; p++)
		cost0[p] = (int)lrint(-log2(p / 256.0) * 256);
	cost0[0] = cost0[1];
}

static int64_t bits_cost(int p, const uint32_t ct[2])
{
	return (int64_t)ct[0] * cost0[p] + (int64_t)ct[1] * cost0[256 - p];
}

/* the cheapest probability that a 7-bit update can send (v << 1, 0 -> 1) */
static int best_prob(const uint32_t ct[2], int64_t *cost)
{
	int best = 128;
	int64_t bc = -1;

	for (int v = 0; v < 128; v++) {
		int p = v ? v << 1 : 1;
		int64_t c = bits_cost(p, ct);

		if (bc < 0 || c < bc) {
			bc = c;
			best = p;
		}
	}
	*cost = bc;
	return best;
}

/* ---- the coded picture ---- */

struct blk {
	int16_t lev[64];	/* by coefficient index (coded order); [0] = DC residual */
	uint8_t ctx;		/* DC context: neighbours with a non-zero DC residual */
	uint8_t last;		/* index after the last non-zero level (0 = none) */
};

struct enc {
	int w, h, mbw, mbh, q;
	uint8_t *y, *u, *v;	/* the picture, flipped: row 0 is the bottom */
	struct blk *blk;	/* 6 a macroblock, in coding order */
	uint8_t index_to_pos[64];
	/* probabilities in use this frame */
	uint8_t dccv[2][11], dcct[2][3][5], ract[2][3][6][11], runv[2][14];
	/* counts: [node][bit] */
	uint32_t c_dccv[2][11][2], c_dcct[2][3][5][2], c_ract[2][3][6][11][2], c_runv[2][14][2];
	double cos_t[8][8];
	struct bool_enc p1, p2;
};

static void index_to_pos_init(struct enc *e)
{
	int idx = 1;

	e->index_to_pos[0] = 0;
	for (int i = 0; i < 16; i++)
		for (int pos = 1; pos < 64; pos++)
			if (def_coeff_reorder[pos] == i)
				e->index_to_pos[idx++] = pos;
}

/* orthonormal 2-D DCT of an 8x8 block minus 128; out[v * 8 + h] */
static void fdct(const struct enc *e, const uint8_t *src, int stride, double *out)
{
	double tmp[8][8];

	for (int y = 0; y < 8; y++)
		for (int h = 0; h < 8; h++) {
			double s = 0;

			for (int x = 0; x < 8; x++)
				s += (src[y * stride + x] - 128.0) * e->cos_t[h][x];
			tmp[y][h] = s;
		}
	for (int v = 0; v < 8; v++)
		for (int h = 0; h < 8; h++) {
			double s = 0;

			for (int y = 0; y < 8; y++)
				s += tmp[y][h] * e->cos_t[v][y];
			out[v * 8 + h] = s;
		}
}

/*
 * Levels as the decoder multiplies them back: the IDCT (VP3's) takes 4x
 * the orthonormal coefficients and dequant tables are stored << 2, so a
 * level is the orthonormal coefficient over the table's value.
 */
static int quant(double c, int step, double bias)
{
	double a = fabs(c) / step;
	int l = (int)(a + bias);

	return c < 0 ? -l : l;
}

static void code_blocks(struct enc *e)
{
	/* DC prediction state, as libavcodec/vp56.c keeps it */
	struct ref { int ref, dc, nnz; } *above, left[4];
	int prev_dc[3], above_idx[6];
	int dcq = dc_dequant[e->q], acq = ac_dequant[e->q];
	struct blk *b = e->blk;
	const int NONE = 0, CUR = 1;

	above = calloc(4 * e->mbw + 6, sizeof(*above));
	if (!above) {
		perror("vp6enc");
		exit(1);
	}
	above[2 * e->mbw + 2].ref = CUR;
	above[3 * e->mbw + 4].ref = CUR;
	prev_dc[0] = 0;
	prev_dc[1] = prev_dc[2] = 128;

	for (int row = 0; row < e->mbh; row++) {
		memset(left, 0, sizeof(left));
		above_idx[0] = 1;
		above_idx[1] = 2;
		above_idx[2] = 1;
		above_idx[3] = 2;
		above_idx[4] = 2 * e->mbw + 2 + 1;
		above_idx[5] = 3 * e->mbw + 4 + 1;
		for (int col = 0; col < e->mbw; col++) {
			for (int n = 0; n < 6; n++, b++) {
				static const uint8_t b6to4[6] = { 0, 0, 1, 1, 2, 3 };
				static const uint8_t b2p[6] = { 0, 0, 0, 0, 1, 2 };
				struct ref *ab = &above[above_idx[n]], *lb = &left[b6to4[n]];
				const uint8_t *src;
				int stride, count = 0, dc = 0, level;
				double f[64];

				if (n < 4) {
					stride = e->w;
					src = e->y + (row * 16 + (n >> 1) * 8) * stride + col * 16 + (n & 1) * 8;
				} else {
					stride = e->w / 2;
					src = (n == 4 ? e->u : e->v) + row * 8 * stride + col * 8;
				}
				fdct(e, src, stride, f);
				b->last = 0;
				for (int k = 1; k < 64; k++) {
					b->lev[k] = (int16_t)quant(f[zigzag_direct[e->index_to_pos[k]]], acq, 0.38);
					if (b->lev[k])
						b->last = k + 1;
				}
				level = quant(f[0], dcq, 0.5);

				/* the decoder's DC prediction (vp56_add_predictors_dc) */
				b->ctx = lb->nnz + ab->nnz;
				if (lb->ref == CUR) {
					dc += lb->dc;
					count++;
				}
				if (ab->ref == CUR) {
					dc += ab->dc;
					count++;
				}
				if (count == 0)
					dc = prev_dc[b2p[n]];
				else if (count == 2)
					dc /= 2;
				b->lev[0] = (int16_t)(level - dc);
				if (b->lev[0] && !b->last)
					b->last = 1;
				prev_dc[b2p[n]] = level;
				ab->dc = lb->dc = level;
				ab->ref = lb->ref = CUR;
				ab->nnz = lb->nnz = b->lev[0] != 0;
				(void)NONE;
			}
			for (int y = 0; y < 4; y++)
				above_idx[y] += 2;
			for (int uv = 4; uv < 6; uv++)
				above_idx[uv] += 1;
		}
	}
	free(above);
}

/*
 * The tokens of every block, either counted (bool coder NULL: branch
 * statistics for the probabilities) or written. The walk is
 * vp6_parse_coeff() run backwards.
 */
#define PUT(node, prob, bit) do { \
		if (w) be_put(w, (prob), (bit)); \
		else (node)[!!(bit)]++; \
	} while (0)

static void put_value(struct enc *e, struct bool_enc *w, int a, uint8_t *m1, uint8_t *m2,
		      uint32_t (*c1)[2], uint32_t (*c2)[2])
{
	/* a = |coefficient| >= 1 */
	if (a == 1) {
		PUT(c2[2], m2[2], 0);
		return;
	}
	PUT(c2[2], m2[2], 1);
	if (a <= 4) {
		PUT(c2[3], m2[3], 0);
		if (a == 2) {
			PUT(c2[4], m2[4], 0);
		} else {
			PUT(c2[4], m2[4], 1);
			PUT(c1[5], m1[5], a - 3);
		}
		return;
	}
	PUT(c2[3], m2[3], 1);
	{
		int cat = a >= 67 ? 5 : a >= 35 ? 4 : a >= 19 ? 3 : a >= 11 ? 2 : a >= 7 ? 1 : 0;
		const struct path *p = &pc_path[cat];
		int extra = a - coeff_bias[cat + 5];

		for (int i = 0; i < p->n; i++)
			PUT(c1[p->prob_idx[i]], m1[p->prob_idx[i]], p->bit[i]);
		for (int i = coeff_bit_length[cat]; i >= 0; i--)
			if (w)
				be_put(w, coeff_parse_table[cat][i], (extra >> i) & 1);
	}
	(void)e;
}

static void tokens(struct enc *e, struct bool_enc *w)
{
	struct blk *b = e->blk;
	int nblk = e->mbw * e->mbh * 6;

	for (int i = 0; i < nblk; i++, b++) {
		int pt = (i % 6) > 3;
		uint8_t *m1 = e->dccv[pt], *m2 = e->dcct[pt][b->ctx];
		uint32_t (*c1)[2] = e->c_dccv[pt], (*c2)[2] = e->c_dcct[pt][b->ctx];
		int ct = 1, k = 0;

		for (;;) {
			int l = b->lev[k];

			if (l) {
				if (!(k > 1 && ct == 0))
					PUT(c2[0], m2[0], 1);
				put_value(e, w, abs(l), m1, m2, c1, c2);
				if (w)
					be_put(w, 128, l < 0);
				ct = abs(l) > 1 ? 2 : 1;
				k++;
			} else if (k == 0) {
				/* a zero DC: no run, on to the first AC */
				PUT(c2[0], m2[0], 0);
				ct = 0;
				k = 1;
			} else {
				PUT(c2[0], m2[0], 0);
				if (k >= b->last) {
					PUT(c2[1], m2[1], 0);	/* end of block */
					break;
				}
				PUT(c2[1], m2[1], 1);
				{
					int n = k + 1, run, g = k >= 6;
					uint8_t *m3 = e->runv[g];
					uint32_t (*c3)[2] = e->c_runv[g];

					while (!b->lev[n])
						n++;
					run = n - k;
					if (run <= 8) {
						const struct path *p = &pcr_path[run];

						for (int j = 0; j < p->n; j++)
							PUT(c3[p->prob_idx[j]], m3[p->prob_idx[j]], p->bit[j]);
					} else {
						const struct path *p = &pcr_path[0];

						for (int j = 0; j < p->n; j++)
							PUT(c3[p->prob_idx[j]], m3[p->prob_idx[j]], p->bit[j]);
						for (int j = 0; j < 6; j++)
							PUT(c3[j + 8], m3[j + 8], ((run - 9) >> j) & 1);
					}
					ct = 0;
					k = n;
				}
			}
			if (k >= 64)
				break;
			{
				int cg = coeff_groups[k];

				m1 = m2 = e->ract[pt][ct][cg];
				c1 = c2 = e->c_ract[pt][ct][cg];
			}
		}
	}
}

static void derive_dcct(struct enc *e)
{
	for (int pt = 0; pt < 2; pt++)
		for (int ctx = 0; ctx < 3; ctx++)
			for (int node = 0; node < 5; node++) {
				int p = ((e->dccv[pt][node] * dccv_lc[ctx][node][0] + 128) >> 8) +
					dccv_lc[ctx][node][1];

				e->dcct[pt][ctx][node] = p < 1 ? 1 : p > 255 ? 255 : p;
			}
}

static int dcct_of(int dccv, int ctx, int node)
{
	int p = ((dccv * dccv_lc[ctx][node][0] + 128) >> 8) + dccv_lc[ctx][node][1];

	return p < 1 ? 1 : p > 255 ? 255 : p;
}

/* the coefficient models of a key frame: chosen, and written into p1 */
static void models(struct enc *e)
{
	struct bool_enc *w = &e->p1;
	int def_prob[11];
	const int upd_cost = 7 * 256;

	for (int i = 0; i < 11; i++)
		def_prob[i] = 128;

	/* DC: nodes 0..4 are used through dcct (3 contexts), 5..10 directly */
	for (int pt = 0; pt < 2; pt++)
		for (int node = 0; node < 11; node++) {
			int64_t keep, best = -1;
			int bp = def_prob[node];

			if (node < 5) {
				keep = 0;
				for (int ctx = 0; ctx < 3; ctx++)
					keep += bits_cost(dcct_of(def_prob[node], ctx, node), e->c_dcct[pt][ctx][node]);
				for (int v = 0; v < 128; v++) {
					int p = v ? v << 1 : 1;
					int64_t c = 0;

					for (int ctx = 0; ctx < 3; ctx++)
						c += bits_cost(dcct_of(p, ctx, node), e->c_dcct[pt][ctx][node]);
					if (best < 0 || c < best) {
						best = c;
						bp = p;
					}
				}
			} else {
				keep = bits_cost(def_prob[node], e->c_dccv[pt][node]);
				bp = best_prob(e->c_dccv[pt][node], &best);
			}
			if (best + upd_cost + cost0[256 - dccv_pct[pt][node]] <
			    keep + cost0[dccv_pct[pt][node]] && bp != def_prob[node]) {
				be_put(w, dccv_pct[pt][node], 1);
				be_bits(w, bp >> 1, 7);
				def_prob[node] = bp;
			} else {
				be_put(w, dccv_pct[pt][node], 0);
			}
			e->dccv[pt][node] = (uint8_t)def_prob[node];
		}

	be_put(w, 128, 0);	/* the default coefficient order */

	for (int cg = 0; cg < 2; cg++)
		for (int node = 0; node < 14; node++) {
			int64_t keep = bits_cost(def_runv_coeff_model[cg][node], e->c_runv[cg][node]), best;
			int bp = best_prob(e->c_runv[cg][node], &best);

			if (best + upd_cost + cost0[256 - runv_pct[cg][node]] <
			    keep + cost0[runv_pct[cg][node]] && bp != def_runv_coeff_model[cg][node]) {
				be_put(w, runv_pct[cg][node], 1);
				be_bits(w, bp >> 1, 7);
				e->runv[cg][node] = (uint8_t)bp;
			} else {
				be_put(w, runv_pct[cg][node], 0);
				e->runv[cg][node] = def_runv_coeff_model[cg][node];
			}
		}

	for (int ct = 0; ct < 3; ct++)
		for (int pt = 0; pt < 2; pt++)
			for (int cg = 0; cg < 6; cg++)
				for (int node = 0; node < 11; node++) {
					uint32_t *cnt = e->c_ract[pt][ct][cg][node];
					int64_t keep = bits_cost(def_prob[node], cnt), best;
					int bp = best_prob(cnt, &best);
					int pct = ract_pct[ct][pt][cg][node];

					if (best + upd_cost + cost0[256 - pct] < keep + cost0[pct] &&
					    bp != def_prob[node]) {
						be_put(w, pct, 1);
						be_bits(w, bp >> 1, 7);
						def_prob[node] = bp;
					} else {
						be_put(w, pct, 0);
					}
					e->ract[pt][ct][cg][node] = (uint8_t)def_prob[node];
				}
	derive_dcct(e);
}

/* one key frame of the picture in e->y/u/v; returns its size */
static size_t encode_frame(struct enc *e, uint8_t **out)
{
	static uint8_t *frame;
	static size_t cap;
	size_t n;

	code_blocks(e);

	/* first the statistics with any probabilities (only counted) */
	memset(e->c_dccv, 0, sizeof(e->c_dccv));
	memset(e->c_dcct, 0, sizeof(e->c_dcct));
	memset(e->c_ract, 0, sizeof(e->c_ract));
	memset(e->c_runv, 0, sizeof(e->c_runv));
	memset(e->dccv, 128, sizeof(e->dccv));
	memset(e->ract, 128, sizeof(e->ract));
	memcpy(e->runv, def_runv_coeff_model, sizeof(e->runv));
	derive_dcct(e);
	tokens(e, NULL);

	be_init(&e->p1);
	be_bits(&e->p1, 0, 2);		/* scaling mode */
	be_put(&e->p1, 128, 0);		/* no Huffman coefficients */
	models(e);
	be_flush(&e->p1);

	be_init(&e->p2);
	tokens(e, &e->p2);
	be_flush(&e->p2);

	n = 8 + e->p1.len + e->p2.len;
	if (8 + e->p1.len > 0xffff) {
		fprintf(stderr, "vp6enc: first partition too big\n");
		exit(1);
	}
	if (n > cap) {
		cap = n * 2;
		frame = realloc(frame, cap);
		if (!frame) {
			perror("vp6enc");
			exit(1);
		}
	}
	frame[0] = (uint8_t)(e->q << 1 | 1);	/* key frame, quantiser, separate coefficients */
	frame[1] = 6 << 3;			/* VP6.0, simple profile, progressive */
	frame[2] = (uint8_t)((8 + e->p1.len) >> 8);
	frame[3] = (uint8_t)(8 + e->p1.len);
	frame[4] = (uint8_t)e->mbh;
	frame[5] = (uint8_t)e->mbw;
	frame[6] = (uint8_t)e->mbh;
	frame[7] = (uint8_t)e->mbw;
	memcpy(frame + 8, e->p1.buf, e->p1.len);
	memcpy(frame + 8 + e->p1.len, e->p2.buf, e->p2.len);
	*out = frame;
	return n;
}

/* ---- the EA container ---- */

static uint32_t rl32(const uint8_t *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static void wl32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

/*
 * Video chunks in IN: all of them, and those after the audio's end chunk
 * (SCEl/SEND/SEEN). FFmpeg's demuxer stops at that chunk, so it decodes
 * only the frames before it (Most Wanted's attract movie has 6 after).
 */
static void count_video(FILE *in, uint32_t *all, uint32_t *after_end)
{
	uint8_t h[8];
	int ended = 0;

	*all = *after_end = 0;
	while (fread(h, 1, 8, in) == 8) {
		uint32_t size = rl32(h + 4);

		if (size < 8 || fseek(in, size - 8, SEEK_CUR))
			break;
		if (!memcmp(h, "SCEl", 4) || !memcmp(h, "SEND", 4) || !memcmp(h, "SEEN", 4))
			ended = 1;
		if (!memcmp(h, "MV0K", 4) || !memcmp(h, "MV0F", 4)) {
			++*all;
			*after_end += ended;
		}
	}
	rewind(in);
}

static void flip_plane(uint8_t *dst, const uint8_t *src, int w, int h)
{
	/* stored upside down: the input's last row becomes row 0 */
	for (int y = 0; y < h; y++)
		memcpy(dst + (size_t)(h - 1 - y) * w, src + (size_t)y * w, w);
}

/* the next yuv420p frame of stdin: 1, or 0 at its end, -1 cut short */
static int read_frame(struct enc *e)
{
	static uint8_t *raw;
	size_t ys = (size_t)e->w * e->h, n = ys * 3 / 2, got;

	if (!raw && !(raw = malloc(n))) {
		perror("vp6enc");
		exit(1);
	}
	got = fread(raw, 1, n, stdin);
	if (got != n)
		return got ? -1 : 0;
	flip_plane(e->y, raw, e->w, e->h);
	flip_plane(e->u, raw + ys, e->w / 2, e->h / 2);
	flip_plane(e->v, raw + ys + ys / 4, e->w / 2, e->h / 2);
	return 1;
}

int main(int argc, char **argv)
{
	struct enc e = { 0 };
	FILE *in, *out;
	uint8_t hdr[8], *buf = NULL, mvhd[32];
	size_t cap = 0;
	long mvhd_pos = -1;
	uint32_t frames = 0, largest = 0, all, after_end, repeated = 0;
	uint64_t total = 0;

	if (argc != 6) {
		fprintf(stderr, "usage: vp6enc IN.vp6 OUT.vp6 WIDTH HEIGHT QUANT < frames.yuv420p\n");
		return 2;
	}
	e.w = atoi(argv[3]);
	e.h = atoi(argv[4]);
	e.q = atoi(argv[5]);
	if (e.w <= 0 || e.h <= 0 || e.w % 16 || e.h % 16 || e.w > 4080 || e.h > 4080 ||
	    e.q < 0 || e.q > 63) {
		fprintf(stderr, "vp6enc: WIDTH and HEIGHT multiples of 16 (<= 4080), QUANT 0..63\n");
		return 2;
	}
	e.mbw = e.w / 16;
	e.mbh = e.h / 16;
	e.y = malloc((size_t)e.w * e.h);
	e.u = malloc((size_t)e.w * e.h / 4);
	e.v = malloc((size_t)e.w * e.h / 4);
	e.blk = malloc(sizeof(*e.blk) * e.mbw * e.mbh * 6);
	if (!e.y || !e.u || !e.v || !e.blk) {
		perror("vp6enc");
		return 1;
	}
	for (int k = 0; k < 8; k++)
		for (int x = 0; x < 8; x++)
			e.cos_t[k][x] = (k ? sqrt(2.0 / 8) : sqrt(1.0 / 8)) *
					cos((2 * x + 1) * k * M_PI / 16);
	index_to_pos_init(&e);
	init_costs();
	for (int s = 0; s < 6; s++)
		tree_path(pc_tree, 0, s, &pc_path[s]);
	for (int s = 0; s < 9; s++)
		tree_path(pcr_tree, 0, s, &pcr_path[s]);

	in = fopen(argv[1], "rb");
	if (!in) {
		fprintf(stderr, "vp6enc: %s: %s\n", argv[1], strerror(errno));
		return 1;
	}
	count_video(in, &all, &after_end);
	out = fopen(argv[2], "wb");
	if (!out) {
		fprintf(stderr, "vp6enc: %s: %s\n", argv[2], strerror(errno));
		return 1;
	}
	while (fread(hdr, 1, 8, in) == 8) {
		uint32_t size = rl32(hdr + 4);

		if (size < 8 || size > (1u << 28)) {
			fprintf(stderr, "vp6enc: %s: bad chunk size %u at %ld\n", argv[1], size, ftell(in) - 8);
			return 1;
		}
		size -= 8;
		if (size > cap) {
			cap = size;
			buf = realloc(buf, cap);
			if (!buf) {
				perror("vp6enc");
				return 1;
			}
		}
		if (fread(buf, 1, size, in) != size) {
			fprintf(stderr, "vp6enc: %s: truncated chunk\n", argv[1]);
			return 1;
		}
		if (!memcmp(hdr, "MVhd", 4)) {
			if (size != 24 || mvhd_pos >= 0) {
				fprintf(stderr, "vp6enc: %s: unexpected MVhd\n", argv[1]);
				return 1;
			}
			memcpy(mvhd, hdr, 8);
			memcpy(mvhd + 8, buf, 24);
			mvhd[12] = (uint8_t)e.w;
			mvhd[13] = (uint8_t)(e.w >> 8);
			mvhd[14] = (uint8_t)e.h;
			mvhd[15] = (uint8_t)(e.h >> 8);
			mvhd_pos = ftell(out);
			fwrite(mvhd, 1, 32, out);
		} else if (!memcmp(hdr, "MV0K", 4) || !memcmp(hdr, "MV0F", 4)) {
			uint8_t *f, h8[8];
			size_t n;

			if (repeated) {
				repeated++;	/* the last picture again */
			} else {
				int r = read_frame(&e);

				if (r < 0 || (!r && (!frames || frames != all - after_end))) {
					fprintf(stderr, "vp6enc: input ended at frame %u%s (the movie has %u)\n",
						frames, r < 0 ? " in the middle" : "", all);
					return 1;
				}
				if (!r)
					repeated = 1;	/* the planes still hold the last one */
			}
			n = encode_frame(&e, &f);
			memcpy(h8, "MV0K", 4);
			wl32(h8 + 4, (uint32_t)n + 8);
			fwrite(h8, 1, 8, out);
			fwrite(f, 1, n, out);
			frames++;
			total += n;
			if (n > largest)
				largest = (uint32_t)n;
		} else if (!memcmp(hdr, "AVhd", 4) || !memcmp(hdr, "AV0K", 4) || !memcmp(hdr, "AV0F", 4)) {
			fprintf(stderr, "vp6enc: %s: movies with alpha are not handled\n", argv[1]);
			return 1;
		} else {
			fwrite(hdr, 1, 8, out);
			fwrite(buf, 1, size, out);
		}
	}
	if (fgetc(stdin) != EOF) {
		fprintf(stderr, "vp6enc: more input frames than the movie's %u\n", frames);
		return 1;
	}
	if (mvhd_pos < 0) {
		fprintf(stderr, "vp6enc: %s: no MVhd\n", argv[1]);
		return 1;
	}
	if (rl32(mvhd + 16) != frames)
		fprintf(stderr, "vp6enc: note: MVhd says %u frames, the movie has %u\n", rl32(mvhd + 16), frames);
	/* the header's largest frame */
	wl32(mvhd + 20, largest);
	fseek(out, mvhd_pos, SEEK_SET);
	fwrite(mvhd, 1, 32, out);
	if (fclose(out)) {
		fprintf(stderr, "vp6enc: %s: %s\n", argv[2], strerror(errno));
		return 1;
	}
	fclose(in);
	fprintf(stderr, "vp6enc: %u frames (%u after the audio's end: the last picture again), "
		"average %llu bytes, largest %u\n", frames, repeated,
		frames ? (unsigned long long)(total / frames) : 0ULL, largest);
	return 0;
}
