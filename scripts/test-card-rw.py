#!/usr/bin/env python3
"""
Tests of card-rw (board/common/buildroot/rootfs-overlay/usr/sbin/card-rw, the one count
of the games card's writers) on the PC: every place of it under a temporary directory
(CARD_RW_*), the card a line of a made-up /proc/mounts, "mount" a script of the test
that changes that line and writes each call into a file. Nothing is mounted.

  python3 scripts/test-card-rw.py [-v] [Test.test_name]
"""
import os
import shutil
import subprocess
import tempfile
import threading
import unittest

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_RW = os.path.join(SDK, "board", "common", "buildroot", "rootfs-overlay", "usr", "sbin", "card-rw")

# mount -o remount,rw|ro DIR: the line of DIR in $CARD_RW_MOUNTS changed, the call
# written into $T/calls; $T/busy holds how many read-only remounts still fail
# (EBUSY), $T/no-rw makes the writable one fail
MOUNT = r"""#!/bin/sh
[ "$1" = -o ] || exit 9
how=${2#remount,}
echo "$how $3" >> "$T/calls"
if [ "$how" = ro ] && [ -f "$T/busy" ]; then
	n=$(cat "$T/busy")
	if [ "$n" -gt 0 ]; then
		echo $((n - 1)) > "$T/busy"
		echo "mount: $3: target is busy" >&2
		exit 32
	fi
fi
[ "$how" = rw ] && [ -e "$T/no-rw" ] && { echo "mount: cannot" >&2; exit 32; }
sed -i "s#^\(card $3 exfat \)[a-z]*,#\1$how,#" "$CARD_RW_MOUNTS"
"""


