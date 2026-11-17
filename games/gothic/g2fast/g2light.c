/*
 * g2light: the world polygons of a BSP leaf of Gothic II 2.6 rendered
 * natively on the GO Ultra (aarch64), where the game itself runs emulated
 * (Box64 under Wine). A Unix library, loaded through Wine's unixbridge by
 * g2fast (g2fast.c), which calls it for each leaf the engine renders
 * outdoors (zCBspBase::RenderNodeOutdoor).
 *
 * Outdoors the engine relights every visible polygon every frame: its
 * camera light (cameraLightRange, 5000 in an outdoor world) keeps the
 * shortcut for a polygon lit the frame before from ever being taken. That
 * lighting (zCPolygon::LightClippedPoly with the light maps' lookups) and
 * the polygon's way to its material's list (zCPolygon::RenderPoly) were a
 * fifth of the main thread in the city of Archolos at night, in x87 code
 * that the emulator runs slowly.
 *
 * The colours can be computed by worker threads (G2L_INIT's `workers`):
 * each polygon lit becomes a job, the threads compute its vertex colours
 * into the job, and at G2L_JOIN (before the engine's Flush reads them)
 * the engine's thread writes them to the vertices in the order the engine
 * lights the polygons, so a vertex shared by polygons ends up with the
 * colour of the last one, as with the engine. The threads touch none of
 * the game's memory for writing and the engine's thread none of theirs
 * while they work: a fault in a thread Wine does not know would end the
 * game.
 *
 * Here that work is the engine's, step by step, on the game's own data:
 * the same tests, the same lists in the same order, and the same
 * arithmetic, as the emulator does the x87 one: what the engine keeps on
 * the x87 stack is a double here, what it stores to memory a float, and
 * fistp rounds to even. Whatever this code does not do (a portal polygon,
 * an animated water polygon, a list that must grow, a polygon to clip) is
 * left to the engine: g2fast calls the engine's own code for it.
 *
 * Addresses and layouts are those of Gothic2.exe 2.6 (Steam's "Gold
 * Classic", which Archolos uses too); g2fast checks the program's code
 * before it calls here, and G2L_INIT checks the constants used here.
 */
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <linux/futex.h>
#include <sys/syscall.h>
#include <unistd.h>

#include "g2light.h"

typedef uint32_t u32;
typedef uint8_t u8;

/* ---- Gothic2.exe 2.6 ------------------------------------------------- */

#define BSP_FRAME_CTR	0x008d4944	/* bspFrameCtr */
#define ACT_BSP_TREE	0x008d4978	/* the BSP tree rendered */
#define  TREE_MODE	0x5c		/*   0: outdoor */
#define LIGHTS		0x008d4938	/* the leaf's lights: zCArray<zCVobLight*>, as CollectNodeLights made them */
#define LIGHTS_N	0x008d4940
#define LIGHTS2		0x008d496c	/* ... and those flagged at +0x166 */
#define LIGHTS2_N	0x008d4974
#define SKY		0x0099ac8c	/* zCSkyControler::s_activeSkyControler */
#define  SKY_CLUT	0x24		/*   u32[256]: static light to colour */
#define  SKY_LIGHT	0x28		/*   float: the clouds' shadows */
#define  SKY_CHANGED	0x2c
#define TOTAL_TIME	0x0099b3dc	/* ztimer.totalTimeFloat */
#define CAM_LIGHT	0x0089ebb4	/* playerLightInt (cameraLightRange) */
#define ACTIVE_CAM	0x008d7f94	/* zCCamera::activeCam */
#define  CAM_VOB	0x920
#define CAM_POS_X	0x008d7f88	/* the camera's position for backface tests */
#define CAM_POS_Y	0x008d7f8c
#define CAM_POS_Z	0x008d7f90
#define WAVE_ANIS	0x008a8abc	/* zCWorld::s_bWaveAnisEnabled */
#define RENDERMAN	0x0099aa44	/* zrenderMan: its frame stamp */
#define RENDERMAN_MATS	0x0099aa48	/*   zCArray<zCMaterial*>: the materials used this frame */
#define SIN_SCALE	0x008304b4	/* zSinApprox: argument scale */
#define SIN_TABLE	0x00833628	/*   float[6284] */
#define SIN_N		6284
#define SIN_OFFSET	0x5fef26

