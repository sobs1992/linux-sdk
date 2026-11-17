/*
 * g2fast: a faster zCWayNet::GetNearestWaypoint for Gothic II 2.6
 * (Gothic2.exe of "Gothic II Gold", fix 2.6, as Steam and Archolos ship it).
 *
 * The engine looks for the waypoint nearest to a point by walking its whole
 * waypoint list (an L1 distance in x87 floating point per waypoint). On the
 * GO Ultra, where the game runs emulated (Box64 under Wine), that walk was a
 * quarter of the main thread in The Chronicles of Myrtana: Archolos, whose
 * world has many thousands of waypoints and whose NPCs ask often.
 *
 * Here the waypoints are put into a grid of cells over x and z once, and a
 * query looks only at the cells near the point. The answer is the one the
 * engine's walk gives: the same distance, computed as the engine computes it
 * (each coordinate's difference rounded to a float, summed z + y + x), and
 * among waypoints that close the one the walk would keep (the first in the
 * list, with the walk's float-rounded minimum). Heights (y) are read from
 * the waypoints at each query; the grid only holds x and z.
 *
 * The grid is made again when the waypoint list may have changed:
 * zCWayNet::Unarchive (a world or saved game loaded), its destructor,
 * InsertWaypoint and DeleteWaypoint are wrapped to say so, and every 256th
 * query the list is walked and compared with the grid's copy.
 *
 * This file is the DLL BugslayerUtil.dll, which Gothic2.exe loads from its
 * directory; the game's own one, renamed BugslayerUtil_orig.dll, keeps
 * doing its work (crash reports) through the forwarded exports of
 * g2fast.def. If the code at the patched addresses is not the expected
 * one (another version of the program), nothing is changed.
 *
 * Environment: G2FAST=0 leaves the game as it is; G2FAST_CHECK=1 also runs
 * the engine's walk for every query and counts the answers that differ;
 * G2FAST_STATS=1 writes counts (queries, cells looked at, grid rebuilds,
 * callers) to C:\g2fast.log every 10 seconds.
 */
#include <windows.h>
#include <stdint.h>
#include <math.h>
#include <float.h>
#include <string.h>

/* ---- Gothic2.exe 2.6 ------------------------------------------------- */

#define ADDR_GET_NEAREST   0x007ad660	/* zCWaypoint* __fastcall (zCWayNet*, zVEC3 const&) */
#define ADDR_INSERT_WP1    0x007ad100	/* void __thiscall InsertWaypoint(zCWaypoint*) */
#define ADDR_INSERT_WP3    0x007ad130	/* void __thiscall InsertWaypoint(zCWaypoint*, zCWaypoint*, zCWaypoint*) */
#define ADDR_INSERT_XYZ    0x007acff0	/* zCWaypoint* __thiscall InsertWaypoint(float, float, float) */
#define ADDR_DELETE_WP     0x007ad2b0	/* void __thiscall DeleteWaypoint(zCWaypoint*) */
#define ADDR_VTBL_WAYNET   0x0083e3d8	/* ??_7zCWayNet@@6B@ */
#define VTBL_UNARCHIVE     2		/* ?Unarchive@zCWayNet@@UAEXAAVzCArchiver@@@Z */
#define VTBL_DELETING_DTOR 3		/* ??_GzCWayNet@@UAEPAXI@Z */
#define ADDR_UNARCHIVE     0x007b2200
#define ADDR_DELETING_DTOR 0x007acce0

#define WAYNET_LIST  0x30	/* zCWayNet: first node of its waypoint list */
#define NODE_DATA    0x04	/* list node: the waypoint */
#define NODE_NEXT    0x08	/* list node: the next node */
#define WP_POS       0x44	/* zCWaypoint: position x, y, z */

/* each patched function's first bytes, copied to its trampoline */
struct patch {
	uintptr_t addr;
	unsigned char code[8];
	unsigned len;
	void *hook;
	void *tramp;
};

static unsigned char tramp_mem[5][16];

