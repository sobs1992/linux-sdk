#!/usr/bin/env python3
"""
doom3-test: a test run of DOOM 3 BFG (package rbdoom3-bfg) on the ODROID-GO
Ultra, over the network on its USB-C port like scripts/ogu-ctl.py. Each
scenario starts the game from bare_app's home, drives it through console
commands written into
com_cmdFile, and reads back the kernel's log, bare_app's log and the game's
own (qconsole.log, com_speeds 1: a line a frame). A scenario fails on a GPU
fault or timeout, a kernel error, a crash, an OOM kill, an engine ERROR, a
game that stops making frames or does not quit cleanly.

  doom3-test.py [options] [SCENARIO...]     default: start views intro resize exit

DOOM 3's tile is found on bare_app's home by its place among the games
played (recent= in /etc/bare_app.conf); no other game may be running.

Scenarios:
  start     the game up to its main menu: time, screenshot
  views     maps (--maps) loaded one after the other from the main menu:
            load time, then 4 directions from the spawn point (setviewpos),
            fps of each; back to the menu (disconnect) between maps, the
            memory the GPU holds (Shmem) compared after each
  intro     mars_city1 from the main menu, its intro: fps every 10 s, shots
  resize    the 3D view's size switched 0.6 <-> 0.85 every few frames in a
            map with glass (glCopyTexImage2D at a new size each time)
  cpubound  the game held on the two A53 cores: the dynamic resolution must
            not drop (the CPU, not the GPU, holds the frames back)
  memory    memory pressure (a hog leaves --leave MB) in a heavy map: the
            kernel purges GPU buffers; no fault, no OOM kill
  exit      SIGTERM: exit status 0 within 15 s, the GPU's memory given back
  crash     SIGSEGV: the game ends by it at once, with a backtrace
  soak      views + resize + map changes over and over for --minutes

Options:
  -o DIR          results (report.txt, results.json, shots); default
                  output/doom3-tests/<date-time>
  --baseline F    results.json of an earlier run: fps compared, -10 % warns
  --deploy        copy the engine, SDL2 and libgallium of output/ogu's
                  target to the board first
  --maps A,B      maps for views/soak (default alphalabs1,mars_city2,
                  delta2a,caverns1,mc_underground)
  --minutes N     soak length (default 30); --resize-secs N (default 120)
  --leave MB      what the memory hog leaves available (default 250)

The board's doom3.ini gets the test arguments (+set com_cmdFile cmd.cfg
+set logFile 2) if it lacks them; they stay. Helpers aff (CPU affinity) and
memhog are built with the ogu toolchain and copied to /root on first use.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("ogu_ctl", os.path.join(SDK, "scripts/ogu-ctl.py"))
ogu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ogu)
# a board that hangs mid-command: ssh gives up within 15 s instead of waiting
ogu.SSH[1:1] = ["-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]

INI = "/usr/share/bare_app/games/doom3.ini"
BASE = "/data/doom3/base"
QLOG = BASE + "/qconsole.log"
BLOG = "/var/log/bare_app.log"
TEST_ARGS = "+set com_cmdFile cmd.cfg +set logFile 2"
TARGET = os.path.join(SDK, "output/ogu/buildroot/target")
FILES = {"engine": "/usr/lib/rbdoom3bfg/RBDoom3BFG",
         "sdl2": "/usr/lib/libSDL2-2.0.so.0.3200.10",
         "gallium": "/usr/lib64/libgallium-25.0.7.so"}
GLASS_MAP = "mc_underground"

HELPERS = {
    "aff": r'''/* aff PID MASK: CPU affinity (hex mask) of all threads of PID */
#define _GNU_SOURCE
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>
int main(int argc, char **argv)
{
	char path[64];
	unsigned long mask = argc > 2 ? strtoul(argv[2], NULL, 16) : 0;
	cpu_set_t set;
	DIR *d;
	struct dirent *e;
	int n = 0;
	if (argc < 3)
		return 2;
	CPU_ZERO(&set);
	for (int c = 0; c < 64; c++)
		if (mask & (1ul << c))
			CPU_SET(c, &set);
	snprintf(path, sizeof(path), "/proc/%s/task", argv[1]);
	if (!(d = opendir(path))) {
		perror(path);
		return 1;
	}
	while ((e = readdir(d)))
		if (e->d_name[0] != '.' && sched_setaffinity(atoi(e->d_name), sizeof(set), &set) == 0)
			n++;
	printf("%d threads -> %lx\n", n, mask);
	return 0;
}
''',
    "memhog": r'''/* memhog LEAVE_MB SECONDS: takes memory until MemAvailable is about
 * LEAVE_MB, holds it (touched again every second), then exits */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static long avail_mb(void)
{
	char line[256];
	long kb = -1;
	FILE *f = fopen("/proc/meminfo", "r");
	while (f && fgets(line, sizeof(line), f))
		if (sscanf(line, "MemAvailable: %ld kB", &kb) == 1)
			break;
	if (f)
		fclose(f);
	return kb / 1024;
}
int main(int argc, char **argv)
{
	long leave = argc > 1 ? atol(argv[1]) : 250, secs = argc > 2 ? atol(argv[2]) : 60;
	static char *chunks[4096];
	int n = 0;
	while (n < 4096 && avail_mb() > leave + 16) {
		if (!(chunks[n] = malloc(16 << 20)))
			break;
		memset(chunks[n], 1, 16 << 20);
		n++;
	}
	printf("memhog: %d MB taken, %ld MB available\n", n * 16, avail_mb());
	fflush(stdout);
	for (long s = 0; s < secs; s++) {
		sleep(1);
		for (int i = 0; i < n; i++)
			memset(chunks[i], (int)s, 16 << 20);
	}
	return 0;
}
''',
}


class BoardGone(Exception):
    pass


def sh(cmd, timeout=30, data=None, check=True):
    """A command on the board; BoardGone when it does not answer"""
    try:
        r = subprocess.run(ogu.SSH + [cmd], input=data, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BoardGone("no answer in %d s to: %s" % (timeout, cmd[:60]))
    if r.returncode == 255:
        raise BoardGone(r.stderr.decode(errors="replace").strip())
    if check and r.returncode:
        raise RuntimeError("board: %s: exit %d: %s" % (cmd[:60], r.returncode, r.stderr.decode(errors="replace").strip()))
    return r.stdout.decode("latin-1")


def press(*steps):
    try:
        ogu.run(list(steps))
    except SystemExit as e:	# ogu-ctl gives up on ssh errors
        raise BoardGone(str(e))


# ---- the board's state ---------------------------------------------------

def mark():
    """Where the logs are now: what a scenario finds later is after this"""
    out = sh("wc -l < %s; wc -l < %s 2>/dev/null || echo 0; dmesg | tail -1" % (BLOG, QLOG))
    lines = out.splitlines()
    m = re.match(r"\[\s*([0-9.]+)\]", lines[2] if len(lines) > 2 else "")
    return {"blog": int(lines[0]), "qlog": int(lines[1]), "dmesg": float(m.group(1)) if m else 0.0}


KERNEL = [("gpu_faults", re.compile(r"js fault|Page fault|AS_ACTIVE")),
          ("gpu_timeouts", re.compile(r"sched timeout|job timeout|gpu sched")),
          ("oom", re.compile(r"Out of memory|oom-kill|invoked oom-killer")),
          ("kernel_errors", re.compile(r"BUG:|Oops|Unable to handle|bad page map|Call trace|WARNING: CPU|WARNING: \S+:\d+ at")),
          ("purges", re.compile(r"Purging"))]


def kernel_since(m):
    """Kernel messages after the mark, sorted by kind"""
    found = {k: [] for k, _ in KERNEL}
    in_oom = False	# an OOM report's stack dump is the OOM's, not a kernel error
    for line in sh("dmesg | grep -v rk818", timeout=30).splitlines():
        t = re.match(r"\[\s*([0-9.]+)\]", line)
        if not t or float(t.group(1)) <= m["dmesg"]:
            continue
        if "invoked oom-killer" in line:
            in_oom = True
        elif in_oom and re.search(r"Out of memory|oom-kill", line):
            in_oom = False
        elif in_oom:
            continue
        for kind, rx in KERNEL:
            if rx.search(line):
                found[kind].append(line.strip())
                break
    return found


def bare_app_since(m):
    """bare_app's log after the mark: how games ended, backtraces"""
    text = sh("tail -n +%d %s | grep -a -E 'game ended|^SIG[A-Z]+ \\(|^  #|Crashed|double fault'" % (m["blog"] + 1, BLOG), check=False)
    ends = re.findall(r"game ended(?:, exit status (\d+)| by signal (\d+))", text)
    return {"exits": [int(a) for a, b in ends if a != ""],
            "signals": [int(b) for a, b in ends if b != ""],
            "backtrace": [l for l in text.splitlines() if l.startswith(("SIG", "  #", "Crashed"))][:40]}


