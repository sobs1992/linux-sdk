#!/usr/bin/env python3
"""ddr-calibrate against a simulated DDR PHY: the scenario matrix.

    board/common/buildroot/package/ddr-tools/test/sim-test.py [-k CELL] [-v]

Builds ../src/ddr-calibrate.c for the host with -DDDR_SIM and runs it in a
directory of its own per cell (DDR_SIM_DIR): "phy" is the PHY's register
file (2 MiB, CSR c at byte 2c), "spec" the lanes' read eyes. A lane (db, r)
samples at x = its delay - R * its nibble's strobe and reads wrong outside
[lo, hi]; the test sets the eyes from each lane's early and late margin
(E, T steps from where it samples now), so the right answer is known:
S = (E - T) / 2; in BL2's frame a lane's place is its centre minus the median
of its three neighbours' offsets from BL2's values.
"""
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src", "ddr-calibrate.c")
PATCH = os.path.abspath(os.path.join(HERE, "../../../../../ogu/u-boot/patches/"
                                     "0020-board-odroid-go-ultra-ddr-phy-read-delays-tuned-per-device.patch"))
PHY_SIZE = 0x200000
VMAX = 0x3f
R = 2.5
SCALE = "0.02"


def pbd(db, r):
    return 0x10000 | db << 12 | r << 8 | 0x68


def clk(db, u):
    return 0x10000 | db << 12 | u << 8 | 0x8c


def lnsel_csr(db, b):
    return 0x10000 | db << 12 | (0xa0 + b)


# bit b of byte db (odd beat: bit 32 + 8 db + b) is lane LNSEL[db][b]; bit 42 = DBYTE1 lane 6
LNSEL = [list(range(8)) for _ in range(4)]
LNSEL[1][2], LNSEL[1][6] = 6, 2


def cpu_bit(db, r):
    return 32 + db * 8 + LNSEL[db].index(r)


def rnd(x):  # half away from zero
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def rnd0(x):  # ddr-calibrate's offsets: half a step towards zero
    r = int(x)
    return r + (1 if x - r > 0.5 else -1 if x - r < -0.5 else 0)