static struct patch patches[] = {
	{ ADDR_GET_NEAREST, { 0x83, 0xec, 0x10, 0x56, 0x8b, 0x71, 0x30 }, 7, NULL, NULL },	/* sub esp,10; push esi; mov esi,[ecx+30] */
	{ ADDR_INSERT_WP1,  { 0x8b, 0x41, 0x30, 0x85, 0xc0 }, 5, NULL, NULL },		/* mov eax,[ecx+30]; test eax,eax */
	{ ADDR_INSERT_WP3,  { 0x53, 0x8b, 0x5c, 0x24, 0x08 }, 5, NULL, NULL },		/* push ebx; mov ebx,[esp+8] */
	{ ADDR_INSERT_XYZ,  { 0x83, 0xec, 0x0c, 0x57, 0x8b, 0xf9 }, 6, NULL, NULL },	/* sub esp,c; push edi; mov edi,ecx */
	{ ADDR_DELETE_WP,   { 0x51, 0x8b, 0x41, 0x30, 0x53 }, 5, NULL, NULL },		/* push ecx; mov eax,[ecx+30]; push ebx */
};

typedef void *(__fastcall *get_nearest_fn)(void *waynet, const float *pos);
typedef void (__fastcall *wp1_fn)(void *waynet, void *edx, void *wp);
typedef void (__fastcall *wp3_fn)(void *waynet, void *edx, void *a, void *b, void *c);
typedef void *(__fastcall *xyz_fn)(void *waynet, void *edx, float x, float y, float z);
typedef void (__fastcall *unarchive_fn)(void *waynet, void *edx, void *arc);
typedef void *(__fastcall *dtor_fn)(void *waynet, void *edx, unsigned flags);

static volatile LONG generation = 1;	/* bumped when the list may change */

/* ---- the grid ---------------------------------------------------------- */

struct point {
	void *wp;
	float x, z;	/* binned by these */
	unsigned index;	/* place in the list */
};

static struct {
	void *waynet;
	LONG generation;
	unsigned n;		/* waypoints in the list (also those not in the grid) */
	void **nodes;		/* the list's nodes, in order, for checks */
	void **wps;
	float *xs, *zs;
	struct point *points;	/* grouped by cell */
	unsigned *cell_start;	/* nx * nz + 1 */
	unsigned nx, nz;
	float x0, z0, cell;	/* grid origin and cell size */
	unsigned capacity;
	unsigned queries_since_check;
	BOOL valid;
} grid;

static HANDLE heap;
static volatile LONG busy;
static BOOL check_mode, stats_mode;

static struct {
	unsigned queries, rebuilds, mismatches, fallbacks, points_scored, cells;
	DWORD last;
	uintptr_t callers[16];
	unsigned caller_count[16];
} stats;

static void *xalloc(size_t size)
{
	return HeapAlloc(heap, 0, size ? size : 1);
}

static void xfree(void *p)
{
	if (p)
		HeapFree(heap, 0, p);
}

static inline void *node_data(void *node)
{
	return *(void **)((char *)node + NODE_DATA);
}

static inline void *node_next(void *node)
{
	return *(void **)((char *)node + NODE_NEXT);
}

static inline const float *wp_pos(void *wp)
{
	return (const float *)((char *)wp + WP_POS);
}

static void grid_free(void)
{
	xfree(grid.nodes);
	xfree(grid.wps);
	xfree(grid.xs);
	xfree(grid.zs);
	xfree(grid.points);
	xfree(grid.cell_start);
	grid.nodes = grid.wps = NULL;
	grid.xs = grid.zs = NULL;
	grid.points = NULL;
	grid.cell_start = NULL;
	grid.capacity = 0;
	grid.valid = FALSE;
}

static inline unsigned cell_of(float v, float origin, float size, unsigned count)
{
	float c = (v - origin) / size;

	if (!(c > 0.0f))
		return 0;
	if (c >= (float)(count - 1))
		return count - 1;
	return (unsigned)c;
}