/* the constants used here, as the program holds them */
static const struct {
	u32 addr;
	u32 lo, hi;
} constants[] = {
	{ 0x008304ec, 0x3a03126f },		/* 0.0005f: the clouds' time scale */
	{ 0x00831bcc, 0xba83126f },		/* -0.001f: ... x */
	{ 0x00831bd0, 0xbb09a027 },		/* -0.0021f: ... z */
	{ 0x0082f1b0, 0x3ecccccd },		/* 0.4f */
	{ 0x0082ed70, 0x3f800000 },		/* 1.0f */
	{ 0x0082f5f8, 0x437f0000 },		/* 255.0f */
	{ 0x0082e8ac, 0x00000000 },		/* 0.0f */
	{ 0x00830090, 0x42480000 },		/* 50.0f: the least camera light */
	{ 0x0082eb38, 0x00000000, 0x3fb00000 },	/* 0.0625: the distance's estimate */
	{ 0x0082eb30, 0x00000000, 0x3fd00000 },	/* 0.25 */
	{ 0x0082eb28, 0x00000000, 0x3fc00000 },	/* 0.125 */
};

#define CLOUD_T		0.0005f
#define CLOUD_X		-0.001f
#define CLOUD_Z		-0.0021f
#define CLOUD_K		0.4f
#define DIST_MAX	0.0625
#define DIST_MID	0.25
#define DIST_MIN	0.125

/* zCPolygon */
#define POLY_VERTS	0x00	/* zCVertex** */
#define POLY_FRAME	0x04	/* last frame rendered */
#define POLY_PLANE_D	0x08
#define POLY_PLANE_N	0x0c	/* x, y, z */
#define POLY_MATERIAL	0x18
#define POLY_LIGHTMAP	0x1c
#define POLY_FEATS	0x2c	/* zCVertFeature** */
#define POLY_NVERTS	0x30	/* u8 */
#define POLY_FLAGS	0x31	/* u8: 3 portal, 4 occluder, 8 ends the leaf, 0x10 relight, 0x80 no light change */
/* zCVertex: x, y, z; zCVertFeature: */
#define FEAT_NORMAL	0x00
#define FEAT_STAT	0x0c	/* u32 colour; byte 0xe scales the clouds, byte 0xf 99: by the CLUT */
#define FEAT_DYN	0x10	/* u32 colour: what is drawn */
/* zCMaterial */
#define MAT_POLYS	0x24	/* zCArray<zCPolygon*> */
#define MAT_STAMP	0x30
#define MAT_LMFLAGS	0x70
#define MAT_FLAGS	0x78	/* bit 0: lit by a fixed grey */
#define MAT_WAVE	0x7c
/* zCVobLight */
#define VOB_POS_X	0x48
#define VOB_POS_Y	0x58
#define VOB_POS_Z	0x68
#define LIGHT_COLOR	0x140	/* 3 bytes, added to the feature's bytes 0x10..0x12 */
#define LIGHT_RANGE	0x144
#define LIGHT_INV_RANGE	0x148
#define LIGHT_POLYS	0x168	/* zTRayTurboValMap<zCPolygon*, int>: buckets, -, count; node: key, ..., next at 0xc */
/* zCBspLeaf */
#define LEAF_POLYS	0x1c
#define LEAF_NPOLYS	0x20
/* zCArray */
#define ARR_DATA	0
#define ARR_ALLOC	4
#define ARR_N		8

static inline u32 rd32(u32 a) { return *(const u32 *)(uintptr_t)a; }
static inline int rdi(u32 a) { return *(const int32_t *)(uintptr_t)a; }
static inline float rdf(u32 a) { return *(const float *)(uintptr_t)a; }
static inline u8 rd8(u32 a) { return *(const u8 *)(uintptr_t)a; }
static inline void wr32(u32 a, u32 v) { *(u32 *)(uintptr_t)a = v; }
static inline void wr8(u32 a, u8 v) { *(u8 *)(uintptr_t)a = v; }