# the engine's fatal errors (common->Error, FatalError); OpenAL's "Error:"
# lines are warnings
ENGINE_ERRORS = r"^ERROR:|FATAL|Sys_Error"


def game_errors():
    """Fatal errors in the game's log (each scenario starts the game anew)"""
    return sh("grep -a -E '%s' %s 2>/dev/null | head -5" % (ENGINE_ERRORS, QLOG), check=False).splitlines()


def meminfo():
    out = sh("grep -E '^(MemAvailable|Shmem):' /proc/meminfo")
    return {k: int(v) // 1024 for k, v in re.findall(r"(\w+):\s+(\d+)", out)}


def game_pid():
    return sh("pidof RBDoom3BFG || true").strip()


# ---- frames --------------------------------------------------------------

def frame_stats(lines):
    """com_speeds 1 lines: fps, percentiles; the dynamic resolution's changes"""
    fr = [int(m.group(1)) for m in (re.search(r"all:\s*(\d+)", l) for l in lines if l.startswith("frame:")) if m]
    scales = [float(m.group(1)) for m in (re.search(r"resolutionScale: ([0-9.]+)", l) for l in lines) if m]
    if not fr:
        return {"frames": 0, "scale_changes": len(scales)}
    s = sorted(fr)
    pct = lambda p: s[min(len(s) - 1, int(len(s) * p))]
    total = sum(fr)
    return {"frames": len(fr), "fps": round(len(fr) * 1000.0 / max(total, 1), 1),
            "p50": pct(0.5), "p90": pct(0.9), "p99": pct(0.99), "worst": s[-1],
            "hitches": sum(1 for v in fr if v > 50), "scale_changes": len(scales),
            "scale": scales[-1] if scales else None}


class Window:
    """Frames over a stretch of time (the game log's lines between two marks)"""

    def __init__(self):
        self.start = int(sh("wc -l < %s" % QLOG).strip())
        self.t0 = time.time()

    def end(self):
        lines = sh("tail -n +%d %s | head -n 200000 | grep -a -E '^frame:|resolutionScale'" % (self.start + 1, QLOG), check=False).splitlines()
        st = frame_stats(lines)
        st["secs"] = round(time.time() - self.t0, 1)
        return st


# ---- the game ------------------------------------------------------------

def cmd(text, wait=True):
    """Console commands through com_cmdFile (written aside, then renamed)"""
    sh("cat > %s/cmd.tmp && mv %s/cmd.tmp %s/cmd.cfg" % (BASE, BASE, BASE), data=(text + "\n").encode())
    if wait:
        for _ in range(20):
            time.sleep(0.3)
            if sh("[ -e %s/cmd.cfg ] && echo y || true" % BASE).strip() != "y":
                return
        raise RuntimeError("the game did not take the commands: %s" % text[:60])


def stop_game(sig="TERM", wait=15):
    """The running game ended: its exit status if it went within the wait"""
    pid = game_pid()
    if not pid:
        return None
    m = mark()
    sh("kill -%s %s" % (sig, pid))
    for _ in range(wait * 2):
        time.sleep(0.5)
        if not game_pid():
            return bare_app_since(m)
    sh("kill -9 $(pidof RBDoom3BFG) 2>/dev/null; true")
    time.sleep(2)
    return {"hung": True}


def game_key(name, kind="native"):
    """bare_app's key of a game (games.c game_key: FNV-1a of "id/name")"""
    h = 2166136261
    for b in ("%s/%s" % (kind, name)).encode():
        h = ((h ^ b) * 16777619) & 0xffffffff
    return "%08x" % h


def other_game():
    """The game bare_app runs now (or keeps minimised) if it is not DOOM 3"""
    log = sh("grep -a -E 'game: (started|game ended)|game ended' %s | tail -1" % BLOG, check=False)
    m = re.search(r"started (\S+) \(pid (\d+)", log)
    if m and "rbdoom3bfg" not in m.group(1) and sh("[ -d /proc/%s ] && echo y || true" % m.group(2)).strip() == "y":
        return m.group(1)
    return None


def doom3_tile():
    """Where DOOM 3's tile is on bare_app's home: the games played, the
    latest first (/etc/bare_app.conf recent=)"""
    name = re.search(r"^name\s*=\s*(.+?)\s*$", sh("cat %s" % INI), re.M).group(1)
    key = game_key(name)
    recent = re.search(r"^recent=(.*)$", sh("cat /etc/bare_app.conf"), re.M)
    keys = recent.group(1).split(",") if recent else []
    if key not in keys:
        raise RuntimeError("DOOM 3 (key %s) was never started from bare_app: start it once by hand" % key)
    return keys.index(key)


def start_game(extra=()):
    """The game started from bare_app's home and at its main menu"""
    stop_game()
    other = other_game()
    if other:
        raise RuntimeError("bare_app runs another game (%s): close it first" % other)
    autoexec = ["set logFile 2", "set com_speeds 1", "set rs_showResolutionChanges 1"] + list(extra)
    sh("cat > %s/autoexec.cfg; rm -f %s/cmd.cfg %s/cmd.tmp; pidof bare_app > /dev/null || "
       "(/etc/init.d/S90bare-app start; sleep 5)" % (BASE, BASE, BASE), data=("\n".join(autoexec) + "\n").encode())
    t0 = time.time()
    # home, the row of tiles, the first tile, then along to DOOM 3's
    tile = doom3_tile()
    press(*(["b", "wait:800", "b", "wait:800", "up", "up"] + ["left"] * 10 + ["right"] * tile + ["wait:300", "a"]))
    for _ in range(80):
        time.sleep(0.5)
        if game_pid() and sh("grep -a -c 'Common Initialization Complete' %s 2>/dev/null || true" % QLOG).strip() not in ("", "0"):
            time.sleep(4)	# the menu's first frames
            return round(time.time() - t0, 1)
    if not game_pid():
        other = other_game()
        raise RuntimeError("DOOM 3 did not start%s" % (" (bare_app started %s instead)" % other if other else ""))
    raise RuntimeError("DOOM 3 started but did not reach its main menu in 40 s")


def load_map(name, timeout=120):
    """map game/NAME from wherever the game is; seconds it took"""
    start = int(sh("wc -l < %s" % QLOG).strip())
    t0 = time.time()
    cmd("map game/%s" % name)
    while time.time() - t0 < timeout:
        time.sleep(1)
        out = sh("tail -n +%d %s | grep -a 'msec to load game' || true" % (start + 1, QLOG)).strip()
        if out:
            time.sleep(3)
            return round(time.time() - t0, 1)
        if not game_pid():
            raise RuntimeError("the game ended while loading %s" % name)
    raise RuntimeError("%s did not load in %d s" % (name, timeout))


def view_pos():
    start = int(sh("wc -l < %s" % QLOG).strip())
    cmd("getviewpos")
    time.sleep(0.5)
    out = sh("tail -n +%d %s | grep -a -E '^\\(' | tail -1" % (start + 1, QLOG)).strip()
    m = re.match(r"\(([-0-9.]+) ([-0-9.]+) ([-0-9.]+)\) ([-0-9.]+)", out)
    if not m:
        raise RuntimeError("getviewpos gave nothing (%r)" % out)
    return [float(v) for v in m.groups()]


def need_helper(name):
    if sh("[ -x /root/%s ] && echo y || true" % name).strip() == "y":
        return
    cc = ogu.CC
    if not os.path.exists(cc):
        raise RuntimeError("no ogu toolchain (%s) for /root/%s" % (cc, name))
    src = os.path.join(SDK, "output/ogu/%s.c" % name)
    out = os.path.join(SDK, "output/ogu/%s" % name)
    with open(src, "w") as f:
        f.write(HELPERS[name])
    subprocess.run([cc, "-O2", "-s", "-Wall", "-o", out, src], check=True)
    with open(out, "rb") as f:
        sh("cat > /root/%s && chmod 755 /root/%s" % (name, name), data=f.read())


def shot(run, name):
    path = os.path.join(run.out, "shots", name + ".png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        ogu.shot(path)
    except SystemExit:
        return None
    return os.path.relpath(path, run.out)


# ---- scenarios -----------------------------------------------------------

class Run:
    def __init__(self, args):
        self.args = args
        self.out = args.o
        self.results = {}

    def scenario(self, name, fn):
        print("== %s" % name, flush=True)
        r = {"name": name, "fail": [], "warn": [], "info": {}}
        m = mark()
        mem0 = meminfo()
        t0 = time.time()
        try:
            fn(r)
        except BoardGone as e:
            r["fail"].append("the board stopped answering (%s): hung or rebooted?" % e)
            self.results[name] = r
            raise
        except Exception as e:
            r["fail"].append("%s: %s" % (type(e).__name__, e))
        r["secs"] = round(time.time() - t0)
        try:
            self.check_logs(r, m, mem0)
        except BoardGone as e:
            r["fail"].append("the board stopped answering (%s)" % e)
            self.results[name] = r
            raise
        self.results[name] = r
        self.print_result(r)

    def check_logs(self, r, m, mem0):
        k = kernel_since(m)
        for kind in ("gpu_faults", "gpu_timeouts", "kernel_errors", "oom"):
            if k[kind] and not (kind == "oom" and r.get("oom_ok")):
                r["fail"].append("%d %s, first: %s" % (len(k[kind]), kind.replace("_", " "), k[kind][0][:140]))
        r["info"]["purges"] = len(k["purges"])
        b = bare_app_since(m)
        expected = r.get("expect_signal")
        for s in b["signals"]:
            if s == 9:
                r["fail"].append("the game did not quit on SIGTERM and was killed")
            elif s != expected:
                r["fail"].append("the game crashed (signal %d)" % s)
        if b["backtrace"] and expected is None:
            r["backtrace"] = b["backtrace"]
        for e in b["exits"]:
            if e != 0:
                r["fail"].append("the game quit with status %d" % e)
        errors = game_errors()
        if errors:
            r["fail"].append("engine: %s" % errors[0][:140])
        mem = meminfo()
        r["info"]["shmem_mb"] = mem["Shmem"]
        r["info"]["available_mb"] = mem["MemAvailable"]

    def check_window(self, r, key, st, min_fps=1.0):
        r.setdefault("windows", {})[key] = st
        if st.get("frames", 0) == 0 or st.get("fps", 0) < min_fps:
            r["fail"].append("%s: no frames (the game stalled)" % key)
        base = self.args.baseline_data.get(r["name"], {}).get("windows", {}).get(key) if self.args.baseline_data else None
        if base and base.get("fps") and st.get("fps"):
            d = (st["fps"] - base["fps"]) / base["fps"] * 100
            st["vs_baseline"] = round(d, 1)
            if d < -10:
                r["warn"].append("%s: %.1f fps, baseline %.1f (%+.0f %%)" % (key, st["fps"], base["fps"], d))

    def print_result(self, r):
        state = "FAIL" if r["fail"] else "WARN" if r["warn"] else "PASS"
        print("   %s (%d s)" % (state, r["secs"]))
        for w in r.get("windows", {}).items():
            st = w[1]
            if st.get("frames"):
                print("   %-28s %5.1f fps  p50 %3d p90 %3d p99 %3d worst %4d  hitches %3d  scale %s (%d changes)%s" % (
                    w[0], st["fps"], st["p50"], st["p90"], st["p99"], st["worst"], st["hitches"],
                    "%.2f" % st["scale"] if st.get("scale") else "-", st["scale_changes"],
                    "  %+.1f %%" % st["vs_baseline"] if "vs_baseline" in st else ""))
        for f in r["fail"]:
            print("   FAIL: " + f)
        for w in r["warn"]:
            print("   warn: " + w)
        if r["info"]:
            print("   " + ", ".join("%s %s" % kv for kv in r["info"].items()))
        sys.stdout.flush()

    # -- the scenarios

    def s_start(self, r):
        r["info"]["to_menu_s"] = start_game()
        r["shots"] = [shot(self, "start-menu")]
        w = Window()
        time.sleep(8)
        self.check_window(r, "main menu", w.end())

    def views(self, r, maps, prefix=""):
        shmem_menu = None
        for name in maps:
            r["info"]["load_%s_s" % name] = load_map(name)
            cmd("god; notarget")
            time.sleep(1)
            x, y, z, yaw = view_pos()
            for k in range(4):
                cmd("setviewpos %.1f %.1f %.1f %.0f" % (x, y, z, (yaw + 90 * k) % 360))
                time.sleep(2.5)	# settle: the scale steers itself in
                w = Window()
                time.sleep(6)
                self.check_window(r, "%s%s %d" % (prefix, name, 90 * k), w.end())
                if k == 0:
                    r.setdefault("shots", []).append(shot(self, "%s%s" % (prefix.strip("# "), name)))
            cmd("disconnect")
            time.sleep(6)
            shm = meminfo()["Shmem"]
            if shmem_menu is None:
                shmem_menu = shm
            elif shm > shmem_menu + 64:
                r["warn"].append("main menu after %s holds %d MB of GPU memory, %d after the first map" % (name, shm, shmem_menu))
            r["info"]["shmem_menu_after_%s" % name] = shm

    def s_views(self, r):
        start_game()
        self.views(r, self.args.maps.split(","))

    def s_intro(self, r):
        start_game()
        r["info"]["load_s"] = load_map("mars_city1")
        shots = []
        for t in range(10, 130, 10):
            w = Window()
            time.sleep(10 - 0.2)
            self.check_window(r, "intro %3d s" % t, w.end())
            if t in (30, 60, 90):
                shots.append(shot(self, "intro-%d" % t))
        r["shots"] = shots

    def resize(self, r, secs, frames=4):
        """resize.cfg switches the size 25 times and runs itself again: the
        console's commands from com_cmdFile wait behind it, so it is
        stopped by writing the file over (at most 50 switches later)"""
        r["info"]["load_s"] = load_map(GLASS_MAP)
        cmd("god; notarget")
        step = "rs_forceFractionX %s; rs_forceFractionY %s; wait " + str(frames) + "\n"
        loop = "".join(step % (f, f) for _ in range(25) for f in ("0.6", "0.85")) + "exec resize.cfg\n"
        sh("cat > %s/resize.cfg" % BASE, data=loop.encode())
        cmd("exec resize.cfg")
        try:
            t = 0
            while t < secs:
                w = Window()
                time.sleep(min(30, secs - t))
                t += 30
                self.check_window(r, "resize %3d s" % min(t, secs), w.end())
                if not game_pid():
                    raise RuntimeError("the game ended")
        finally:
            sh("echo 'rs_forceFractionX 0; rs_forceFractionY 0' > %s/resize.cfg" % BASE)
            time.sleep(3)

    def s_resize(self, r):
        start_game()
        self.resize(r, self.args.resize_secs)

    def s_cpubound(self, r):
        need_helper("aff")
        start_game()
        load_map("alphalabs1")
        cmd("god; notarget")
        time.sleep(8)
        w = Window()
        time.sleep(10)
        self.check_window(r, "all cores", w.end())
        sh("/root/aff %s 3" % game_pid())
        try:
            w = Window()
            time.sleep(40)
            st = w.end()
            self.check_window(r, "two A53 cores", st)
            if st.get("scale_changes", 0) > 2:
                r["fail"].append("the dynamic resolution changed %d times with the CPU holding the frames back"
                                 % st["scale_changes"])
        finally:
            sh("/root/aff %s 3f" % game_pid(), check=False)

    def s_memory(self, r):
        need_helper("memhog")
        start_game()
        load_map("mars_city2")
        cmd("god; notarget")
        sh("(/root/memhog %d 90 > /tmp/memhog.log 2>&1 &)" % self.args.leave)
        for t in (30, 60, 90):
            w = Window()
            time.sleep(30)
            self.check_window(r, "pressure %d s" % t, w.end())
        r["info"]["memhog"] = sh("head -1 /tmp/memhog.log", check=False).strip()
        if not game_pid():
            r["fail"].append("the game is gone (OOM kill?)")

    def s_exit(self, r):
        if not game_pid():
            start_game()
        res = stop_game("TERM", 15)
        if res is None:
            r["fail"].append("no game to stop")
            return
        if res.get("hung"):
            r["fail"].append("the game did not quit in 15 s after SIGTERM (killed)")
        time.sleep(2)
        shm = meminfo()["Shmem"]
        r["info"]["shmem_after_mb"] = shm
        if shm > 120:
            r["warn"].append("%d MB of shared memory still held after the game quit" % shm)

    def s_crash(self, r):
        start_game()
        r["expect_signal"] = 11
        m = mark()
        sh("kill -SEGV %s" % game_pid())
        for _ in range(10):
            time.sleep(0.5)
            if not game_pid():
                break
        else:
            r["fail"].append("the game did not end within 5 s of SIGSEGV")
        b = bare_app_since(m)
        if 11 not in b["signals"]:
            r["fail"].append("bare_app did not see the game end by signal 11")
        if not any(l.startswith("  #") for l in b["backtrace"]):
            r["fail"].append("no backtrace in bare_app's log")
        r["shots"] = [shot(self, "crash-message")]
        press("b")

    def s_soak(self, r):
        end = time.time() + self.args.minutes * 60
        start_game()
        n = 0
        maps = self.args.maps.split(",")
        while time.time() < end:
            n += 1
            self.views(r, maps[(n - 1) % len(maps):][:1] + [maps[n % len(maps)]], prefix="#%d " % n)
            self.resize(r, 60)
            cmd("disconnect")
            time.sleep(5)
            r["info"]["rounds"] = n
            if r["fail"]:
                break


SCENARIOS = ["start", "views", "intro", "resize", "cpubound", "memory", "exit", "crash", "soak"]


def deploy():
    for key, path in FILES.items():
        local = os.path.join(TARGET, path.lstrip("/"))
        with open(local, "rb") as f:
            data = f.read()
        print("deploy %s (%d KB)" % (path, len(data) // 1024), flush=True)
        stop_game()
        sh("cat > %s.new && chmod 755 %s.new && mv %s.new %s" % (path, path, path, path), data=data, timeout=300)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("scenarios", nargs="*", default=["start", "views", "intro", "resize", "exit"])
    p.add_argument("-o", default=os.path.join(SDK, "output/doom3-tests", datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    p.add_argument("--baseline")
    p.add_argument("--deploy", action="store_true")
    p.add_argument("--maps", default="alphalabs1,mars_city2,delta2a,caverns1,mc_underground")
    p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--resize-secs", type=int, default=120)
    p.add_argument("--leave", type=int, default=250)
    a = p.parse_args()
    for s in a.scenarios:
        if s not in SCENARIOS:
            p.error("unknown scenario %s (%s)" % (s, " ".join(SCENARIOS)))
    a.baseline_data = None
    if a.baseline:
        with open(a.baseline) as f:
            a.baseline_data = json.load(f)["scenarios"]
    os.makedirs(a.o, exist_ok=True)

    run = Run(a)
    meta = {"date": datetime.datetime.now().isoformat(timespec="seconds"), "scenarios": a.scenarios,
            "maps": a.maps}
    try:
        if a.deploy:
            deploy()
        if TEST_ARGS not in sh("grep '^args' %s" % INI):
            sh("sed -i 's|^args = .*|& %s|' %s" % (TEST_ARGS, INI))
            meta["ini"] = "test arguments added to " + INI
        sums = sh("md5sum %s" % " ".join(FILES.values()))
        meta["board"] = {k: sums.split()[2 * i] for i, k in enumerate(FILES)}
        meta["kernel"] = sh("uname -r").strip()
        print("board: %s" % ", ".join("%s %s" % (k, v[:8]) for k, v in meta["board"].items()))
        for s in a.scenarios:
            run.scenario(s, getattr(run, "s_" + s))
    except BoardGone as e:
        print("the board stopped answering: %s" % e)
        meta["board_gone"] = str(e)
    except KeyboardInterrupt:
        meta["interrupted"] = True
    finally:
        try:
            stop_game()
        except Exception:
            pass
        with open(os.path.join(a.o, "results.json"), "w") as f:
            json.dump({"meta": meta, "scenarios": run.results}, f, indent=1)
        lines = []
        for name, r in run.results.items():
            state = "FAIL" if r["fail"] else "WARN" if r["warn"] else "PASS"
            lines.append("%-9s %s  %s" % (name, state, "; ".join(r["fail"] + r["warn"])[:200]))
        summary = "\n".join(lines)
        with open(os.path.join(a.o, "report.txt"), "w") as f:
            f.write(json.dumps(meta, indent=1) + "\n\n" + summary + "\n")
        print("\n" + summary + "\nresults: %s" % a.o)
    sys.exit(1 if any(r["fail"] for r in run.results.values()) or meta.get("board_gone") else 0)


if __name__ == "__main__":
    main()