/* the grid of WAYNET's list, FALSE if it cannot be made */
static BOOL grid_build(void *waynet)
{
	void *node;
	unsigned n = 0, i, in_grid = 0, cells;
	float xmin = FLT_MAX, xmax = -FLT_MAX, zmin = FLT_MAX, zmax = -FLT_MAX;
	double area;

	grid.valid = FALSE;
	for (node = *(void **)((char *)waynet + WAYNET_LIST); node; node = node_next(node))
		n++;
	if (n > grid.capacity) {
		grid_free();
		grid.nodes = xalloc(n * sizeof(void *));
		grid.wps = xalloc(n * sizeof(void *));
		grid.xs = xalloc(n * sizeof(float));
		grid.zs = xalloc(n * sizeof(float));
		grid.points = xalloc(n * sizeof(struct point));
		if (!grid.nodes || !grid.wps || !grid.xs || !grid.zs || !grid.points) {
			grid_free();
			return FALSE;
		}
		grid.capacity = n;
	}
	i = 0;
	for (node = *(void **)((char *)waynet + WAYNET_LIST); node && i < n; node = node_next(node), i++) {
		void *wp = node_data(node);
		const float *p = wp_pos(wp);

		grid.nodes[i] = node;
		grid.wps[i] = wp;
		grid.xs[i] = p[0];
		grid.zs[i] = p[2];
		/* never nearest for the engine's walk: not in the grid */
		if (!isfinite(p[0]) || !isfinite(p[1]) || !isfinite(p[2]))
			continue;
		in_grid++;
		xmin = fminf(xmin, p[0]);
		xmax = fmaxf(xmax, p[0]);
		zmin = fminf(zmin, p[2]);
		zmax = fmaxf(zmax, p[2]);
	}
	grid.n = n;
	grid.waynet = waynet;
	grid.generation = generation;
	grid.queries_since_check = 0;

	/* about 4 waypoints a cell, at most 1024 x 1024 cells */
	if (!in_grid) {
		xmin = xmax = zmin = zmax = 0.0f;
	}
	area = ((double)xmax - xmin + 1.0) * ((double)zmax - zmin + 1.0);
	grid.cell = (float)sqrt(area / (in_grid ? in_grid : 1) * 4.0);
	if (!(grid.cell >= 100.0f))
		grid.cell = 100.0f;	/* 1 m: the engine's units are cm */
	while ((xmax - xmin) / grid.cell > 1023.0f || (zmax - zmin) / grid.cell > 1023.0f)
		grid.cell *= 2.0f;
	grid.x0 = xmin;
	grid.z0 = zmin;
	grid.nx = (unsigned)((xmax - xmin) / grid.cell) + 1;
	grid.nz = (unsigned)((zmax - zmin) / grid.cell) + 1;
	cells = grid.nx * grid.nz;
	xfree(grid.cell_start);
	if (!(grid.cell_start = xalloc((cells + 1) * sizeof(unsigned))))
		return FALSE;
	ZeroMemory(grid.cell_start, (cells + 1) * sizeof(unsigned));

	/* counting sort by cell, keeping the list order within a cell */
	for (i = 0; i < n; i++) {
		const float *p = wp_pos(grid.wps[i]);

		if (!isfinite(p[0]) || !isfinite(p[1]) || !isfinite(p[2]))
			continue;
		grid.cell_start[cell_of(p[2], grid.z0, grid.cell, grid.nz) * grid.nx +
				cell_of(p[0], grid.x0, grid.cell, grid.nx) + 1]++;
	}
	for (i = 0; i < cells; i++)
		grid.cell_start[i + 1] += grid.cell_start[i];
	{
		unsigned *fill = xalloc(cells * sizeof(unsigned));

		if (!fill)
			return FALSE;
		CopyMemory(fill, grid.cell_start, cells * sizeof(unsigned));
		for (i = 0; i < n; i++) {
			const float *p = wp_pos(grid.wps[i]);
			unsigned c;

			if (!isfinite(p[0]) || !isfinite(p[1]) || !isfinite(p[2]))
				continue;
			c = cell_of(p[2], grid.z0, grid.cell, grid.nz) * grid.nx +
			    cell_of(p[0], grid.x0, grid.cell, grid.nx);
			grid.points[fill[c]].wp = grid.wps[i];
			grid.points[fill[c]].x = p[0];
			grid.points[fill[c]].z = p[2];
			grid.points[fill[c]].index = i;
			fill[c]++;
		}
		xfree(fill);
	}
	grid.valid = TRUE;
	stats.rebuilds++;
	return TRUE;
}

/* the list as the grid knows it? (nodes, waypoints, their x and z) */
static BOOL grid_matches(void *waynet)
{
	void *node = *(void **)((char *)waynet + WAYNET_LIST);
	unsigned i;

	for (i = 0; i < grid.n; i++, node = node_next(node)) {
		const float *p;

		if (node != grid.nodes[i] || node_data(node) != grid.wps[i])
			return FALSE;
		p = wp_pos(grid.wps[i]);
		if (*(const uint32_t *)&p[0] != *(const uint32_t *)&grid.xs[i] ||
		    *(const uint32_t *)&p[2] != *(const uint32_t *)&grid.zs[i])
			return FALSE;
	}
	return node == NULL;
}