class Board:
    """A simulated unit: its trained registers, the lanes' margins, a boot."""

    def __init__(self, d, strobe, lanes, trained=None):
        # strobe[(db, u)], lanes[(db, r)] = (now, E, T); trained[(db, r)]: BL2's value (U-Boot moved it)
        self.d, self.strobe, self.lanes, self.trained = d, strobe, lanes, trained or {}
        os.makedirs(os.path.join(d, "run"), exist_ok=True)
        self.boot()

    def regs_start(self):
        regs = {clk(db, u): v for (db, u), v in self.strobe.items()}
        regs.update({pbd(db, r): v[0] for (db, r), v in self.lanes.items()})
        return regs

    def boot(self, regs=None):
        """power-on: the registers as trained, a new boot ID, /run empty, /data not frozen"""
        buf = bytearray(PHY_SIZE)
        for c, v in (regs or self.regs_start()).items():
            struct.pack_into("<H", buf, c * 2, v)
        for db in range(4):
            for b in range(8):
                struct.pack_into("<H", buf, lnsel_csr(db, b) * 2, LNSEL[db][b])
        with open(self.path("phy"), "wb") as f:
            f.write(buf)
        with open(self.path("boot_id"), "w") as f:
            f.write(str(uuid.uuid4()) + "\n")
        for p in ("run/ddr-calibrate.saved", "frozen"):
            if os.path.exists(self.path(p)):
                os.unlink(self.path(p))
        with open(self.path("spec"), "w") as f:
            f.write("R %g\n" % R)
            for (db, r), (now, e, t) in self.lanes.items():
                x0 = now - R * self.strobe[(db, r // 4)]
                f.write("eye %d %d %g %g\n" % (db, r, x0 - t + 0.5, x0 + e - 0.5))
        if self.trained:
            with open(self.path("chosen"), "w") as f:
                f.write(" ".join("%05x:%04x>%04x" % (pbd(db, r), v, self.lanes[(db, r)][0])
                                 for (db, r), v in sorted(self.trained.items())) + "\0")

    def retrain(self, bl2):
        """a new start: BL2 trained the lanes to bl2 {(db, r): value} (the rest as at the
        board's start), the eyes stay where they are; then U-Boot applies kept (a line)"""
        regs = self.regs_start()
        regs.update({pbd(*k): v for k, v in bl2.items()})
        buf = bytearray(open(self.path("phy"), "rb").read())
        for c, v in regs.items():
            struct.pack_into("<H", buf, c * 2, v)
        with open(self.path("phy"), "wb") as f:
            f.write(buf)
        with open(self.path("boot_id"), "w") as f:
            f.write(str(uuid.uuid4()) + "\n")
        for p in ("run/ddr-calibrate.saved", "frozen", "chosen", "chosen-lift", "chosen-line"):
            if os.path.exists(self.path(p)):
                os.unlink(self.path(p))

    def uboot(self, line):
        """U-Boot 0020's own code (from the patch) applies line to the registers and
        writes what the kernel would find in /chosen"""
        r = subprocess.run([uboot_tool(), line, self.path("phy")], capture_output=True, text=True, check=True)
        props = dict(l[len("prop 7 "):].split("=", 1) for l in r.stdout.splitlines() if l.startswith("prop 7 "))
        for name, f in (("ddr-tune", "chosen"), ("ddr-tune-lift", "chosen-lift"), ("ddr-tune-line", "chosen-line")):
            if name in props:
                with open(self.path(f), "w") as out:
                    out.write(props[name] + "\0")
        return props

    def path(self, p):
        return os.path.join(self.d, p)

    def regs(self):
        with open(self.path("phy"), "rb") as f:
            buf = f.read()
        return {c: struct.unpack_from("<H", buf, c * 2)[0] for c in self.regs_start()}

    def expected(self, thresh=4, lift=None, read=None, unmeasured=()):
        """the line ddr-calibrate should give, as {CSR: N} of "CSR@+N": a lane whose place
        (centred against its nibble) is thresh or more from BL2's value, N from the median
        of BL2's values of the other three lanes; lift[(db, u)]: U-Boot's lift at this start;
        unmeasured: (db, r) lanes whose edge is out of reach (one in a nibble: the others
        take the median of the three measured offsets, their own counted; such a lane
        itself, at BL2's value here, is not kept)"""
        line = {}
        for db in range(4):
            for u in range(2):
                lanes = [(db, 4 * u + i) for i in range(4)]
                S = {l: (self.lanes[l][1] - self.lanes[l][2]) / 2.0 for l in lanes}
                bl2 = {l: self.trained.get(l, self.lanes[l][0]) for l in lanes}
                L = (lift or {}).get((db, u), 0)
                # BL2's frame: a lane's centre C = now - L + S, its offset C - BL2; its place =
                # C - the median of its three neighbours' offsets, rounded towards BL2's value
                C = {l: self.lanes[l][0] - L + S[l] for l in lanes}
                off = {l: C[l] - bl2[l] for l in lanes}
                um = [l for l in lanes if l in unmeasured]
                assert len(um) <= 1
                for i, l in enumerate(lanes):
                    if l in um:
                        continue
                    med = sorted(off[lanes[(i + k) % 4]] for k in (1, 2, 3))[1]
                    if um:
                        med = sorted(off[m] for m in lanes if m not in um)[1]
                    mb = sorted(bl2[lanes[(i + k) % 4]] for k in (1, 2, 3))[1]
                    n = rnd0(C[l] - med - mb)       # N rounded on its own
                    if abs(mb + n - bl2[l]) >= thresh or pbd(*l) in (read or {}):
                        line[pbd(*l)] = n
        return line


_UBOOT_TOOL = []


def uboot_tool():
    """U-Boot 0020's ogu_ddr_tune and meson_ft_board_setup, from the patch's own
    lines (scripts/test-ddr-tune.py's stubs), on a register file: TOOL LINE PHYFILE"""
    if _UBOOT_TOOL:
        return _UBOOT_TOOL[0]
    import importlib.util
    sdk = os.path.abspath(os.path.join(HERE, "../../../../../.."))
    spec = importlib.util.spec_from_file_location("tdt", os.path.join(sdk, "scripts/test-ddr-tune.py"))
    tdt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tdt)
    main = r"""
int main(int argc, char **argv)
{
	FILE *f = fopen(argv[2], "r+b");
	size_t n;

	(void)argc;
	if (!f || fread(regs, 2, 0x20000, f) != 0x20000)
		return 1;
	n = strlen(argv[1]);
	memset(sector, 0, sizeof sector);
	snprintf(sector, sizeof sector, "ddr_tune=%s\n", argv[1]);
	(void)n;
	ogu_ddr_tune();
	meson_ft_board_setup(NULL, NULL);
	fseek(f, 0, SEEK_SET);
	fwrite(regs, 2, 0x20000, f);
	fclose(f);
	return 0;
}
"""
    work = tempfile.mkdtemp(prefix="uboot-tool-")
    c, exe = os.path.join(work, "tool.c"), os.path.join(work, "tool")
    with open(c, "w") as f:
        f.write(tdt.STUBS + tdt.uboot_code(PATCH) + main)
    subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-o", exe, c], check=True)
    _UBOOT_TOOL.append(exe)
    return exe


def parse_line(text):
    """ "CSR@+N" entries -> {CSR: N} (a "CSR+N" one -> {CSR: ("move", N)})"""
    out = {}
    for t in text.split():
        if t[5] == "@":
            out[int(t[:5], 16)] = int(t[7:], 16) * (-1 if t[6] == "-" else 1)
        else:
            out[int(t[:5], 16)] = ("move", int(t[6:], 16) * (-1 if t[5] == "-" else 1))
    return out


def base_board(d, **kw):
    """like the GO Ultras: bit 42's lane at the late edge, DBYTE3 r4/r5 off by 5 the other way"""
    strobe = {(0, 0): 6, (0, 1): 8, (1, 0): 5, (1, 1): 10, (2, 0): 7, (2, 1): 9, (3, 0): 4, (3, 1): 12}
    lanes = {}
    for db in range(4):
        for r in range(8):
            # small skews: S = 10 +- 1 at most
            e, t = 31 + (r * 7 + db) % 3 - 1, 11 + (r * 5 + db) % 3 - 1
            lanes[(db, r)] = [(r * 3 + db * 5) % 9, e, t]
    lanes[(1, 6)] = [2, 46, 4]      # S 21: +11 (bit 42)
    lanes[(3, 4)] = [0, 21, 11]     # S 5: -5, at 0: its nibble lifts
    lanes[(3, 5)] = [2, 41, 11]     # S 15: +5
    for k, v in kw.get("override", {}).items():
        lanes[k] = v
    s = dict(strobe)
    s.update(kw.get("strobe", {}))
    return Board(d, s, {k: tuple(v) for k, v in lanes.items()}, kw.get("trained"))


class Cell:
    def __init__(self, name):
        self.name, self.errors, self.log = name, [], []

    def check(self, ok, what):
        if not ok:
            self.errors.append(what)


def run(binary, board, args, env_extra=None, timeout=120):
    env = dict(os.environ, DDR_SIM_DIR=board.d, DDR_SIM_SCALE=SCALE)
    env.update(env_extra or {})
    return subprocess.run([binary] + args, env=env, capture_output=True, text=True, timeout=timeout)


def start(binary, board, args, env_extra=None):
    env = dict(os.environ, DDR_SIM_DIR=board.d, DDR_SIM_SCALE=SCALE)
    env.update(env_extra or {})
    return subprocess.Popen([binary] + args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for(proc, pred, timeout=60):
    """lines of proc's stdout until pred(line)"""
    end = time.time() + timeout
    lines = []
    while time.time() < end:
        l = proc.stdout.readline()
        if not l:
            break
        lines.append(l)
        if pred(l):
            return lines
    raise RuntimeError("not seen in time: " + "".join(lines[-5:]))


def log_closed(board):
    with open(board.path("ddr-calibrate.log")) as f:
        lines = [l for l in f if l.strip()]
    return lines[-1].startswith("ddr_tune=")


def status(binary, board):
    return run(binary, board, ["-s"]).stdout.strip()


def common_after(c, b, binary, r, start_regs):
    """what every run that ended leaves: registers as at its start, /data thawed, no lock file"""
    c.check(b.regs() == start_regs, "registers not as at the start: %s" %
            {hex(k): (start_regs[k], v) for k, v in b.regs().items() if start_regs[k] != v})
    c.check(not os.path.exists(b.path("frozen")), "/data left frozen")
    c.check(not os.path.exists(b.path("run/ddr-calibrate.saved")), "the lock's file left")
    c.check("sim: clamped 0, out of field 0, frozen writes 0" in r.stderr or "stopped" in r.stderr,
            "values out of the field: " + r.stderr.strip()[-200:])


def result_of(r):
    for l in r.stdout.splitlines():
        if l.startswith("result"):
            return parse_line(l[7:])
    return None


# ---- the cells -------------------------------------------------------------

def cell_base(binary, d):
    c = Cell("base: a full run finds bit 42 and DBYTE3 r4/r5 (r4 below 0: U-Boot's to lift)")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"])
    c.check(r.returncode == 0, "exit %d: %s" % (r.returncode, r.stderr[-300:]))
    got, exp = result_of(r), b.expected()
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    c.check(0x11668 in exp and 0x13468 in exp, "the cell tests nothing: bit 42 or DBYTE3 r4 not in the expected line")
    c.check(all(t[5] == "@" for t in [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:].split()),
            "not all entries CSR@+N")
    lanes = [l.split() for l in r.stdout.splitlines() if l.startswith("lane 1")]
    want = [["lane", "%05x" % k, str(cpu_bit(k >> 12 & 3, k >> 8 & 15)), "%+d" % v] for k, v in sorted(exp.items())]
    c.check(sorted(lanes) == sorted(want), "lane lines %s, expected %s" % (lanes, want))
    common_after(c, b, binary, r, s0)
    c.check(log_closed(b), "the log's block not ended")
    c.check(status(binary, b) == "unfinished 0", "-s: " + status(binary, b))
    return c


def cell_moved32(binary, d):
    c = Cell("moved32: U-Boot moved all 32 lanes at this start (/chosen 511 bytes): every BL2 value read")
    b0 = base_board(d)
    trained = {k: v[0] for k, v in b0.lanes.items()}
    # moved differently per lane (the frame of BL2's values cancels a common move): a BL2 value
    # lost from /chosen distorts its lane's offset
    over = {k: (v[0] + 2 + k[1] % 4 * 3, v[1], v[2]) for k, v in b0.lanes.items()}
    b = base_board(d, override=over, trained=trained)
    c.check(os.path.getsize(b.path("chosen")) > 256, "chosen is short: the cell tests nothing")
    s0 = b.regs()
    r = run(binary, b, ["-p"])
    got, exp = result_of(r), b.expected()
    # BL2's values of all 32 lanes come from /chosen: read short, the later lanes' corrections go wrong
    c.check(len(exp) >= 3, "the expected line has %d lanes: the cell tests little" % len(exp))
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    common_after(c, b, binary, r, s0)
    return c


def table(r):
    """ddr-calibrate's table: {(db, r): its offset against its nibble}"""
    return {(int(a), int(b)): float(rel) for a, b, rel in
            re.findall(r"^(\d)\.(\d)\s+-?\d+\s+[0-9a-f]{2}\s+\d+\+?\s+\d+\+?\s+[-\d.]+\s+([-+\d.]+)", r.stdout, re.M)}


def e2e(binary, d, name, bl2):
    """calibrate, then a new start where BL2 trained bl2 (the eyes where they were) and
    U-Boot applied the line: calibrating again gives the same line, its lanes centred"""
    c = Cell(name)
    b = base_board(d)
    r = run(binary, b, ["-p"])
    line1 = [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:]
    c.check(result_of(r) == b.expected() and line1, "first line %s" % line1)
    b.retrain(bl2)
    props = b.uboot(line1)
    r2 = run(binary, b, ["-p"])
    got = result_of(r2)
    c.check(got == parse_line(line1), "line after %s, before %s (U-Boot did %s)" % (got, parse_line(line1), props))
    rel = table(r2)
    off = {k: v for k, v in rel.items() if pbd(*k) in parse_line(line1) and abs(v) > 1}
    c.check(not off, "corrected lanes not centred: %s" % off)
    common_after(c, b, binary, r2, b.regs())
    return c, props


def cell_e2e_lane_jump(binary, d):
    c, props = e2e(binary, d, "e2e_lane_jump: BL2 trains bit 42's lane 6 instead of 2: same place, same line",
                   {(1, 6): 6})
    return c


def cell_e2e_nibble_moves(binary, d):
    b0 = base_board(d)
    bl2 = {(1, 4 + i): b0.lanes[(1, 4 + i)][0] + 2 for i in range(4)}
    c, props = e2e(binary, d, "e2e_nibble_moves: BL2 trains DBYTE1 nibble 1 two steps later: the lane follows",
                   bl2)
    return c


def cell_e2e_lift(binary, d):
    c, props = e2e(binary, d, "e2e_lift: DBYTE3 r4 below 0: U-Boot lifts the nibble, the next run sees the lift",
                   {})
    c.check("1318c+" in props.get("ddr-tune-lift", ""), "no lift recorded: %s" % props)
    return c


def cell_e2e_odd_start(binary, d):
    c = Cell("e2e_odd_start: calibrated where BL2 trained lane 0.2 at 6 (it belongs at 2): on the usual start "
             "(2) the entry stays, the lane centred")
    b = base_board(d, override={(0, 2): (6, 23, 11)})
    r = run(binary, b, ["-p"])
    line1 = [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:]
    c.check(0x10268 in parse_line(line1), "the cell tests nothing: 0.2 not in %s" % line1)
    b.retrain({(0, 2): 2})
    b.uboot(line1)
    r2 = run(binary, b, ["-p"])
    c.check(result_of(r2) == parse_line(line1), "line after %s, before %s" % (result_of(r2), parse_line(line1)))
    off = {k: v for k, v in table(r2).items() if pbd(*k) in parse_line(line1) and abs(v) > 1}
    c.check(not off, "corrected lanes not centred: %s" % off)
    return c


HALF = {(1, 4): (2, 30, 12), (1, 5): (5, 31, 11), (1, 7): (8, 33, 9), (1, 6): (2, 46, 4)}


def cell_e2e_half_step(binary, d):
    c = Cell("e2e_half_step: neighbours half a step apart: the line stays over two applications at the same start")
    b = base_board(d, override=HALF)
    r = run(binary, b, ["-p", "-d", "1"])
    lines = [[l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:]]
    for k in range(2):
        b.retrain({})
        b.uboot(lines[-1])
        r = run(binary, b, ["-p", "-d", "1"])
        lines.append([l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:])
    c.check(len(set(lines)) == 1 and lines[0], "lines %s" % lines)
    return c


def cell_e2e_neighbour_jump(binary, d):
    c = Cell("e2e_neighbour_jump: calibrated where BL2 trained a neighbour of bit 42 3 steps off: N off by no more "
             "than the jump (the model's limit, said in the docs)")
    b = base_board(d, override=HALF)
    r = run(binary, b, ["-p", "-d", "1"])
    n0 = result_of(r).get(0x11668)
    c.check(n0 is not None, "the cell tests nothing: 11668 not in the line")
    got = {}
    for lane, step in (((1, 7), 3), ((1, 5), -3), ((1, 4), 3)):
        bj = base_board(os.path.join(d, "j%d%d" % lane), override=HALF)
        bj.retrain({lane: HALF[lane][0] + step})
        got[lane] = result_of(run(binary, bj, ["-p", "-d", "1"])).get(0x11668)
    c.check(all(v is not None and abs(v - n0) <= 3 for v in got.values()),
            "11668@%s at the usual start, with a neighbour off: %s" % (n0, got))
    return c


def cell_e2e_half_own(binary, d):
    c = Cell("e2e_half_own: a lane's place half a step from BL2's value, starts with its BL2 value 2 and 7 by turns: "
             "the same line")
    b = base_board(d, override={(0, 2): (7, 22, 11)})
    r = run(binary, b, ["-p", "-d", "0"])
    lines = [[l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:]]
    c.check(0x10268 in parse_line(lines[0]), "the cell tests nothing: 0.2 not in %s" % lines[0])
    for v in (2, 7, 2, 7):
        b.retrain({(0, 2): v})
        b.uboot(lines[-1])
        r = run(binary, b, ["-p", "-d", "0"])
        lines.append([l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:])
    c.check(len(set(lines)) == 1, "lines %s" % lines)
    return c


def cell_e2e_pair(binary, d):
    c = Cell("e2e_pair: two lanes of a nibble in the line, the other two's centres 1-3 steps apart: "
             "the line stays over three applications at the same start")
    bad = {}
    for dd in (1, 2, 3):
        b = base_board(os.path.join(d, "d%d" % dd),
                       override={(3, 6): (2, 31, 11), (3, 7): (2, 31 + 2 * dd, 11)})
        r = run(binary, b, ["-p", "-d", "3"])
        lines = [[l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:]]
        for k in range(3):
            b.retrain({})
            b.uboot(lines[-1])
            r = run(binary, b, ["-p", "-d", "3"])
            lines.append([l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:])
        if len(set(lines)) != 1 or len(lines[0].split()) < 2:
            bad[dd] = lines
    c.check(not bad, "lines moving: %s" % bad)
    return c


def cell_d_keeps_others(binary, d):
    c = Cell("d_keeps_others: -d 3 keeps the other DBYTEs' entries, strobes, lane 8 and old moves as U-Boot read them")
    b = base_board(d)
    r = run(binary, b, ["-p"])
    line1 = [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:] + " 10868+2 1018c+1 10168+2"
    b.retrain({})
    b.uboot(line1)
    r2 = run(binary, b, ["-p", "-d", "3"])
    c.check(result_of(r2) == parse_line(line1), "-d 3: %s, the line %s" % (result_of(r2), parse_line(line1)))
    # -p's lane lines (bare_app shows their bits): the @ lanes only, not what was carried on
    lanes = sorted(l.split()[1] for l in r2.stdout.splitlines() if l.startswith("lane 1"))
    want = sorted("%05x" % k for k, v in parse_line(line1).items() if not isinstance(v, tuple))
    c.check(lanes == want, "lane lines %s, the @ entries %s" % (lanes, want))
    return c


def cell_resume_d(binary, d):
    c = Cell("resume_d: -r -d 3 after a run killed in nibble 6: every CSR once, an old move of a nibble done "
             "before stays decided (dropped)")
    b = base_board(d)
    r = run(binary, b, ["-p"])
    line1 = [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:] + " 10868+2 10068+1"
    b.retrain({})
    b.uboot(line1)
    rf = run(binary, b, ["-p"])     # a whole run on this start: what -r must come to
    full = [l for l in rf.stdout.splitlines() if l.startswith("result ")][0][7:]
    b.retrain({})
    b.uboot(line1)
    r1 = run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "1100"})
    c.check(r1.returncode == -9, "not killed: %d" % r1.returncode)
    st = status(binary, b)
    c.check(st.startswith("unfinished ") and st.split()[1] not in ("0", "8"), "-s: " + st)
    run(binary, b, ["-R"])
    r2 = run(binary, b, ["-p", "-r", "-d", "3"])
    got = [t[:5] for t in [l for l in r2.stdout.splitlines() if l.startswith("result ")][0][7:].split()]
    c.check(len(got) == len(set(got)), "twice: %s" % got)
    c.check(sorted(got) == sorted(t[:5] for t in full.split()), "line %s, the whole run's %s" % (got, full))
    c.check("10068" not in got, "the old move 10068+1 came back: %s" % got)
    return c