static inline u32 fbits(float f)
{
	u32 u;

	memcpy(&u, &f, 4);
	return u;
}

/* a vertex colour computed: the bytes the engine writes */
static inline u8 col8(u32 c, unsigned b) { return (u8)(c >> (8 * b)); }
static inline u32 col_set8(u32 c, unsigned b, u8 v) { return (c & ~(0xffu << (8 * b))) | ((u32)v << (8 * b)); }

/* fistp with the x87's rounding (to nearest, ties to even); a NaN or a
 * value out of range gives the x87's "integer indefinite" */
static inline int fistp(double v)
{
	v = __builtin_roundeven(v);
	if (!(v >= -2147483648.0 && v < 2147483648.0))
		return INT32_MIN;
	return (int)v;
}

/* x87 compares: fcom/fcomp, then the flags tested */
static inline int x87_less(double a, double b) { return a < b; }	/* C0 alone set (ordered) */

static float sin_approx(float x)
{
	float y = (float)((double)x * (double)rdf(SIN_SCALE));
	int i = (int)((u32)fistp(y) + SIN_OFFSET);

	return rdf(SIN_TABLE + 4 * (i % SIN_N));
}

/* zTRayTurboValMap<zCPolygon*, int>::GetNode != NULL */
static int in_light(u32 light, u32 poly)
{
	u32 map = light + LIGHT_POLYS;
	u32 count = rd32(map + 8), node;

	if ((int)count <= 0)
		return 0;
	for (node = rd32(rd32(map) + 4 * ((poly >> 4) % count)); node; node = rd32(node + 0xc))
		if (rd32(node) == poly)
			return 1;
	return 0;
}

/* (i * c) >> 8 as imul and sar do it */
static inline int scale8(int i, int c)
{
	return (int)((u32)i * (u32)c) >> 8;
}

static inline u8 add_clamp(u8 old, int add)
{
	int v = old + add;

	return v > 0xff ? 0xff : (u8)v;
}

/* the largest of |a|, |b|, |c| and the (float) sum of the two others, as
 * the engine sorts them: `m` held on the x87 stack (here a double), the
 * others stored as floats and swapped in when larger */
static inline void sort3(double m, float b, float c, double *max, float *rest)
{
	float t;

	if (x87_less(m, b)) {
		t = (float)m;
		m = b;
		b = t;
	}
	if (x87_less(m, c)) {
		t = (float)m;
		m = c;
		c = t;
	}
	*max = m;
	*rest = (float)((double)c + (double)b);
}

/* the leaf's lights, as zCBspBase::CollectNodeLights listed them */
#define MAX_LIGHTS 64
struct lights {
	u32 l1[MAX_LIGHTS], l2[MAX_LIGHTS];
	int n1, n2;
};

