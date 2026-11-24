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
    def __init__(self, app, work, shots, board=None, kept=None, prefix=""):
        self.work, self.shots, self.n, self.prefix = work, shots, 0, prefix
        self.board = board or sim.base_board(os.path.join(work, "board"))
        if kept:
            with open(os.path.join(work, "kept"), "w") as f:
                f.write(kept + "\n")
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
            out = os.path.join(self.shots, "%s%02d-%s.png" % (self.prefix, self.n, name))
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
        time.sleep(4)
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
        time.sleep(3)
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
        # SIGKILL while a register is moved (a probe or a lift), so -R has something to do
        moved = False
        end = time.time() + 30
        while time.time() < end and not moved:
            time.sleep(0.05)
            if b.regs() != s0:
                subprocess.run(["pkill", "-STOP", "-f", app.binary])
                moved = b.regs() != s0
                if not moved:
                    subprocess.run(["pkill", "-CONT", "-f", app.binary])
        subprocess.run(["pkill", "-KILL", "-f", app.binary])
        cell("kill: it was killed with a register moved", moved)
        cell("kill: ended as killed", app.wait_log("killed", 10, mark), app.log()[mark:][-500:])
        time.sleep(0.8)
        cell("kill: -R put the registers back, /data thawed", b.regs() == s0 and not os.path.exists(b.path("frozen")),
             "moved at the kill %s, now %s" % (moved, {hex(k): v for k, v in b.regs().items() if s0[k] != v}))
        # parts done: offered to go on (this start); none: nothing to go on with, "killed" said
        import re
        st = re.findall(r"interrupted run: (\d+) part\(s\) \((\d)\)", app.log()[mark:].split("killed")[-1])
        cell("kill: an interrupted run with parts is offered (this start), none is not",
             bool(st) and (st[-1][1] == "1" if int(st[-1][0]) > 0 else st[-1][1] == "0"), str(st))
        app.shot("killed")
    finally:
        app.quit()

    # one line to correct (bit 42): "bit", not "bits"
    work1 = os.path.join(work, "one")
    os.makedirs(work1)
    b1 = sim.base_board(os.path.join(work1, "board"), override={(3, 4): (0, 31, 11), (3, 5): (2, 31, 11)})
    app = App(a.app, work1, a.shots, board=b1, prefix="one-")
    try:
        exp1 = b1.expected()
        mark = len(app.log())
        app.ctl("open memcal")
        time.sleep(0.8)
        app.key("a")
        app.key("down")
        app.key("a")
        cell("one: done with one lane", len(exp1) == 1 and
             app.wait_log("memcal: done: 1 lane(s) to correct", 90, mark), str(exp1))
        time.sleep(0.5)
        cell("one: the note says 'бит 42'", "памяти, бит 42." in app.log()[mark:], app.log()[mark:][-400:])
        app.shot("done")
    finally:
        app.quit()

    # nothing to correct, corrections kept from before: saving removes them, and says so
    work2 = os.path.join(work, "none")
    os.makedirs(work2)
    b2 = sim.base_board(os.path.join(work2, "board"),
                        override={(1, 6): (2, 31, 11), (3, 4): (0, 31, 11), (3, 5): (2, 31, 11)})
    app = App(a.app, work2, a.shots, board=b2, kept="11668+c 13568+7", prefix="none-")
    try:
        mark = len(app.log())
        app.ctl("open memcal")
        time.sleep(0.8)
        app.key("a")
        app.key("down")
        app.key("a")
        cell("none: done with nothing to correct", b2.expected() == {} and
             app.wait_log("memcal: done: 0 lane(s) to correct", 90, mark), str(b2.expected()))
        time.sleep(0.5)
        cell("none: it says Save removes the 2 lines kept", "(2 линии) больше не нужны" in app.log()[mark:],
             app.log()[mark:][-400:])
        app.shot("done")
        app.key("down")      # Save
        app.key("a")
        time.sleep(1)
        cell("none: Save cleared them (ddr-tune clear)", "clear" in app.calls() and app.kept() is None,
             str(app.calls()))
        app.shot("saved")
    finally:
        app.quit()
    # a run left by a bare_app that died: the next one keeps the guards until it ends
    work3 = os.path.join(work, "orphan")
    os.makedirs(work3)
    b3 = sim.base_board(os.path.join(work3, "board"))
    s3 = b3.regs()
    app = App(a.app, work3, a.shots, board=b3, prefix="orphan-")
    app.ctl("open memcal")
    time.sleep(0.8)
    app.key("a")
    app.key("down")
    app.key("a")
    time.sleep(2)
    app.p.kill()
    app.p.wait()
    w4 = os.path.join(work3, "second")
    os.makedirs(w4)
    app2 = App(a.app, w4, a.shots, board=b3, prefix="orphan2-")
    try:
        cell("orphan: the next bare_app sees it run", app2.wait_log("a calibration started before runs", 5),
             app2.log()[-400:])
        app2.ctl("launch doom")
        cell("orphan: a game refused meanwhile", app2.wait_log("doom not started: the memory calibration runs", 5),
             app2.log()[-400:])
        app2.key("b")
        mark = len(app2.log())
        app2.ctl("open memcal")
        time.sleep(1)
        app2.shot("screen")
        app2.key("a")         # no row to start from: nothing happens
        app2.key("down")
        app2.key("a")
        time.sleep(1)
        cell("orphan: nothing offered to start, none started",
             "ddr-calibrate -p" not in app2.log()[mark:] and "fail busy" not in app2.log()[mark:],
             app2.log()[mark:][-400:])
        cell("orphan: its end seen, -R, guards gone", app2.wait_log("the calibration started before has ended", 90),
             app2.log()[-400:])
        time.sleep(0.5)
        cell("orphan: registers as at the start, /data thawed", b3.regs() == s3 and not os.path.exists(b3.path("frozen")))
    finally:
        app2.quit()
    # bare_app and then its ddr-calibrate killed, nobody watching: the next bare_app runs -R at its start
    work5 = os.path.join(work, "unwatched")
    os.makedirs(work5)
    b5 = sim.base_board(os.path.join(work5, "board"))
    s5 = b5.regs()
    app = App(a.app, work5, a.shots, board=b5, prefix="unwatched-")
    app.ctl("open memcal")
    time.sleep(0.8)
    app.key("a")
    app.key("down")
    app.key("a")
    time.sleep(2)
    app.p.kill()
    app.p.wait()
    moved = False
    end = time.time() + 30
    while time.time() < end and not moved:
        time.sleep(0.05)
        if b5.regs() != s5:
            subprocess.run(["pkill", "-STOP", "-f", app.binary])
            moved = b5.regs() != s5
            if not moved:
                subprocess.run(["pkill", "-CONT", "-f", app.binary])
    subprocess.run(["pkill", "-KILL", "-f", app.binary])
    time.sleep(0.5)
    cell("unwatched: killed with a register moved, /data frozen", moved and os.path.exists(b5.path("frozen")))
    w6 = os.path.join(work5, "second")
    os.makedirs(w6)
    app2 = App(a.app, w6, a.shots, board=b5, prefix="unwatched2-")
    try:
        time.sleep(1)
        cell("unwatched: the next bare_app put the registers back at its start, /data thawed",
             b5.regs() == s5 and not os.path.exists(b5.path("frozen")), app2.log()[-400:])
    finally:
        app2.quit()
    print("%d cells failed" % len(bad))
    if bad:
        print("log: " + app.logf.name)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