def cell_unmeasured(binary, d):
    c = Cell("unmeasured: a lane of the line whose early edge is out of reach stays where U-Boot put it")
    b = base_board(d)
    r = run(binary, b, ["-p"])
    line1 = [l for l in r.stdout.splitlines() if l.startswith("result ")][0][7:] + " 10168@+3"
    b.uboot(line1)
    # 0.1's eye now ends beyond 3f: its early edge is not reached
    with open(b.path("spec"), "a") as f:
        x0 = b.regs()[pbd(0, 1)] - R * b.strobe[(0, 0)]
        f.write("eye 0 1 %g %g\n" % (x0 - 11 + 0.5, x0 + 80))
    r2 = run(binary, b, ["-p"])
    c.check("(edge not reached)" in r2.stdout, "the cell tests nothing: every edge reached")
    got = result_of(r2)
    c.check(got.get(0x10168) == 3, "10168: %s in %s" % (got.get(0x10168), got))
    # a line of the old kind (a move from BL2's value): the unmeasured lane becomes @ where it is
    b.retrain({})
    b.uboot("10168+5")
    with open(b.path("spec"), "a") as f:
        x0 = b.regs()[pbd(0, 1)] - R * b.strobe[(0, 0)]
        f.write("eye 0 1 %g %g\n" % (x0 - 11 + 0.5, x0 + 80))
    r3 = run(binary, b, ["-p", "-d", "0"])
    bl2 = {rr: b.lanes[(0, rr)][0] for rr in range(4)}
    want = bl2[1] + 5 - sorted([bl2[0], bl2[2], bl2[3]])[1]
    c.check(result_of(r3).get(0x10168) == want, "old move 10168+5: %s, expected @%+d" % (result_of(r3), want))
    # in a nibble U-Boot lifted (DBYTE3 nibble 1: r4 below 0), a lane not measured keeps its N
    b2 = base_board(os.path.join(d, "lifted"))
    r4 = run(binary, b2, ["-p", "-d", "3"])
    line4 = [l for l in r4.stdout.splitlines() if l.startswith("result ")][0][7:] + " 13768@+3"
    props = b2.uboot(line4)
    with open(b2.path("spec"), "a") as f:
        x0 = b2.regs()[pbd(3, 7)] - R * b2.strobe[(3, 1)]
        f.write("eye 3 7 %g %g\n" % (x0 - 11 + 0.5, x0 + 80))
    r5 = run(binary, b2, ["-p", "-d", "3"])
    c.check("1318c+" in props.get("ddr-tune-lift", ""), "the nibble was not lifted: %s" % props)
    c.check(result_of(r5).get(0x13768) == 3, "13768 in a lifted nibble: %s" % result_of(r5))
    return c


