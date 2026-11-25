#!/usr/bin/env python3
"""
Tests of bare-backup (board/common/buildroot/rootfs-overlay/usr/sbin/bare-backup, the
copies of saved games) on the PC: every place of it a fresh directory under a
temporary one (BARE_BACKUP_DATA, _GAMES, _RUN, _CONF, _CTL, _RELEASE), games.json
written here as bare_app writes it (its pid this process), bare_app's FIFO a FIFO
read by a thread of the test. Nothing of /data, /games or lab/: the saved games are
made here.

  python3 scripts/test-bare-backup.py [-v] [Test.test_name]
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BARE_BACKUP = os.path.join(SDK, "board", "common", "buildroot", "rootfs-overlay", "usr", "sbin",
                           "bare-backup")


def tree_md5(top):
    """{relative path: md5} of the files, and the directories, of top"""
    out = {}
    for d, dirs, files in os.walk(top):
        rel = os.path.relpath(d, top)
        out["D " + rel] = ""
        for f in files:
            with open(os.path.join(d, f), "rb") as fh:
                out[os.path.join(rel, f)] = hashlib.md5(fh.read()).hexdigest()
    return out


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


class Fifo:
    """bare_app's FIFO: the lines written into it"""
    def __init__(self, path):
        self.path, self.lines = path, []
        os.mkfifo(path)
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        self.stop = False
        self.t = threading.Thread(target=self.read, daemon=True)
        self.t.start()

    def read(self):
        buf = b""
        while not self.stop:
            try:
                b = os.read(self.fd, 4096)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            buf += b
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.lines.append(line.decode())

    def wait_lines(self, n, timeout=3):
        end = time.time() + timeout
        while len(self.lines) < n and time.time() < end:
            time.sleep(0.02)
        return self.lines

    def close(self):
        self.stop = True
        self.t.join()
        os.close(self.fd)


