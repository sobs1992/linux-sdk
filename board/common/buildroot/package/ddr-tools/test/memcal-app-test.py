#!/usr/bin/env python3
"""bare_app's memory calibration screen against ddr-calibrate on a simulated PHY.

    board/common/buildroot/package/ddr-tools/test/memcal-app-test.py [--app BARE_APP] [--shots DIR]

bare_app (the PC build, apps/bare_app/build-host/bare_app, platform pc-mem,
854x480 as the GO Ultra) runs with BARE_APP_DDR_CALIBRATE = ddr-calibrate
built with -DDDR_SIM (sim-test.py's board) and BARE_APP_DDR_TUNE = a stand-in
ddr-tune that keeps its line in a file; the test drives it through its FIFO
(open, press, release, launch) and reads its log (-v). Screenshots
(SIGUSR1) go to --shots for a look.
"""
import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.abspath(os.path.join(HERE, "../../../../../.."))
spec = importlib.util.spec_from_file_location("simtest", os.path.join(HERE, "sim-test.py"))
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

TUNE = r'''#!/bin/sh
# ddr-tune's stand-in: the line in $D/kept, every call in $D/tune.calls
D=__DIR__
echo "$*" >> $D/tune.calls
case $1 in
"") echo "kept: $(cat $D/kept 2>/dev/null || echo none)"; echo "applied by U-Boot at this start: nothing" ;;
set) echo "$2" > $D/kept; echo "kept: $2" ;;
clear) rm -f $D/kept; echo "kept: none" ;;
esac
'''


