#!/usr/bin/env python3
"""ddr-calibrate against a simulated DDR PHY: the scenario matrix.

    board/common/buildroot/package/ddr-tools/test/sim-test.py [-k CELL] [-v]

Builds ../src/ddr-calibrate.c for the host with -DDDR_SIM and runs it in a
directory of its own per cell (DDR_SIM_DIR): "phy" is the PHY's register
file (2 MiB, CSR c at byte 2c), "spec" the lanes' read eyes. A lane (db, r)
samples at x = its delay - R * its nibble's strobe and reads wrong outside
[lo, hi]; the test sets the eyes from each lane's early and late margin
(E, T steps from where it samples now), so the right answer is known:
S = (E - T) / 2, against the median of its nibble.
"""
import os
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


def rnd(x):  # the C code's rounding: half away from zero
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


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

    def path(self, p):
        return os.path.join(self.d, p)

    def regs(self):
        with open(self.path("phy"), "rb") as f:
            buf = f.read()
        return {c: struct.unpack_from("<H", buf, c * 2)[0] for c in self.regs_start()}

    def expected(self, thresh=4):
        """the line ddr-calibrate should give, as {CSR: steps}"""
        line = {}
        for db in range(4):
            for u in range(2):
                lanes = [(db, 4 * u + i) for i in range(4)]
                S = {l: (self.lanes[l][1] - self.lanes[l][2]) / 2.0 for l in lanes}
                Sm = sorted(rnd(S[l]) for l in lanes)
                med = (Sm[1] + Sm[2]) / 2.0
                tot, bl2 = {}, {}
                for l in lanes:
                    now = self.lanes[l][0]
                    bl2[l] = self.trained.get(l, now)
                    moved = now - bl2[l]
                    reli = rnd(S[l] - med)
                    if abs(reli) >= thresh or moved:
                        tot[l] = moved + reli
                lift = 0
                for l, t in tot.items():
                    lift = max(lift, -(bl2[l] + t))
                for l in lanes:
                    t = tot.get(l, 0) + lift
                    if l in tot or lift:
                        t = min(t, VMAX - bl2[l])
                        if t:
                            line[pbd(*l)] = t
        return line


def parse_line(text):
    out = {}
    for t in text.split():
        out[int(t[:5], 16)] = int(t[6:], 16) * (-1 if t[5] == "-" else 1)
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
    c = Cell("base: a full run finds bit 42 and DBYTE3 r4/r5, lifts the nibble at 0")
    b = base_board(d)
    s0 = b.regs()
    r = run(binary, b, ["-p"])
    c.check(r.returncode == 0, "exit %d: %s" % (r.returncode, r.stderr[-300:]))
    got, exp = result_of(r), b.expected()
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    c.check(exp.get(0x11668, 0) >= 9, "the cell tests nothing: bit 42 not off in the expected line")
    lanes = [l.split() for l in r.stdout.splitlines() if l.startswith("lane 1")]
    want = [["lane", "%05x" % k, str(cpu_bit(k >> 12 & 3, k >> 8 & 15)), "%+d" % v] for k, v in sorted(exp.items())]
    c.check(sorted(lanes) == sorted(want), "lane lines %s, expected %s" % (lanes, want))
    common_after(c, b, binary, r, s0)
    c.check(log_closed(b), "the log's block not ended")
    c.check(status(binary, b) == "unfinished 0", "-s: " + status(binary, b))
    return c


def cell_moved32(binary, d):
    c = Cell("moved32: U-Boot moved all 32 lanes at this start (/chosen 511 bytes): all kept")
    b0 = base_board(d)
    trained = {k: v[0] for k, v in b0.lanes.items()}
    over = {k: (v[0] + 6, v[1], v[2]) for k, v in b0.lanes.items()}
    b = base_board(d, override=over, trained=trained)
    c.check(os.path.getsize(b.path("chosen")) > 256, "chosen is short: the cell tests nothing")
    s0 = b.regs()
    r = run(binary, b, ["-p"])
    got, exp = result_of(r), b.expected()
    c.check(len(exp) == 32, "the expected line has %d lanes" % len(exp))
    c.check(got == exp, "line %s, expected %s" % (got, exp))
    common_after(c, b, binary, r, s0)
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


CELLS = [cell_base, cell_moved32, cell_strobe_high, cell_stop, cell_stop_in_restore, cell_run_after_kill,
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