class Test(unittest.TestCase):
    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="bare-backup-test-")
        t = self.top
        self.data, self.games, self.run_dir = (os.path.join(t, n) for n in ("data", "games", "run"))
        for d in (self.data, self.games, self.run_dir):
            os.makedirs(d)
        self.conf = os.path.join(t, "bare_app.conf")
        self.release = os.path.join(t, "sdk-release")
        put(self.conf, "# bare_app settings\nlang=ru\nwifi=1\nbluetooth=1\n"
                       "controls.0000abcd=a=b\noptions.0000abcd=fps=30\ncontrols.11111111=x=y\n")
        put(self.release, "FIRMWARE=ogu\nSDK=test123\n")
        self.fifo = Fifo(os.path.join(t, "ctl"))
        # a Windows game (its tree and a "saves" in the profile), a game of its own
        self.pir_tree = os.path.join(self.data, "wine", "games", "pirates")
        self.pir_saves = os.path.join(self.data, "wine", "prefix", "drive_c", "users", "root",
                                      "Documents", "My Games", "pirates")
        put(os.path.join(self.pir_saves, "Начало.pirates_savegame"), os.urandom(70000))
        put(os.path.join(self.pir_saves, "Config.ini"), "[a]\nb=1\n")
        # Wine leaves files of 1970 in the profile (a zip has no dates before 1980)
        put(os.path.join(self.pir_saves, "Config.ini.wd2"), "old")
        os.utime(os.path.join(self.pir_saves, "Config.ini.wd2"), (0, 0))
        os.makedirs(os.path.join(self.pir_saves, "empty"))
        self.h3 = [os.path.join(self.data, p) for p in ("vcmi", "config/vcmi", "cache/vcmi")]
        put(os.path.join(self.h3[0], "Saves", "1.vsgm1"), os.urandom(5000))
        put(os.path.join(self.h3[1], "settings.json"), "{}")
        self.running = None
        self.write_state()
        self.env = dict(os.environ, BARE_BACKUP_DATA=self.data, BARE_BACKUP_GAMES=self.games,
                        BARE_BACKUP_RUN=self.run_dir, BARE_BACKUP_CONF=self.conf,
                        BARE_BACKUP_CTL=self.fifo.path, BARE_BACKUP_RELEASE=self.release)

    def tearDown(self):
        self.fifo.close()
        # our own tree only: no mount in it
        with open("/proc/mounts") as f:
            self.assertFalse(any(" " + self.top in line for line in f))
        for d, dirs, files in os.walk(self.top):
            os.chmod(d, 0o755)
        shutil.rmtree(self.top)

    def write_state(self, pid=None):
        games = [
            {"folder": "pirates", "name": "Pirates", "kind": "wine", "key": "0000abcd",
             "dir": os.path.join(self.games, "pirates"), "storage": [self.pir_tree, self.pir_saves],
             "available": True, "has_layer": False},
            {"folder": "homm3", "name": "Heroes", "kind": "homm3", "key": "2222beef",
             "dir": os.path.join(self.games, "heroes3"), "storage": self.h3, "available": True},
            {"folder": "evil", "name": "Evil", "kind": "wine", "key": "33333333",
             "dir": os.path.join(self.games, "evil"), "storage": ["/etc", self.data, "../x"]},
        ]
        state = {"version": 1, "pid": pid or os.getpid(), "running": self.running, "games": games}
        put(os.path.join(self.run_dir, "games.json"), json.dumps(state))

    def bb(self, *args, ok=True, env=None):
        r = subprocess.run([sys.executable, "-S", BARE_BACKUP] + list(args), env=env or self.env,
                           capture_output=True, text=True, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def backup(self, what="pirates", *more):
        return self.bb("backup", what, *more).stdout.strip().splitlines()[-1]

    # ---- the hooks ----

    def test_partial_hooks_refused(self):
        env = dict(os.environ, BARE_BACKUP_DATA=self.data)
        r = self.bb("list", ok=False, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("refused", r.stderr)
        env = dict(self.env, BARE_BACKUP_GAMES="")
        self.assertEqual(self.bb("list", ok=False, env=env).returncode, 2)

    def test_no_bare_app(self):
        os.unlink(os.path.join(self.run_dir, "games.json"))
        r = self.bb("backup", "pirates", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("bare_app не запущен", r.stderr)
        # a pid that is gone
        p = subprocess.Popen(["true"])
        p.wait()
        self.write_state(pid=p.pid)
        self.assertIn("bare_app не запущен", self.bb("backup", "pirates", ok=False).stderr)

    # ---- backup and restore ----

    def test_backup_restore_md5(self):
        before = tree_md5(self.pir_saves)
        put(os.path.join(self.games, "recipes", "pirates", "wine.ini"), "mode = 1024x768\n")
        path = self.backup()
        # on the card (a directory here) without a DIR
        self.assertTrue(path.startswith(os.path.join(self.games, "backups", "saves-pirates-")), path)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            m = json.loads(z.read("manifest.json"))
            self.assertIn("recipe/wine.ini", names)
            self.assertIn("settings.ini", names)
            st = z.read("settings.ini").decode()
            self.assertIn("controls.0000abcd=a=b", st)
            self.assertIn("options.0000abcd=fps=30", st)
            self.assertNotIn("11111111", st)
            self.assertTrue(any(n.startswith("data/wine/prefix/drive_c/users/root/Documents/My Games/"
                                             "pirates/Начало") for n in names))
        self.assertEqual(m["unit"], "test")
        self.assertEqual(m["system"], "test123")
        g = m["games"][0]
        self.assertEqual([d["exists"] for d in g["dirs"]], [False, True])
        self.assertEqual(g["dirs"][1]["files"], 3)
        # changed after the copy, then the copy back
        put(os.path.join(self.pir_saves, "Config.ini"), "changed")
        put(os.path.join(self.pir_saves, "new.sav"), "new")
        shutil.rmtree(os.path.join(self.games, "recipes", "pirates"))
        r = self.bb("restore", path)
        self.assertEqual(tree_md5(self.pir_saves), before)
        self.assertFalse(os.path.exists(self.pir_saves + ".bak"))
        self.assertFalse(os.path.exists(self.pir_saves + ".new-restore"))
        self.assertEqual(json.loads(r.stdout)["restored"], ["pirates"])
        # the settings through bare_app's FIFO, the layer back on the card, then reload
        lines = self.fifo.wait_lines(2)
        imp = os.path.join(self.run_dir, "import-pirates.ini")
        self.assertIn("import-settings " + imp, lines)
        self.assertIn("reload pirates", lines)
        # homm3 has no layer: its settings imported, no "reload"
        path = self.backup("homm3")
        self.bb("restore", path)
        lines = self.fifo.wait_lines(3)
        time.sleep(0.2)
        self.assertIn("import-settings " + os.path.join(self.run_dir, "import-homm3.ini"), lines)
        self.assertNotIn("reload homm3", self.fifo.lines)
        with open(imp) as f:
            self.assertIn("controls.0000abcd=a=b", f.read())
        with open(os.path.join(self.games, "recipes", "pirates", "wine.ini")) as f:
            self.assertEqual(f.read(), "mode = 1024x768\n")
        # bare_app.conf itself untouched by bare-backup
        with open(self.conf) as f:
            self.assertIn("controls.11111111=x=y", f.read())

    def test_backup_without_card_into_data(self):
        env = dict(self.env, BARE_BACKUP_GAMES=os.path.join(self.top, "no-card"))
        r = self.bb("backup", "homm3", env=env)
        path = r.stdout.strip()
        self.assertTrue(path.startswith(os.path.join(self.data, "backups", "saves-homm3-")), path)
        # a DIR outside /data and the card is refused
        r = self.bb("backup", "homm3", "/tmp", ok=False)
        self.assertEqual(r.returncode, 2)

    def test_restore_homm3_md5(self):
        before = [tree_md5(d) for d in self.h3[:2]]
        path = self.backup("homm3")
        for d in self.h3[:2]:
            put(os.path.join(d, "junk"), "x")
        self.bb("restore", path)
        self.assertEqual([tree_md5(d) for d in self.h3[:2]], before)
        self.assertFalse(os.path.exists(self.h3[2]))	# not in the copy: not made

    def test_damaged_zip_keeps_data(self):
        path = self.backup()
        put(os.path.join(self.pir_saves, "Config.ini"), "mine now")
        before = tree_md5(self.pir_saves)
        with open(path, "rb") as f:
            data = bytearray(f.read())
        # a byte of the big save's compressed data
        with zipfile.ZipFile(path) as z:
            info = [i for i in z.infolist() if i.filename.endswith(".pirates_savegame")][0]
        off = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 100
        data[off] ^= 0xff
        with open(path, "wb") as f:
            f.write(bytes(data))
        r = self.bb("restore", path, ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(tree_md5(self.pir_saves), before)
        self.assertEqual(os.listdir(os.path.dirname(self.pir_saves)), ["pirates"])

    def test_md5_mismatch_keeps_data(self):
        """unpacked whole but not what the manifest says: nothing changed"""
        path = self.backup()
        put(os.path.join(self.pir_saves, "Config.ini"), "mine now")
        before = tree_md5(self.pir_saves)
        bad = path + ".bad.zip"
        with zipfile.ZipFile(path) as z, zipfile.ZipFile(bad, "w") as out:
            for i in z.infolist():
                d = z.read(i)
                if i.filename == "manifest.json":
                    m = json.loads(d)
                    m["games"][0]["dirs"][1]["md5"] = "0" * 32
                    d = json.dumps(m).encode()
                out.writestr(i, d)
        self.assertEqual(self.bb("restore", bad, ok=False).returncode, 1)
        self.assertEqual(tree_md5(self.pir_saves), before)
        self.assertEqual(os.listdir(os.path.dirname(self.pir_saves)), ["pirates"])

    def test_swap_failure_puts_old_back(self):
        """the second directory cannot be moved in: the first one is put back too"""
        path = self.backup("homm3")
        for d in self.h3[:2]:
            put(os.path.join(d, "mine"), "x")
        before = [tree_md5(d) for d in self.h3[:2]]
        r = self.bb("restore", path, ok=False, env=dict(self.env, BARE_BACKUP_SWAP_FAIL="1"))
        self.assertIn("the move of", r.stderr)
        self.assertEqual(r.returncode, 1)
        self.assertEqual([tree_md5(d) for d in self.h3[:2]], before)
        for d in self.h3[:2]:
            self.assertFalse(os.path.exists(d + ".bak"))
            self.assertFalse(os.path.exists(d + ".new-restore"))
        # a directory that cannot be unpacked beside its place: nothing changed either
        parent = os.path.dirname(self.h3[1])
        os.chmod(parent, 0o555)
        try:
            self.assertNotEqual(self.bb("restore", path, ok=False).returncode, 0)
        finally:
            os.chmod(parent, 0o755)
        self.assertEqual([tree_md5(d) for d in self.h3[:2]], before)

    def test_other_games_dir_refused(self):
        """a manifest naming a directory of /data that is not the game's here, its
        files with it: refused"""
        other = os.path.join(self.data, "wine", "games", "other")
        put(os.path.join(other, "keep"), "mine")
        bad = os.path.join(self.top, "other.zip")
        m = {"format": 1, "kind": "game", "games": [
            {"folder": "pirates", "prefix": "", "dirs": [
                {"path": other, "rel": "wine/games/other", "exists": True, "md5": "x"}]}]}
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("manifest.json", json.dumps(m))
            z.writestr("data/wine/games/other/keep", "theirs")
        r = self.bb("restore", bad, ok=False)
        self.assertIn("не относится к игре pirates", r.stderr)
        with open(os.path.join(other, "keep")) as f:
            self.assertEqual(f.read(), "mine")

    def zip_with(self, path, name, data=b"x", attr=None):
        out = path + ".evil.zip"
        with zipfile.ZipFile(path) as z, zipfile.ZipFile(out, "w") as o:
            for i in z.infolist():
                o.writestr(i, z.read(i))
            zi = zipfile.ZipInfo(name)
            if attr is not None:
                zi.external_attr = attr
            o.writestr(zi, data)
        return out

    def test_paths_refused(self):
        path = self.backup()
        before = tree_md5(self.data)
        for name in ("data/wine/prefix/drive_c/users/root/Documents/My Games/pirates/../../../../x",
                     "../x", "/etc/passwd", "data/etc/x", "data/wine/games/other/x", "recipe/../../x",
                     "games/x/settings.ini"):
            r = self.bb("restore", self.zip_with(path, name), ok=False)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("Недопустимый путь", r.stderr, name)
        # a link
        r = self.bb("restore", self.zip_with(
            path, "data/wine/prefix/drive_c/users/root/Documents/My Games/pirates/l", b"/etc/passwd",
            attr=(stat.S_IFLNK | 0o777) << 16), ok=False)
        self.assertIn("Ссылка", r.stderr)
        # a manifest's directory outside /data or not the game's
        for bad in ("../etc", "etc", "wine/games/evil"):
            out = path + ".m.zip"
            with zipfile.ZipFile(path) as z, zipfile.ZipFile(out, "w") as o:
                for i in z.infolist():
                    d = z.read(i)
                    if i.filename == "manifest.json":
                        m = json.loads(d)
                        m["games"][0]["dirs"][1]["rel"] = bad
                        m["games"][0]["dirs"][1]["path"] = os.path.join(self.data, bad)
                        d = json.dumps(m).encode()
                    o.writestr(i, d)
            self.assertEqual(self.bb("restore", out, ok=False).returncode, 1, bad)
        self.assertEqual(tree_md5(self.data), before)

    def test_running_game_refused(self):
        path = self.backup()
        put(os.path.join(self.pir_saves, "Config.ini"), "mine now")
        before = tree_md5(self.pir_saves)
        self.running = {"folder": "pirates", "key": "0000abcd", "pid": os.getpid()}
        self.write_state()
        r = self.bb("restore", path, ok=False)
        self.assertEqual(r.returncode, 3)
        self.assertIn("запущена", r.stderr)
        self.assertEqual(tree_md5(self.pir_saves), before)
        # another game runs: this one is restored
        self.running = {"folder": "homm3", "key": "2222beef", "pid": os.getpid()}
        self.write_state()
        self.bb("restore", path)

    def test_evil_storage_left_out(self):
        path = self.backup("evil")
        with zipfile.ZipFile(path) as z:
            self.assertFalse([n for n in z.namelist() if n.startswith("data/")])
            m = json.loads(z.read("manifest.json"))
        self.assertEqual(m["games"][0]["dirs"], [])
        self.assertEqual(len(m["games"][0]["skipped"]), 3)

    # ---- automatic copies ----

    def test_auto(self):
        r = self.bb("auto", "pirates")
        first = r.stdout.strip()
        self.assertTrue(first.endswith("-auto.zip"), first)
        self.assertTrue(os.path.exists(os.path.join(self.data, "backups", ".stamp-pirates")))
        # nothing changed: no copy
        self.assertEqual(self.bb("auto", "pirates").stdout.strip(), "unchanged")
        self.assertEqual(len(os.listdir(os.path.dirname(first))), 1)
        # a save changed, the settings changed: a copy each
        made = [first]
        for i in range(4):
            time.sleep(1.05)	# another name: the date has seconds
            if i % 2:
                with open(self.conf, "a") as f:
                    f.write("options.0000abcd=fps=%d\n" % (40 + i))
            else:
                put(os.path.join(self.pir_saves, "Config.ini"), "v%d" % i)
            out = self.bb("auto", "pirates").stdout.strip()
            self.assertNotEqual(out, "unchanged", i)
            made.append(out)
        # the last three kept; a copy made by hand is not counted
        left = sorted(os.listdir(os.path.dirname(first)))
        self.assertEqual(left, sorted(os.path.basename(p) for p in made[-3:]))
        hand = self.backup()
        time.sleep(1.05)
        put(os.path.join(self.pir_saves, "Config.ini"), "v9")
        self.bb("auto", "pirates")
        self.assertIn(os.path.basename(hand), os.listdir(os.path.dirname(first)))
        self.assertEqual(len([n for n in os.listdir(os.path.dirname(first)) if n.endswith("-auto.zip")]), 3)

    def test_auto_nothing(self):
        shutil.rmtree(self.pir_saves)
        self.assertEqual(self.bb("auto", "pirates").stdout.strip(), "nothing")
        self.assertFalse(os.path.exists(os.path.join(self.games, "backups")))

    # ---- everything ----

    def test_all(self):
        put(os.path.join(self.games, "recipes", "pirates", "wine.ini"), "mode = 1024x768\n")
        put(os.path.join(self.games, "recipes", "worms", "wine.ini"), "mode = 640x480\n")
        path = self.backup("all")
        self.assertIn("saves-all-", path)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            conf = z.read("bare_app.conf").decode()
            m = json.loads(z.read("manifest.json"))
        self.assertIn("lang=ru", conf)
        self.assertNotIn("wifi", conf)
        self.assertNotIn("bluetooth", conf)
        self.assertIn("games/pirates/settings.ini", names)
        self.assertIn("games/homm3/settings.ini", names)
        self.assertIn("recipes/worms/wine.ini", names)
        self.assertEqual(sorted(g["folder"] for g in m["games"]), ["evil", "homm3", "pirates"])
        self.assertEqual(m["recipes"], ["pirates", "worms"])
        # one game of it back
        before = tree_md5(self.h3[0])
        put(os.path.join(self.h3[0], "junk"), "x")
        put(os.path.join(self.pir_saves, "Config.ini"), "kept")
        r = self.bb("restore", path, "--game", "homm3")
        self.assertEqual(json.loads(r.stdout)["restored"], ["homm3"])
        self.assertEqual(tree_md5(self.h3[0]), before)
        with open(os.path.join(self.pir_saves, "Config.ini")) as f:
            self.assertEqual(f.read(), "kept")
        # all of it back: the recipes too
        shutil.rmtree(os.path.join(self.games, "recipes"))
        self.bb("restore", path)
        with open(os.path.join(self.games, "recipes", "worms", "wine.ini")) as f:
            self.assertEqual(f.read(), "mode = 640x480\n")
        with open(os.path.join(self.pir_saves, "Config.ini")) as f:
            self.assertEqual(f.read(), "[a]\nb=1\n")

    def test_list_info(self):
        path = self.backup()
        out = json.loads(self.bb("list").stdout)
        self.assertEqual([c["name"] for c in out["copies"]], [os.path.basename(path)])
        self.assertEqual(out["copies"][0]["where"], "card")
        pir = [g for g in out["games"] if g["folder"] == "pirates"][0]
        self.assertEqual(pir["files"], 3)
        self.assertGreater(pir["size"], 70000)
        info = json.loads(self.bb("info", path).stdout)
        self.assertEqual(info["games"][0]["folder"], "pirates")
        r = self.bb("info", self.conf, ok=False)
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