class Test(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="card-rw-test-")
        t = self.t
        self.cardp = os.path.join(t, "games")
        os.makedirs(self.cardp)
        self.mounts = os.path.join(t, "mounts")
        self.mount_bin = os.path.join(t, "mount")
        with open(self.mount_bin, "w") as f:
            f.write(MOUNT)
        os.chmod(self.mount_bin, 0o755)
        self.set_card("ro")
        self.env = dict(os.environ, T=t, CARD_RW_CARD=self.cardp, CARD_RW_STATE=os.path.join(t, "state"),
                        CARD_RW_LOCK=os.path.join(t, "lock"), CARD_RW_MOUNTS=self.mounts,
                        CARD_RW_MOUNT=self.mount_bin, CARD_RW_LOG=os.path.join(t, "log"),
                        CARD_RW_PAUSE="0.05", CARD_RW_TRIES="5")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        with open("/proc/mounts") as f:
            self.assertFalse(any(" " + self.t in line for line in f))
        shutil.rmtree(self.t)

    def set_card(self, how, there=True):
        with open(self.mounts, "w") as f:
            f.write("/dev/root / ext4 rw 0 0\n")
            if there:
                f.write("card %s exfat %s,noatime 0 0\n" % (self.cardp, how))

    def card(self):
        with open(self.mounts) as f:
            for line in f:
                p = line.split()
                if p[1] == self.cardp:
                    return p[3].split(",")[0]
        return None

    def calls(self):
        try:
            with open(os.path.join(self.t, "calls")) as f:
                return [line.split()[0] for line in f]
        except FileNotFoundError:
            return []

    def cr(self, *args, env=None):
        r = subprocess.run([CARD_RW] + [str(a) for a in args], env=env or self.env,
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr

    def writer(self):
        """a process that stands for a writer (its pid)"""
        p = subprocess.Popen(["sleep", "60"])
        self.procs.append(p)
        return p

    def ok(self, *args):
        rc, out, err = self.cr(*args)
        self.assertEqual(rc, 0, err)
        return out

    def test_one_writer(self):
        a = self.writer()
        self.ok("begin", a.pid)
        self.assertEqual(self.card(), "rw")
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "ro"])
        self.assertEqual(os.listdir(self.env["CARD_RW_STATE"]), [])

    def test_nested_writers(self):
        # two of them, the first ends first: one rw, one ro, after the second
        a, b = self.writer(), self.writer()
        self.ok("begin", a.pid)
        self.ok("begin", b.pid)
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "rw")
        self.ok("end", b.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "ro"])

    def test_same_process_twice(self):
        # bare-web: several requests of one process at once
        a = self.writer()
        self.ok("begin", a.pid)
        self.ok("begin", a.pid)
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "rw")
        self.assertIn("writers=1", self.ok("status"))
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "ro"])

    def test_caller_by_default(self):
        # no PID: the caller's (a shell's own pid, $PPID of card-rw)
        sh = "%s begin && %s status && %s end && %s status" % ((CARD_RW,) * 4)
        r = subprocess.run(["sh", "-c", sh], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split("\n")[:2], ["mounted=1 rw=1 writers=1 ours=1",
                                                    "mounted=1 rw=0 writers=0 ours=0"])

    def test_writable_before_is_left(self):
        # writable not by card-rw: nothing remounted, still writable after
        self.set_card("rw")
        a = self.writer()
        self.ok("begin", a.pid)
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "rw")
        self.assertEqual(self.calls(), [])

    def test_made_ro_meanwhile(self):
        # someone made it read-only while a writer was there: the next begin
        # makes it writable again, the last end read-only
        a, b = self.writer(), self.writer()
        self.ok("begin", a.pid)
        self.set_card("ro")
        self.ok("begin", b.pid)
        self.assertEqual(self.card(), "rw")
        self.ok("end", a.pid)
        self.ok("end", b.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "rw", "ro"])

    def test_killed_writer_with_another(self):
        a, b = self.writer(), self.writer()
        self.ok("begin", a.pid)
        a.kill()
        a.wait()
        self.ok("begin", b.pid)	# a dropped here
        self.assertIn("writers=1", self.ok("status"))
        self.ok("end", b.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "ro"])
        with open(self.env["CARD_RW_LOG"]) as f:
            self.assertIn("writer %d gone without its end" % a.pid, f.read())

    def test_killed_last_writer(self):
        # the last writer killed: the next card-rw of anyone (status here)
        # drops it and makes the card read-only
        a = self.writer()
        self.ok("begin", a.pid)
        a.kill()
        a.wait()
        self.assertEqual(self.card(), "rw")
        self.assertEqual(self.ok("status").strip(), "mounted=1 rw=0 writers=0 ours=0")
        self.assertEqual(self.calls(), ["rw", "ro"])

    def test_pid_of_another_process(self):
        # a writer's file whose pid is another process now (another start time)
        a, b = self.writer(), self.writer()
        self.ok("begin", a.pid)
        st = os.path.join(self.env["CARD_RW_STATE"], str(a.pid))
        with open(st) as f:
            p, start, c = f.read().split()
        with open(st, "w") as f:
            f.write("%s %d %s\n" % (p, int(start) - 1, c))
        self.ok("begin", b.pid)
        self.ok("end", b.pid)
        self.assertEqual(self.card(), "ro")

    def test_busy_then_free(self):
        a = self.writer()
        self.ok("begin", a.pid)
        with open(os.path.join(self.t, "busy"), "w") as f:
            f.write("2")
        self.ok("end", a.pid)
        self.assertEqual(self.card(), "ro")
        self.assertEqual(self.calls(), ["rw", "ro", "ro", "ro"])

    def test_busy_always(self):
        # stays writable, said so; the next end tries again
        a = self.writer()
        self.ok("begin", a.pid)
        with open(os.path.join(self.t, "busy"), "w") as f:
            f.write("5")
        rc, _, err = self.cr("end", a.pid)
        self.assertEqual(rc, 0)
        self.assertIn("stays writable", err)
        self.assertEqual(self.card(), "rw")
        self.assertEqual(self.calls(), ["rw"] + ["ro"] * 5)
        self.assertTrue(os.path.exists(os.path.join(self.env["CARD_RW_STATE"], "ours")))
        # the next card-rw (status here) tries again: no longer busy
        self.assertEqual(self.ok("status").strip(), "mounted=1 rw=0 writers=0 ours=0")
        self.assertEqual(self.calls(), ["rw"] + ["ro"] * 6)
        with open(self.env["CARD_RW_LOG"]) as f:
            self.assertIn("stays writable: mount: %s: target is busy" % self.cardp, f.read())

    def test_no_card(self):
        self.set_card("ro", there=False)
        a = self.writer()
        rc, _, err = self.cr("begin", a.pid)
        self.assertEqual(rc, 3)
        self.assertEqual(os.listdir(self.env["CARD_RW_STATE"]), [])
        self.assertEqual(self.calls(), [])

    def test_cannot_be_writable(self):
        open(os.path.join(self.t, "no-rw"), "w").close()
        a = self.writer()
        rc, _, err = self.cr("begin", a.pid)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be made writable", err)
        self.assertEqual(os.listdir(self.env["CARD_RW_STATE"]), [])
        self.assertEqual(self.card(), "ro")

    def test_end_without_begin(self):
        a = self.writer()
        rc, _, err = self.cr("end", a.pid)
        self.assertEqual(rc, 0)
        self.assertIn("has not begun", err)
        self.assertEqual(self.calls(), [])

    def test_partial_hooks_refused(self):
        env = dict(self.env)
        del env["CARD_RW_MOUNT"]
        rc, _, err = self.cr("status", env=env)
        self.assertEqual(rc, 2)
        self.assertIn("CARD_RW_MOUNT", err)
        env["CARD_RW_MOUNT"] = ""
        self.assertEqual(self.cr("status", env=env)[0], 2)

    def test_many_at_once(self):
        # writers beginning and ending in parallel: the card ends read-only,
        # as many rw as ro, the count never below zero
        ws = [self.writer() for _ in range(4)]
        errs = []

        def loop(w):
            for _ in range(8):
                for cmd in ("begin", "end"):
                    rc, _, err = self.cr(cmd, w.pid)
                    if rc:
                        errs.append(err)
        th = [threading.Thread(target=loop, args=(w,)) for w in ws]
        for x in th:
            x.start()
        for x in th:
            x.join()
        self.assertEqual(errs, [])
        self.assertEqual(self.card(), "ro")
        c = self.calls()
        self.assertEqual(c.count("rw"), c.count("ro"))
        self.assertGreaterEqual(c.count("rw"), 1)
        self.assertEqual(os.listdir(self.env["CARD_RW_STATE"]), [])


if __name__ == "__main__":
    unittest.main()