def cell_three_measured(binary, d):
    c = Cell("three_measured: one lane of a skewed nibble out of reach: the median of the three"
             " measured offsets, no false entries for the lanes beside bit 42")
    for unm in (4, 5, 7):
        b = base_board(os.path.join(d, "u%d" % unm))
        with open(b.path("spec"), "a") as f:
            x0 = b.regs()[pbd(1, unm)] - R * b.strobe[(1, 1)]
            f.write("eye 1 %d %g %g\n" % (unm, x0 - 11 + 0.5, x0 + 80))
        r = run(binary, b, ["-p", "-d", "1"])
        c.check("(edge not reached)" in r.stdout, "lane 1.%d: every edge reached" % unm)
        got = {k: v for k, v in result_of(r).items() if (k >> 12 & 3) == 1 and (k >> 8 & 15) >= 4}
        exp = {k: v for k, v in b.expected(unmeasured=((1, unm),)).items()
               if (k >> 12 & 3) == 1 and (k >> 8 & 15) >= 4}
        c.check(got == exp, "1.%d not measured: %s, expected %s" % (unm, got, exp))
        c.check(set(got) == {0x11668}, "1.%d not measured: entries %s besides 11668" % (unm, got))
    return c


def cell_strobe_high(binary, d):
    c = Cell("strobe_high: a strobe at 0x3c: the lift stays within 0..3f, result right")
    over = {(2, r): (20, 31, 11 + (r == 1)) for r in range(4)}
    b = base_board(d, override=over, strobe={(2, 0): 0x3c})
    s0 = b.regs()
    r = run(binary, b, ["-p", "-d", "2"])
    got = result_of(r)
    exp = {k: v for k, v in b.expected().items() if (k >> 12 & 3) == 2}
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    common_after(c, b, binary, r, s0)
    return c