/*
 * The engine's distance: each difference computed in double (Box64 runs
 * x87 code in double precision), rounded to a float (fstp), its sign
 * dropped, then |dz| + |dy| + |dx| in double.
 */
static inline double wp_distance(const float *p, const float *q)
{
	float dx = (float)((double)p[0] - (double)q[0]);
	float dy = (float)((double)p[1] - (double)q[1]);
	float dz = (float)((double)p[2] - (double)q[2]);

	return ((double)fabsf(dz) + (double)fabsf(dy)) + (double)fabsf(dx);
}

#define MAX_CANDIDATES 256

/* the engine's choice, or (void *)-1 to fall back to the walk */
static void *grid_nearest(const float *q)
{
	struct { unsigned index; void *wp; double d; } cand[MAX_CANDIDATES];
	unsigned ncand = 0, i, j;
	unsigned cx, cz, r, rmax;
	double best = HUGE_VAL, limit = HUGE_VAL;
	float minf;
	void *chosen = NULL;

	cx = cell_of(q[0], grid.x0, grid.cell, grid.nx);
	cz = cell_of(q[2], grid.z0, grid.cell, grid.nz);
	rmax = grid.nx > grid.nz ? grid.nx : grid.nz;
	for (r = 0; r <= rmax; r++) {
		int dz;

		/* everything in ring r is at least (r - 1) cells away in x or z
		 * (1 cm more for the rounding of the binning) */
		if (r >= 2 && (double)(r - 1) * grid.cell > limit + 1.0)
			break;
		for (dz = -(int)r; dz <= (int)r; dz++) {
			int z = (int)cz + dz, dx, step;

			if (z < 0 || z >= (int)grid.nz)
				continue;
			/* the whole row on the ring's top and bottom, its two ends on the others */
			step = (dz == -(int)r || dz == (int)r) ? 1 : (r ? 2 * (int)r : 1);
			for (dx = -(int)r; dx <= (int)r; dx += step) {
				int x = (int)cx + dx;
				unsigned c, k;

				if (x < 0 || x >= (int)grid.nx)
					continue;
				c = (unsigned)z * grid.nx + (unsigned)x;
				stats.cells++;
				for (k = grid.cell_start[c]; k < grid.cell_start[c + 1]; k++) {
					const struct point *pt = &grid.points[k];
					double d = wp_distance(wp_pos(pt->wp), q);

					stats.points_scored++;
					if (!(d <= limit))
						continue;
					if (d < best) {
						best = d;
						/* within the rounding of the engine's float minimum */
						limit = best * (1.0 + 1e-6);
						/* drop those now too far */
						for (i = j = 0; i < ncand; i++)
							if (cand[i].d <= limit)
								cand[j++] = cand[i];
						ncand = j;
					}
					if (ncand == MAX_CANDIDATES)
						return (void *)-1;
					cand[ncand].index = pt->index;
					cand[ncand].wp = pt->wp;
					cand[ncand].d = d;
					ncand++;
				}
			}
		}
	}
	if (!ncand)
		return NULL;
	/* the walk over the close ones in list order, as the engine does it */
	for (i = 1; i < ncand; i++) {
		unsigned k = i;

		while (k > 0 && cand[k - 1].index > cand[k].index) {
			typeof(cand[0]) t = cand[k];

			cand[k] = cand[k - 1];
			cand[k - 1] = t;
			k--;
		}
	}
	minf = FLT_MAX;
	for (i = 0; i < ncand; i++) {
		if (cand[i].d < (double)minf) {
			minf = (float)cand[i].d;
			chosen = cand[i].wp;
		}
	}
	return chosen;
}

static void stats_caller(uintptr_t ret)
{
	unsigned i, least = 0;

	for (i = 0; i < 16; i++) {
		if (stats.callers[i] == ret) {
			stats.caller_count[i]++;
			return;
		}
		if (stats.caller_count[i] < stats.caller_count[least])
			least = i;
	}
	stats.callers[least] = ret;
	stats.caller_count[least] = 1;
}