/* the dynamic lights of a list (both lists of the leaf the same way) */
static void light_list(u32 poly, const u32 *list, int n_lights, u32 verts, u32 feats, unsigned nv, u32 *out)
{
	int j;
	unsigned k;

	for (j = 0; j < n_lights; j++) {
		u32 l = list[j];
		float lx, ly, lz, inv;
		u32 range;
		int c0, c1, c2;

		if (!in_light(l, poly))
			continue;
		lx = rdf(l + VOB_POS_X);
		ly = rdf(l + VOB_POS_Y);
		lz = rdf(l + VOB_POS_Z);
		inv = rdf(l + LIGHT_INV_RANGE);
		range = rd32(l + LIGHT_RANGE);
		c0 = rd8(l + LIGHT_COLOR);
		c1 = rd8(l + LIGHT_COLOR + 1);
		c2 = rd8(l + LIGHT_COLOR + 2);
		for (k = nv; k-- > 0;) {
			u32 v = rd32(verts + 4 * k), f = rd32(feats + 4 * k);
			double dx = (double)rdf(v) - lx, dy = (double)rdf(v + 4) - ly, dz = (double)rdf(v + 8) - lz;
			double m, dot, ndl;
			float rest, dist, val;
			int i;

			sort3(fabs(dx), (float)fabs(dy), (float)fabs(dz), &m, &rest);
			dist = (float)(((m - DIST_MAX * m) + (double)rest * DIST_MID) + (double)rest * DIST_MIN);
			if (fbits(dist) > range)
				continue;
			dot = (dz * rdf(f + FEAT_NORMAL + 8) + dy * rdf(f + FEAT_NORMAL + 4)) + dx * rdf(f + FEAT_NORMAL);
			ndl = -(dot / dist);
			if (ndl < 0.0)
				continue;
			val = (float)((1.0 - (double)dist * inv) * ndl * 255.0);
			i = fistp(val);
			out[k] = col_set8(out[k], 2, add_clamp(col8(out[k], 2), scale8(i, c2)));
			out[k] = col_set8(out[k], 1, add_clamp(col8(out[k], 1), scale8(i, c1)));
			out[k] = col_set8(out[k], 0, add_clamp(col8(out[k], 0), scale8(i, c0)));
		}
	}
}

/* zCPolygon::LightClippedPoly after its first test (the polygon lit again
 * or not: light_needed()), the colours to out[nv]; param: RenderPoly
 * passes "the tree is not in mode 0" negated */
static void light_poly(u32 poly, u8 flags, int param, const struct lights *lights, u32 *out)
{
	u32 sky = rd32(SKY), clut = rd32(sky + SKY_CLUT);
	u32 verts = rd32(poly + POLY_VERTS), feats = rd32(poly + POLY_FEATS);
	unsigned nv = rd8(poly + POLY_NVERTS), k;
	double cam;

	/* the static light */
	if (clut) {
		float sl = rdf(sky + SKY_LIGHT);

		if (rd8(rd32(poly + POLY_MATERIAL) + MAT_FLAGS) & 1) {
			for (k = 0; k < nv; k++)
				out[k] = 0xffc8c8c8;
		} else if (!(sl <= 0.0f) && !(flags & 8)) {
			float t = (float)((double)rdf(TOTAL_TIME) * (double)CLOUD_T);

			for (k = 0; k < nv; k++) {
				u32 v = rd32(verts + 4 * k), f = rd32(feats + 4 * k);
				float arg = (float)(((double)rdf(v) * CLOUD_X + (double)rdf(v + 8) * CLOUD_Z) + t);
				float s = sin_approx(arg);
				float r = (float)((1.0 - ((double)s + 1.0) * (double)CLOUD_K * sl) * 255.0);
				int i = fistp(r);

				out[k] = rd32(clut + 4 * scale8(rd8(f + FEAT_STAT + 2), i));
			}
		} else if (rd32(poly + POLY_LIGHTMAP) && !param) {
			for (k = 0; k < nv; k++) {
				u32 f = rd32(feats + 4 * k), c = rd32(f + FEAT_STAT);

				if (rd8(f + FEAT_STAT + 3) == 0x63)
					out[k] = rd32(clut + 4 * (c & 0xff)) & 0x00ffffff;
				else
					out[k] = c;
			}
		} else {
			k = 0;
			do {
				u32 f = rd32(feats + 4 * k);

				out[k] = rd32(clut + 4 * (rd32(f + FEAT_STAT) & 0xff));
			} while (++k < nv);
		}
	} else if (rd32(poly + POLY_LIGHTMAP) && !param) {
		for (k = 0; k < nv; k++)
			out[k] = 0xff000000;
	} else {
		for (k = 0; k < nv; k++)
			out[k] = rd32(rd32(feats + 4 * k) + FEAT_STAT);
	}
	if (flags & 3)
		return;

	/* the leaf's lights */
	light_list(poly, lights->l1, lights->n1, verts, feats, nv, out);
	light_list(poly, lights->l2, lights->n2, verts, feats, nv, out);

	/* the camera's light */
	cam = (double)rdi(CAM_LIGHT);
	if (!(cam > 50.0))
		return;
	{
		u32 vob = rd32(rd32(ACTIVE_CAM) + CAM_VOB);
		float cx = rdf(vob + VOB_POS_X), cy = rdf(vob + VOB_POS_Y), cz = rdf(vob + VOB_POS_Z);
		float r2 = (float)(cam * cam);

		for (k = nv; k-- > 0;) {
			u32 v = rd32(verts + 4 * k), f = rd32(feats + 4 * k);
			float dx = (float)((double)rdf(v) - cx), dy = (float)((double)rdf(v + 4) - cy);
			double dzd = (double)rdf(v + 8) - cz;
			float dz = (float)dzd, rest, val;
			double acc, att, m, dot, dist, ndl;
			int i;

			acc = dzd * dz;
			acc = acc + (double)dy * dy;
			acc = acc + (double)dx * dx;
			if (acc > r2)
				continue;
			att = 1.0 - acc / r2;
			sort3(fabs((double)dx), fabsf(dy), fabsf(dz), &m, &rest);
			dot = ((double)dz * rdf(f + FEAT_NORMAL + 8) + (double)dy * rdf(f + FEAT_NORMAL + 4)) +
			      (double)dx * rdf(f + FEAT_NORMAL);
			dist = ((m - m * DIST_MAX) + (double)rest * DIST_MID) + (double)rest * DIST_MIN;
			ndl = -(dot / dist);
			if (ndl < 0.0)
				continue;
			val = (float)(ndl * att * 255.0);
			i = fistp(val);
			out[k] = col_set8(out[k], 2, add_clamp(col8(out[k], 2), i));
			out[k] = col_set8(out[k], 1, add_clamp(col8(out[k], 1), i));
			out[k] = col_set8(out[k], 0, add_clamp(col8(out[k], 0), i));
		}
	}
}