def cell_stop(binary, d):
    c = Cell("stop: SIGTERM in a run: registers back, thawed, block ended, nothing to go on with")
    b = base_board(d)
    s0 = b.regs()
    p = start(binary, b, ["-p"])
    wait_for(p, lambda l: l.startswith("progress") and int(l.split()[1]) >= 20)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    c.check(p.returncode == 128 + 15 or p.returncode == -15, "exit %d" % p.returncode)
    r = subprocess.CompletedProcess([], p.returncode, out, err)
    common_after(c, b, binary, r, s0)
    c.check(log_closed(b), "the log's block not ended")
    c.check(open(b.path("ddr-calibrate.log")).read().rstrip().endswith("ddr_tune= (stopped: signal 15)"),
            "the stop's line: " + open(b.path("ddr-calibrate.log")).read().rstrip().splitlines()[-1])
    c.check(status(binary, b) == "unfinished 0", "-s: " + status(binary, b))
    r2 = run(binary, b, ["-p", "-r", "-d", "0"])
    c.check("done before" not in r2.stdout, "-r went on with a stopped run")
    return c


def cell_stop_in_restore(binary, d):
    c = Cell("stop_in_restore: SIGTERM while a worker puts a lifted probe back: all at the start values")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"], {"DDR_SIM_SIG_IN_RESTORE": "1"})
    c.check(r.returncode == 128 + 15, "exit %d: %s" % (r.returncode, r.stderr[-200:]))
    common_after(c, b, binary, r, s0)
    return c