static void stats_write(void)
{
	char line[1024];
	int len, i;
	DWORD now = GetTickCount(), written;
	HANDLE f;

	if (now - stats.last < 10000)
		return;
	len = wsprintfA(line, "%lu: %u queries, %u points scored, %u cells, %u rebuilds, %u fallbacks, %u mismatches, %u waypoints, grid %ux%u cell %d; callers",
			now, stats.queries, stats.points_scored, stats.cells, stats.rebuilds, stats.fallbacks,
			stats.mismatches, grid.n, grid.nx, grid.nz, (int)grid.cell);
	for (i = 0; i < 16; i++)
		if (stats.caller_count[i])
			len += wsprintfA(line + len, " %lx:%u", (unsigned long)stats.callers[i], stats.caller_count[i]);
	line[len++] = '\r';
	line[len++] = '\n';
	f = CreateFileA("C:\\g2fast.log", FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
			OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
	if (f != INVALID_HANDLE_VALUE) {
		WriteFile(f, line, len, &written, NULL);
		CloseHandle(f);
	}
	ZeroMemory(&stats.queries, sizeof(stats) - sizeof(stats.last) - sizeof(stats.callers) - sizeof(stats.caller_count));
	ZeroMemory(stats.caller_count, sizeof(stats.caller_count));
	stats.last = now;
}

static void *__fastcall hook_get_nearest(void *waynet, const float *q)
{
	get_nearest_fn walk = (get_nearest_fn)patches[0].tramp;
	void *wp;

	if (stats_mode) {
		stats.queries++;
		stats_caller((uintptr_t)__builtin_return_address(0));
		stats_write();
	}
	if (!isfinite(q[0]) || !isfinite(q[1]) || !isfinite(q[2]))
		return walk(waynet, q);
	if (InterlockedCompareExchange(&busy, 1, 0))
		return walk(waynet, q);	/* another thread inside: the engine's walk */
	if (!grid.valid || grid.waynet != waynet || grid.generation != generation ||
	    ++grid.queries_since_check >= 256) {
		if (!(grid.valid && grid.waynet == waynet && grid.generation == generation && grid_matches(waynet)) &&
		    !grid_build(waynet)) {
			busy = 0;
			stats.fallbacks++;
			return walk(waynet, q);
		}
		grid.queries_since_check = 0;
	}
	wp = grid_nearest(q);
	busy = 0;
	if (wp == (void *)-1) {
		stats.fallbacks++;
		return walk(waynet, q);
	}
	if (check_mode) {
		void *ref = walk(waynet, q);

		if (ref != wp) {
			stats.mismatches++;
			wp = ref;
		}
	}
	return wp;
}

static void __fastcall hook_insert_wp1(void *waynet, void *edx, void *wp)
{
	InterlockedIncrement(&generation);
	((wp1_fn)patches[1].tramp)(waynet, edx, wp);
	InterlockedIncrement(&generation);
}

static void __fastcall hook_insert_wp3(void *waynet, void *edx, void *a, void *b, void *c)
{
	InterlockedIncrement(&generation);
	((wp3_fn)patches[2].tramp)(waynet, edx, a, b, c);
	InterlockedIncrement(&generation);
}

static void *__fastcall hook_insert_xyz(void *waynet, void *edx, float x, float y, float z)
{
	void *wp;

	InterlockedIncrement(&generation);
	wp = ((xyz_fn)patches[3].tramp)(waynet, edx, x, y, z);
	InterlockedIncrement(&generation);
	return wp;
}

static void __fastcall hook_delete_wp(void *waynet, void *edx, void *wp)
{
	InterlockedIncrement(&generation);
	((wp1_fn)patches[4].tramp)(waynet, edx, wp);
	InterlockedIncrement(&generation);
}

static void __fastcall hook_unarchive(void *waynet, void *edx, void *arc)
{
	InterlockedIncrement(&generation);
	((unarchive_fn)ADDR_UNARCHIVE)(waynet, edx, arc);
	InterlockedIncrement(&generation);
}

static void *__fastcall hook_deleting_dtor(void *waynet, void *edx, unsigned flags)
{
	void *r;

	InterlockedIncrement(&generation);
	if (grid.waynet == waynet)
		grid.valid = FALSE;
	r = ((dtor_fn)ADDR_DELETING_DTOR)(waynet, edx, flags);
	InterlockedIncrement(&generation);
	return r;
}

/* ---- patching ---------------------------------------------------------- */

static BOOL write_code(void *at, const void *bytes, SIZE_T len)
{
	DWORD old;

	if (!VirtualProtect(at, len, PAGE_EXECUTE_READWRITE, &old))
		return FALSE;
	CopyMemory(at, bytes, len);
	VirtualProtect(at, len, old, &old);
	FlushInstructionCache(GetCurrentProcess(), at, len);
	return TRUE;
}

static BOOL install(void)
{
	void **vtbl = (void **)ADDR_VTBL_WAYNET;
	DWORD old;
	unsigned i;

	MEMORY_BASIC_INFORMATION mbi;
	char path[MAX_PATH];
	DWORD len;

	/* Gothic2.exe 2.6 at its usual base, nothing else (Vdfs32g.exe, the
	 * VDFS init tool, loads this DLL too) */
	if (GetModuleHandleA(NULL) != (HMODULE)0x00400000)
		return FALSE;
	len = GetModuleFileNameA(NULL, path, sizeof(path));
	if (len < 11 || len >= sizeof(path) || lstrcmpiA(path + len - 11, "Gothic2.exe"))
		return FALSE;
	for (i = 0; i < ARRAYSIZE(patches); i++)
		if (!VirtualQuery((void *)patches[i].addr, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT ||
		    mbi.AllocationBase != (void *)0x00400000)
			return FALSE;
	if (!VirtualQuery(vtbl, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT || mbi.AllocationBase != (void *)0x00400000)
		return FALSE;
	for (i = 0; i < ARRAYSIZE(patches); i++)
		if (memcmp((void *)patches[i].addr, patches[i].code, patches[i].len))
			return FALSE;
	if (vtbl[VTBL_UNARCHIVE] != (void *)ADDR_UNARCHIVE || vtbl[VTBL_DELETING_DTOR] != (void *)ADDR_DELETING_DTOR)
		return FALSE;

	patches[0].hook = hook_get_nearest;
	patches[1].hook = hook_insert_wp1;
	patches[2].hook = hook_insert_wp3;
	patches[3].hook = hook_insert_xyz;
	patches[4].hook = hook_delete_wp;
	if (!VirtualProtect(tramp_mem, sizeof(tramp_mem), PAGE_EXECUTE_READWRITE, &old))
		return FALSE;
	for (i = 0; i < ARRAYSIZE(patches); i++) {
		unsigned char *t = tramp_mem[i];
		int32_t rel = (int32_t)(patches[i].addr + patches[i].len - ((uintptr_t)t + patches[i].len + 5));

		CopyMemory(t, patches[i].code, patches[i].len);
		t[patches[i].len] = 0xe9;
		CopyMemory(t + patches[i].len + 1, &rel, 4);
		patches[i].tramp = t;
	}
	FlushInstructionCache(GetCurrentProcess(), tramp_mem, sizeof(tramp_mem));

	/* the vtable first: the list hooks before the query uses the grid */
	{
		void *v[2] = { hook_unarchive, hook_deleting_dtor };

		if (!VirtualProtect(&vtbl[VTBL_UNARCHIVE], 2 * sizeof(void *), PAGE_READWRITE, &old))
			return FALSE;
		vtbl[VTBL_UNARCHIVE] = v[0];
		vtbl[VTBL_DELETING_DTOR] = v[1];
		VirtualProtect(&vtbl[VTBL_UNARCHIVE], 2 * sizeof(void *), old, &old);
	}
	for (i = ARRAYSIZE(patches); i-- > 0;) {
		unsigned char jmp[5];
		int32_t rel = (int32_t)((uintptr_t)patches[i].hook - (patches[i].addr + 5));

		jmp[0] = 0xe9;
		CopyMemory(jmp + 1, &rel, 4);
		write_code((void *)patches[i].addr, jmp, 5);
	}
	return TRUE;
}

static BOOL env_on(const char *name, BOOL dflt)
{
	char v[8];
	DWORD n = GetEnvironmentVariableA(name, v, sizeof(v));

	if (!n || n >= sizeof(v))
		return dflt;
	return v[0] != '0';
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
	if (reason != DLL_PROCESS_ATTACH)
		return TRUE;
	DisableThreadLibraryCalls(inst);
	if (!env_on("G2FAST", TRUE))
		return TRUE;
	heap = GetProcessHeap();
	check_mode = env_on("G2FAST_CHECK", FALSE);
	stats_mode = env_on("G2FAST_STATS", FALSE);
	install();
	return TRUE;
}