/* LightClippedPoly's first test: a polygon lit the frame before, and
 * nothing changed, keeps its colours (the flag 0x10, cleared, asks for
 * the lighting). `flags` is updated. */
static int light_needed(u32 poly, u8 *flags, int frame)
{
	if (*flags & 0x10) {
		*flags &= ~0x10;
		wr8(poly + POLY_FLAGS, *flags);
		return 1;
	}
	return !(rdi(poly + POLY_FRAME) == frame - 1 && (*flags & 0x80) && !rdi(rd32(SKY) + SKY_CHANGED) &&
		 !rdi(LIGHTS2_N) && (double)rdi(CAM_LIGHT) < 50.0);
}

static void lights_snapshot(struct lights *l)
{
	u32 a1 = rd32(LIGHTS), a2 = rd32(LIGHTS2);
	int i;

	l->n1 = rdi(LIGHTS_N);
	l->n2 = rdi(LIGHTS2_N);
	if (l->n1 > MAX_LIGHTS || l->n2 > MAX_LIGHTS || l->n1 < 0 || l->n2 < 0) {
		l->n1 = l->n2 = -1;	/* too many: the engine's lighting */
		return;
	}
	for (i = 0; i < l->n1; i++)
		l->l1[i] = rd32(a1 + 4 * i);
	for (i = 0; i < l->n2; i++)
		l->l2[i] = rd32(a2 + 4 * i);
}

/* ---- the worker threads ----------------------------------------------- */

#define MAX_NV		8	/* a polygon's vertices lit by a thread (more: in the engine's thread) */
#define MAX_JOBS	65536	/* polygons lit by the threads a frame */
#define MAX_LEAVES	4096	/* leaves' light lists a frame */
#define CHUNK		16	/* jobs a thread takes at once */

struct job {
	u32 poly;
	u32 flags;		/* after light_needed() */
	u32 nv;
	u32 lights;		/* index into leaf_lights */
	u32 colour[MAX_NV];
};