class App:
    def __init__(self, app, work, shots):
        self.work, self.shots, self.n = work, shots, 0
        self.board = sim.base_board(os.path.join(work, "board"))
        self.binary = os.path.join(work, "ddr-calibrate-sim")
        subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O2", "-pthread", "-DDDR_SIM",
                        "-o", self.binary, sim.SRC], check=True)
        cal = os.path.join(work, "ddr-calibrate")
        with open(cal, "w") as f:
            f.write("#!/bin/sh\nDDR_SIM_DIR=%s DDR_SIM_SCALE=%s exec %s \"$@\"\n" %
                    (self.board.d, sim.SCALE, self.binary))
        os.chmod(cal, 0o755)
        tune = os.path.join(work, "ddr-tune")
        with open(tune, "w") as f:
            f.write(TUNE.replace("__DIR__", work))
        os.chmod(tune, 0o755)
        self.fifo = os.path.join(work, "ctl")
        os.mkfifo(self.fifo)
        self.shot_ppm = os.path.join(work, "shot.ppm")
        self.logf = open(os.path.join(work, "app.log"), "w+")
        env = dict(os.environ, BARE_APP_SIZE="854x480", BARE_APP_LANG="ru", BARE_APP_CTL=self.fifo,
                   BARE_APP_SHOT=self.shot_ppm, BARE_APP_DDR_CALIBRATE=cal, BARE_APP_DDR_TUNE=tune,
                   BARE_APP_CONFIG=os.path.join(work, "settings.conf"), HOME=work)
        self.p = subprocess.Popen([app, "-p", "pc-mem", "-v"], stdin=subprocess.PIPE, stdout=self.logf,
                                  stderr=subprocess.STDOUT, env=env, cwd=work)
        self.wait_log("view", 10)
        time.sleep(0.5)

    def log(self):
        self.logf.flush()
        with open(self.logf.name) as f:
            return f.read()

    def wait_log(self, text, timeout=60, after=0):
        end = time.time() + timeout
        while time.time() < end:
            if text in self.log()[after:]:
                return True
            if self.p.poll() is not None:
                return False
            time.sleep(0.1)
        return False

    def ctl(self, line):
        with open(self.fifo, "w") as f:
            f.write(line + "\n")
        time.sleep(0.15)

    def key(self, name, pause=0.35):
        self.ctl("press " + name)
        time.sleep(0.08)
        self.ctl("release " + name)
        time.sleep(pause)

    def shot(self, name):
        if not self.shots:
            return
        self.p.send_signal(signal.SIGUSR1)
        time.sleep(0.6)
        if os.path.exists(self.shot_ppm):
            self.n += 1
            out = os.path.join(self.shots, "%02d-%s.png" % (self.n, name))
            subprocess.run(["convert", self.shot_ppm, out], check=False)

    def calls(self):
        p = os.path.join(self.work, "tune.calls")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def kept(self):
        p = os.path.join(self.work, "kept")
        return open(p).read().strip() if os.path.exists(p) else None

    def quit(self):
        self.p.send_signal(signal.SIGTERM)
        try:
            self.p.wait(10)
        except subprocess.TimeoutExpired:
            self.p.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=os.path.join(SDK, "apps/bare_app/build-host/bare_app"))
    ap.add_argument("--shots")
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    bad = []

    def cell(name, ok, detail=""):
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "\n        " + detail))
        if not ok:
            bad.append(name)

    work = tempfile.mkdtemp(prefix="memcal-app-")
    app = App(a.app, work, a.shots)
    b = app.board
    s0 = b.regs()
    exp = b.expected()
    try:
        app.ctl("open memcal")
        cell("open: the status is read", app.wait_log("memcal: kept: 0 lane(s)", 10), app.log()[-500:])
        app.shot("rest")

        # a run to its end, saved
        mark = len(app.log())
        app.key("a")            # Start (the first row)
        app.shot("ask")
        app.key("down")         # Cancel -> Start
        app.key("a")
        cell("start: ddr-calibrate -p runs", app.wait_log("memcal: %s -p" % os.path.join(work, "ddr-calibrate"), 5, mark),
             app.log()[mark:][-500:])
        app.wait_log("progress", 3)
        time.sleep(3)
        app.shot("running")
        # a game is refused meanwhile
        app.ctl("back")
        time.sleep(0.5)
        app.shot("running-settings-statusbar")
        app.ctl("launch doom")
        cell("launch while running: refused", app.wait_log("doom not started: the memory calibration runs", 5, mark),
             app.log()[mark:][-800:])
        time.sleep(1)
        app.shot("game-refused")
        app.key("b")
        app.ctl("open memcal")
        cell("done: the run ended with its lanes", app.wait_log("memcal: done: %d lane(s) to correct" % len(exp), 90, mark),
             app.log()[mark:][-800:])
        time.sleep(0.5)
        app.shot("done")
        built = app.log()[mark:].count("memcal: built")
        mark = len(app.log())
        app.key("down")          # Save
        app.key("a")
        cell("save: ddr-tune set with the run's line", app.wait_log("memcal: kept: 1", 5, mark) and
             app.kept() is not None and sim.parse_line(app.kept()) == exp, "kept %s, expected %s; calls %s" %
             (app.kept(), exp, app.calls()))
        time.sleep(0.5)
        cell("save: the screen built once", app.log()[mark:].count("memcal: built") == 1,
             "%d builds" % app.log()[mark:].count("memcal: built"))
        app.shot("saved")
        cell("after the run: registers as at the start, /data thawed", b.regs() == s0 and
             not os.path.exists(b.path("frozen")))

        # a run stopped
        mark = len(app.log())
        app.ctl("back")
        app.ctl("open memcal")
        time.sleep(0.5)
        app.shot("saved-reopened")
        app.key("down")          # Restart now -> Start the calibration
        app.key("a")
        app.key("down")
        app.key("a")
        app.wait_log("progress", 5, mark)
        time.sleep(2)
        app.key("a")             # Stop the calibration
        cell("stop: it ended as stopped", app.wait_log("ended (status", 10, mark) and "stopped" in app.log()[mark:],
             app.log()[mark:][-500:])
        time.sleep(0.8)
        app.shot("stopped")
        cell("stop: nothing to go on with", "interrupted run: 0 part(s) (0)" in app.log()[mark:],
             app.log()[mark:][-600:])

        # a run killed (SIGKILL): bare_app puts its registers back
        mark = len(app.log())
        app.key("a")             # Start (the rows: Start, Remove)
        app.key("down")
        app.key("a")
        app.wait_log("progress", 5, mark)
        time.sleep(4)
        moved = b.regs() != s0
        subprocess.run(["pkill", "-KILL", "-f", app.binary])
        cell("kill: ended as killed", app.wait_log("killed", 10, mark), app.log()[mark:][-500:])
        time.sleep(0.8)
        cell("kill: -R put the registers back, /data thawed", b.regs() == s0 and not os.path.exists(b.path("frozen")),
             "moved at the kill %s, now %s" % (moved, {hex(k): v for k, v in b.regs().items() if s0[k] != v}))
        cell("kill: the interrupted run is offered (this start)", "(1)" in app.log()[mark:].split("killed")[-1],
             app.log()[mark:][-600:])
        app.shot("killed")
    finally:
        app.quit()
    print("%d cells failed" % len(bad))
    if bad:
        print("log: " + app.logf.name)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
