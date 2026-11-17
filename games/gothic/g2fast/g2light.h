/*
 * g2light.h: what g2fast.c (the game's 32-bit Windows side) and g2light.c
 * (the GO Ultra's 64-bit Unix side, called through Wine's unixbridge) both
 * know: the calls and their arguments. Every field is 32 bits wide, so the
 * layout is the same on both sides; addresses are the game's.
 */
#ifndef G2LIGHT_H
#define G2LIGHT_H

#include <stdint.h>

/* unixbridge_call codes */
#define G2L_INIT	0	/* args: struct g2l_init; returns 0 when the library is the one g2fast was built with */
#define G2L_LEAF	1	/* args: struct g2l_leaf; returns 1 when the engine must render polygon `stop` */
#define G2L_JOIN	2	/* no args: the colours the worker threads computed, written to the polygons */

#define G2L_VERSION	2

struct g2l_init {
	uint32_t version;	/* G2L_VERSION */
	uint32_t size;		/* sizeof(struct g2l_leaf) */
	uint32_t workers;	/* threads wanted for the lighting (0: in the engine's thread), then the threads made */
};

/* A BSP leaf's polygons, as zCBspBase::RenderNodeOutdoor's loop renders
 * them (zCPolygon::RenderPoly with zCPolygon::LightClippedPoly), from
 * polygon `start` on. Portal polygons are left to the engine's loop
 * (`portals` set); a polygon the engine must render itself (its RenderPoly)
 * stops the walk with 1 and its index in `stop`; else the walk ends with 0
 * (`stop` is the polygon count, or the polygon that ends the engine's loop).
 * With worker threads the colours come later: G2L_JOIN before the engine
 * reads them (zCRenderManager::Flush). */
struct g2l_leaf {
	uint32_t leaf;		/* zCBspLeaf* */
	uint32_t start;
	uint32_t stop;
	uint32_t portals;
	/* G2FAST_CHECK=1: the polygons lit here, for the engine's lighting to be
	 * compared, and those found facing away, with their frame and flags
	 * before, for the engine to test them again */
	uint32_t lit_polys;	/* uint32_t[lit_max], 0 for none */
	uint32_t lit_max;
	uint32_t lit;
	uint32_t back_polys;	/* uint32_t[3 * back_max]: polygon, frame, flags */
	uint32_t back_max;
	uint32_t back;
	/* G2FAST_STATS=1: counted up here, cleared by g2fast */
	uint32_t n_lit, n_back, n_engine, n_done;
	uint32_t n_sync;	/* of n_lit: lit in the engine's thread although workers run */
	uint32_t n_occluder, n_wave, n_grow;	/* of n_engine: why */
	uint32_t n_join_wait;	/* G2L_JOIN calls that waited for the workers */
};

#endif