static struct job *jobs;
static struct lights *leaf_lights;
static unsigned n_workers;
static int tree_param;		/* light_poly's param, for the frame */
static int cur_frame = -1;
static unsigned n_leaves;	/* leaf_lights used this frame */
static unsigned join_pos;	/* jobs whose colours were written */
static u32 n_jobs;		/* jobs made this frame (the threads read it) */
static u32 next_job;		/* taken by the threads */
static u32 done_jobs;		/* finished by the threads */
static u32 active;		/* a frame's lighting is on: the threads look for jobs */

static long futex(u32 *addr, int op, u32 val)
{
	return syscall(SYS_futex, addr, op, val, NULL, NULL, 0);
}

static void *worker(void *arg)
{
	unsigned spins = 0;

	for (;;) {
		u32 i, n, cnt, k;

		if (!__atomic_load_n(&active, __ATOMIC_ACQUIRE)) {
			futex(&active, FUTEX_WAIT_PRIVATE, 0);
			continue;
		}
		n = __atomic_load_n(&n_jobs, __ATOMIC_ACQUIRE);
		i = __atomic_load_n(&next_job, __ATOMIC_RELAXED);
		if (i >= n) {
			/* nothing yet: the engine's thread is between leaves */
			if (++spins < 64) {
				__asm__ volatile("yield");
			} else {
				struct timespec ts = { 0, 50000 };

				nanosleep(&ts, NULL);
			}
			continue;
		}
		spins = 0;
		cnt = n - i < CHUNK ? n - i : CHUNK;
		if (!__atomic_compare_exchange_n(&next_job, &i, i + cnt, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED))
			continue;
		for (k = 0; k < cnt; k++) {
			struct job *j = &jobs[i + k];

			light_poly(j->poly, (u8)j->flags, tree_param, &leaf_lights[j->lights], j->colour);
		}
		__atomic_add_fetch(&done_jobs, cnt, __ATOMIC_RELEASE);
	}
	return arg;
}

static unsigned workers_start(unsigned wanted)
{
	sigset_t all, old;
	pthread_attr_t attr;
	unsigned i;

	if (!wanted)
		return 0;
	jobs = malloc(MAX_JOBS * sizeof(*jobs));
	leaf_lights = malloc(MAX_LEAVES * sizeof(*leaf_lights));
	if (!jobs || !leaf_lights)
		return 0;
	/* no signal of Wine's in a thread it does not know */
	sigfillset(&all);
	pthread_sigmask(SIG_BLOCK, &all, &old);
	pthread_attr_init(&attr);
	pthread_attr_setstacksize(&attr, 256 * 1024);
	pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
	for (i = 0; i < wanted; i++) {
		pthread_t t;

		if (pthread_create(&t, &attr, worker, NULL))
			break;
	}
	pthread_attr_destroy(&attr);
	pthread_sigmask(SIG_SETMASK, &old, NULL);
	n_workers = i;
	return i;
}

/* all jobs made so far finished by the threads */
static int workers_wait(void)
{
	unsigned spins = 0;
	int waited = 0;

	while (__atomic_load_n(&done_jobs, __ATOMIC_ACQUIRE) < n_jobs) {
		waited = 1;
		if (++spins < 256) {
			__asm__ volatile("yield");
		} else {
			struct timespec ts = { 0, 20000 };

			nanosleep(&ts, NULL);
		}
	}
	return waited;
}

/* a new frame: the threads' jobs of the last one must be over before
 * theirs are reused */
static void frame_begin(int frame)
{
	workers_wait();
	cur_frame = frame;
	n_jobs = next_job = done_jobs = 0;
	n_leaves = 0;
	join_pos = 0;
	tree_param = rdi(rd32(ACT_BSP_TREE) + TREE_MODE) == 0;
	if (!__atomic_exchange_n(&active, 1, __ATOMIC_RELEASE))
		futex(&active, FUTEX_WAKE_PRIVATE, 0x7fffffff);
}