def cell_run_after_kill(binary, d):
    c = Cell("run_after_kill: a new run at the same start after SIGKILL: the killed run's registers back first")
    b = base_board(d)
    s0 = b.regs()
    run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "300"})
    c.check(b.regs() != s0, "no register moved at the kill: the cell tests nothing")
    c.check(os.path.exists(b.path("frozen")), "/data not left frozen by the kill: the cell tests less")
    r = run(binary, b, ["-p", "-d", "3"])
    exp = {k: v for k, v in b.expected().items() if (k >> 12 & 3) == 3}
    c.check(result_of(r) == exp, "line %s, expected %s" % (result_of(r), exp))
    c.check("killed run restored first" in r.stderr, "not said: " + r.stderr[-200:])
    common_after(c, b, binary, r, s0)
    return c


def cell_kill_early(binary, d):
    c = Cell("kill_early: SIGKILL before a nibble ended: -s 'unfinished 0 this', -R puts all back")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "5"})
    c.check(r.returncode == -9 and b.regs() != s0, "not killed in a probe: %d" % r.returncode)
    st = status(binary, b)
    c.check(st == "unfinished 0 this", "-s: " + st)
    r2 = run(binary, b, ["-R"])
    c.check("restored 40 registers" in r2.stdout, "-R: " + r2.stdout)
    common_after(c, b, binary, subprocess.CompletedProcess([], 0, "", "stopped"), s0)
    c.check(status(binary, b) == "unfinished 0", "-s after -R: " + status(binary, b))
    return c