/* G2L_JOIN: the colours to the vertices, in the jobs' order */
static unsigned join(struct g2l_leaf *a)
{
	unsigned waited = workers_wait();

	if (a && waited)
		a->n_join_wait++;
	while (join_pos < n_jobs) {
		struct job *j = &jobs[join_pos++];	/* before the writes: a fault skips the job */
		u32 feats = rd32(j->poly + POLY_FEATS);
		unsigned k;

		for (k = 0; k < j->nv; k++)
			wr32(rd32(feats + 4 * k) + FEAT_DYN, j->colour[k]);
	}
	__atomic_store_n(&active, 0, __ATOMIC_RELEASE);
	return 0;
}

/* A write of what is there already. The emulator keeps a page of the game
 * read-only while it holds code it has translated (in the game's heap too:
 * the code its patches allocate); a write by the game itself is caught and
 * the page made writable again, but one from here makes the call fail
 * (Wine's STATUS_ACCESS_VIOLATION) and g2fast gives the polygon to the
 * engine. So a polygon's pages are tried before anything is changed. */
static inline void probe32(u32 a)
{
	*(volatile u32 *)(uintptr_t)a = *(volatile u32 *)(uintptr_t)a;
}

static inline void probe8(u32 a)
{
	*(volatile u8 *)(uintptr_t)a = *(volatile u8 *)(uintptr_t)a;
}

/* zCArray::InsertEnd without growing */
static inline int has_room(u32 arr)
{
	return rdi(arr + ARR_ALLOC) >= rdi(arr + ARR_N) + 1;
}

static inline void push(u32 arr, u32 v)
{
	int n = rdi(arr + ARR_N);

	wr32(rd32(arr + ARR_DATA) + 4 * n, v);
	wr32(arr + ARR_N, n + 1);
}

static unsigned render_leaf(struct g2l_leaf *a)
{
	u32 leaf = a->leaf, polys = rd32(leaf + LEAF_POLYS);
	unsigned n = rd32(leaf + LEAF_NPOLYS), i;
	int frame = rdi(BSP_FRAME_CTR);
	int param = rdi(rd32(ACT_BSP_TREE) + TREE_MODE) == 0;
	u32 lit = a->lit_max ? a->lit_polys : 0;
	struct lights local, *lights = &local;
	unsigned lights_index = 0;

	if (n_workers) {
		if (frame != cur_frame)
			frame_begin(frame);
		if (n_leaves < MAX_LEAVES) {
			lights = &leaf_lights[n_leaves];
			lights_index = n_leaves++;
		}
	}
	lights_snapshot(lights);
	if (lights->n1 < 0)
		goto engine_all;

	for (i = a->start; i < n; i++) {
		u32 p = rd32(polys + 4 * i), mat, stamp, feats;
		u8 flags;
		double d;
		int new_mat;
		unsigned k;

		a->stop = i;	/* for g2fast, if a write faults */
		if (rdi(p + POLY_FRAME) == frame)
			continue;
		flags = rd8(p + POLY_FLAGS);
		if (flags & 3) {
			a->portals = 1;
			continue;
		}
		if (flags & 8)
			break;
		if (flags & 4) {
			a->n_occluder++;
			goto engine;
		}
		/* RenderPoly's backface test */
		d = (double)rdf(CAM_POS_Z) * rdf(p + POLY_PLANE_N + 8);
		d = d + (double)rdf(CAM_POS_Y) * rdf(p + POLY_PLANE_N + 4);
		d = d + (double)rdf(CAM_POS_X) * rdf(p + POLY_PLANE_N);
		if (!(d > rdf(p + POLY_PLANE_D)) && !isnan(d) && !isnan(rdf(p + POLY_PLANE_D))) {
			if (a->back_max && a->back < a->back_max) {
				u32 b = a->back_polys + 12 * a->back++;

				wr32(b, p);
				wr32(b + 4, rd32(p + POLY_FRAME));
				wr32(b + 8, flags);
			}
			/* (either write alone leaves what the engine finishes alike) */
			wr8(p + POLY_FLAGS, flags | 0x10);
			wr32(p + POLY_FRAME, frame);
			a->n_back++;
			continue;
		}
		mat = rd32(p + POLY_MATERIAL);
		if (rdi(WAVE_ANIS) && rdi(mat + MAT_WAVE)) {
			a->n_wave++;
			goto engine;	/* zCPolygon::ApplyMorphing moves its vertices */
		}
		stamp = rd32(RENDERMAN);
		new_mat = rd32(mat + MAT_STAMP) != stamp;
		if ((new_mat && !has_room(RENDERMAN_MATS)) || !has_room(mat + MAT_POLYS)) {
			a->n_grow++;
			goto engine;
		}

		probe8(p + POLY_FLAGS);
		probe32(p + POLY_FRAME);
		feats = rd32(p + POLY_FEATS);
		for (k = 0; k < rd8(p + POLY_NVERTS); k++)
			probe32(rd32(feats + 4 * k) + FEAT_DYN);
		probe32(mat + MAT_STAMP);
		probe8(mat + MAT_LMFLAGS);
		probe32(mat + MAT_POLYS + ARR_N);
		probe32(rd32(mat + MAT_POLYS + ARR_DATA) + 4 * rdi(mat + MAT_POLYS + ARR_N));
		if (new_mat) {
			probe32(RENDERMAN_MATS + ARR_N);
			probe32(rd32(RENDERMAN_MATS + ARR_DATA) + 4 * rdi(RENDERMAN_MATS + ARR_N));
		}

		/* the frame last: the engine renders a polygon without it again */
		if (light_needed(p, &flags, frame)) {
			unsigned nv = rd8(p + POLY_NVERTS);

			if (lights != &local && nv <= MAX_NV && n_jobs < MAX_JOBS) {
				struct job *j = &jobs[n_jobs];

				j->poly = p;
				j->flags = flags;
				j->nv = nv;
				j->lights = lights_index;
				__atomic_store_n(&n_jobs, n_jobs + 1, __ATOMIC_RELEASE);
			} else {
				u32 out[256];

				light_poly(p, flags, param, lights, out);
				for (k = 0; k < nv; k++)
					wr32(rd32(feats + 4 * k) + FEAT_DYN, out[k]);
				if (n_workers)
					a->n_sync++;
			}
		}
		if (new_mat) {
			push(RENDERMAN_MATS, mat);
			wr32(mat + MAT_STAMP, stamp);
		}
		push(mat + MAT_POLYS, p);
		wr8(mat + MAT_LMFLAGS, rd8(mat + MAT_LMFLAGS) | (rd32(p + POLY_LIGHTMAP) ? 0x80 : 0));
		wr32(p + POLY_FRAME, frame);
		a->n_lit++;
		if (lit && a->lit < a->lit_max)
			wr32(lit + 4 * a->lit++, p);
		continue;
engine:
		a->n_engine++;
		return 1;
	}
	a->stop = i;
	a->n_done++;
	return 0;
engine_all:
	/* more lights than foreseen: the engine renders the leaf, one polygon
	 * at a time */
	for (i = a->start; i < n; i++) {
		u32 p = rd32(polys + 4 * i);
		u8 flags = rd8(p + POLY_FLAGS);

		if (rdi(p + POLY_FRAME) == frame)
			continue;
		if (flags & 3) {
			a->portals = 1;
			continue;
		}
		if (flags & 8)
			break;
		a->stop = i;
		a->n_engine++;
		return 1;
	}
	a->stop = i;
	a->n_done++;
	return 0;
}

unsigned int unixbridge_entry(unsigned int code, void *args)
{
	switch (code) {
	case G2L_INIT: {
		struct g2l_init *in = args;
		unsigned i;

		if (in->version != G2L_VERSION || in->size != sizeof(struct g2l_leaf))
			return 1;
		for (i = 0; i < sizeof(constants) / sizeof(constants[0]); i++)
			if (rd32(constants[i].addr) != constants[i].lo ||
			    (constants[i].hi && rd32(constants[i].addr + 4) != constants[i].hi))
				return 2;
		in->workers = workers_start(in->workers);
		return 0;
	}
	case G2L_LEAF:
		return render_leaf(args);
	case G2L_JOIN:
		return n_workers ? join(args) : 0;
	}
	return ~0u;
}