def cell_sigint(binary, d):
    c = Cell("sigint: SIGINT: the stop's line says signal 2")
    b = base_board(d)
    s0 = b.regs()
    p = start(binary, b, ["-p"])
    wait_for(p, lambda l: l.startswith("progress"))
    p.send_signal(signal.SIGINT)
    out, err = p.communicate(timeout=30)
    common_after(c, b, binary, subprocess.CompletedProcess([], 0, out, err), s0)
    last = open(b.path("ddr-calibrate.log")).read().rstrip().splitlines()[-1]
    c.check(last == "ddr_tune= (stopped: signal 2)", "the stop's line: " + last)
    return c


def cell_status_running(binary, d):
    c = Cell("status_running: -s while a run goes on says 'running'")
    b = base_board(d)
    s0 = b.regs()
    p = start(binary, b, ["-p"])
    wait_for(p, lambda l: l.startswith("progress"))
    st = status(binary, b)
    c.check(st.startswith("unfinished ") and st.endswith(" running"), "-s: " + st)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    common_after(c, b, binary, subprocess.CompletedProcess([], 0, out, err), s0)
    return c


def cell_kill_same_boot(binary, d):
    c = Cell("kill: SIGKILL in a probe: -s 'this', -R puts the registers back and thaws")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "300"})
    c.check(r.returncode == -9, "not killed: %d" % r.returncode)
    c.check(b.regs() != s0, "no register moved at the kill: the cell tests nothing")
    st = status(binary, b)
    c.check(st.startswith("unfinished ") and st.endswith(" this") and st.split()[1] != "0", "-s: " + st)
    r2 = run(binary, b, ["-R"])
    c.check(r2.returncode == 0 and "restored 40 registers" in r2.stdout, "-R: %s %s" % (r2.stdout, r2.stderr))
    common_after(c, b, binary, subprocess.CompletedProcess([], 0, "", "stopped"), s0)
    r3 = run(binary, b, ["-R"])
    c.check(r3.returncode == 0 and "nothing to restore" in r3.stdout, "-R again: " + r3.stdout)
    return c


def cell_reboot_resume(binary, d):
    c = Cell("reboot: the board went down in nibble 3: -s 'before', -r gives the full run's line")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "520"})
    c.check(r.returncode == -9, "not killed: %d" % r.returncode)
    b.boot()
    st = status(binary, b)
    c.check(st.startswith("unfinished ") and st.endswith(" before") and st.split()[1] != "0", "-s: " + st)
    r2 = run(binary, b, ["-R"])
    c.check(r2.returncode == 0 and "nothing to restore" in r2.stdout, "-R after a reboot: " + r2.stdout)
    r3 = run(binary, b, ["-p", "-r"])
    got, exp = result_of(r3), b.expected()
    c.check("done before" in r3.stdout, "-r did not go on")
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    common_after(c, b, binary, r3, s0)
    c.check(status(binary, b) == "unfinished 0", "-s after: " + status(binary, b))
    return c


def cell_stale_saved(binary, d):
    c = Cell("stale: the lock's file from another start: -R writes no register")
    b = base_board(d)
    run(binary, b, ["-p"], {"DDR_SIM_KILL_PROBE": "300"})
    # a new start with another training, /run kept (as if it were not tmpfs)
    regs = {k: min(v + 1, VMAX) for k, v in b.regs_start().items()}
    saved = open(b.path("run/ddr-calibrate.saved")).read()
    b.boot(regs)
    with open(b.path("run/ddr-calibrate.saved"), "w") as f:
        f.write(saved)
    r = run(binary, b, ["-R"])
    c.check("another start" in r.stdout, "-R: " + r.stdout + r.stderr)
    c.check(b.regs() == regs, "-R wrote registers saved at another start")
    c.check(not os.path.exists(b.path("run/ddr-calibrate.saved")), "the stale file left")
    return c


def cell_lock(binary, d):
    c = Cell("lock: a second run and -R refuse while a run goes on")
    b = base_board(d)
    s0 = b.regs()
    p = start(binary, b, ["-p"])
    wait_for(p, lambda l: l.startswith("progress"))
    r = run(binary, b, ["-p"])
    c.check(r.returncode == 1 and "fail busy" in r.stdout, "second run: %d %s" % (r.returncode, r.stdout))
    r2 = run(binary, b, ["-R"])
    c.check(r2.returncode == 1, "-R in a run: %d %s" % (r2.returncode, r2.stdout))
    c.check(os.path.exists(b.path("run/ddr-calibrate.saved")), "the run's lock file went")
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    common_after(c, b, binary, subprocess.CompletedProcess([], 0, out, err), s0)
    return c


def cell_fail_trained(binary, d):
    c = Cell("fail_trained: a lane wrong at the trained values: 'fail trained', all back")
    b = base_board(d, override={(0, 3): (5, 0, 11)})
    s0 = b.regs()
    r = run(binary, b, ["-p"])
    c.check("fail trained" in r.stdout, "no 'fail trained': " + r.stdout[-200:])
    common_after(c, b, binary, r, s0)
    c.check(log_closed(b), "the log's block not ended")
    c.check(status(binary, b) == "unfinished 0", "-s: " + status(binary, b))
    return c


def cell_restore_nothing(binary, d):
    c = Cell("restore_nothing: -R with no run: nothing, exit 0")
    b = base_board(d)
    r = run(binary, b, ["-R"])
    c.check(r.returncode == 0 and "nothing to restore" in r.stdout, "-R: %d %s" % (r.returncode, r.stdout))
    c.check(status(binary, b) == "unfinished 0", "-s: " + status(binary, b))
    return c


def cell_no_sim_dir(binary, d):
    c = Cell("no_sim_dir: DDR_SIM_DIR empty: refused, never the real /dev/mem")
    r = subprocess.run([binary, "-p"], env=dict(os.environ, DDR_SIM_DIR=""), capture_output=True, text=True)
    c.check(r.returncode == 2, "exit %d" % r.returncode)
    return c


CELLS = [cell_base, cell_moved32, cell_e2e_lane_jump, cell_e2e_nibble_moves, cell_e2e_lift, cell_e2e_odd_start,
         cell_e2e_half_step, cell_e2e_half_own, cell_e2e_neighbour_jump, cell_e2e_pair, cell_d_keeps_others,
         cell_resume_d, cell_unmeasured, cell_three_measured,
         cell_strobe_high, cell_stop, cell_stop_in_restore, cell_run_after_kill,
         cell_status_running, cell_kill_early, cell_sigint, cell_kill_same_boot, cell_reboot_resume,
         cell_stale_saved, cell_lock, cell_fail_trained, cell_restore_nothing, cell_no_sim_dir]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", help="only the cells whose name has this")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--src", default=SRC)
    a = ap.parse_args()
    work = tempfile.mkdtemp(prefix="ddr-sim-")
    try:
        binary = os.path.join(work, "ddr-calibrate-sim")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O2", "-pthread", "-DDDR_SIM",
                        "-o", binary, a.src], check=True)
        cells = [f for f in CELLS if not a.k or a.k in f.__name__]
        results = [None] * len(cells)

        def one(i, f):
            d = os.path.join(work, f.__name__)
            os.makedirs(d)
            try:
                results[i] = f(binary, d)
            except Exception as e:  # a cell that broke is a failed cell
                results[i] = Cell(f.__name__)
                results[i].errors.append("%s: %s" % (type(e).__name__, e))

        threads = [threading.Thread(target=one, args=(i, f)) for i, f in enumerate(cells)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        bad = 0
        for c in results:
            print("%s  %s" % ("PASS" if not c.errors else "FAIL", c.name))
            for e in c.errors:
                print("        " + e)
            bad += bool(c.errors)
        print("%d of %d cells failed" % (bad, len(results)))
        return 1 if bad else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
