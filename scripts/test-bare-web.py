#!/usr/bin/env python3
"""
Tests of bare-web (board/common/buildroot/rootfs-overlay/usr/lib/bare-web/
bare_web.py, the device in a browser) on the PC: the server runs in this process on a
free port of 127.0.0.1, every directory of it a fresh one under a temporary
directory (BARE_WEB_GAMES, BARE_WEB_DATA... and GAME_INSTALL_* for the real
scripts/game-install it runs), the device's programs (bare-report,
system-update, ab-state, usb-disk, unit, reboot) small scripts of the test.
No game of lab/ or of the PC, no link to one: the games are made here.

  python3 scripts/test-bare-web.py [-v] [Test.test_name]
"""
import fcntl
import http.client
import importlib.machinery
import importlib.util
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.parse
import zipfile

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY = os.path.join(SDK, "board", "common", "buildroot", "rootfs-overlay")
BARE_WEB = os.path.join(OVERLAY, "usr", "lib", "bare-web", "bare_web.py")
STATIC = os.path.join(OVERLAY, "usr", "share", "bare-web")
GAME_INSTALL = os.path.join(SDK, "scripts", "game-install")
BARE_BACKUP = os.path.join(OVERLAY, "usr", "sbin", "bare-backup")

TOP = tempfile.mkdtemp(prefix="bare-web-test-")
GAMES = os.path.join(TOP, "games")
DATA = os.path.join(TOP, "data")
LOGS = os.path.join(DATA, "logs")
BIN = os.path.join(TOP, "bin")
STATE = os.path.join(TOP, "state")	# what the fake programs read and write

FAKES = {
    # bare-report [GAME]: a report on the card, its path
    "bare-report": r"""#!/bin/sh
[ -n "$FAIL_REPORT" ] && { echo "bare-report: cannot" >&2; exit 1; }
mkdir -p "$BARE_WEB_GAMES/reports"
out="$BARE_WEB_GAMES/reports/2026-11-25_12-00-00${1:+-$1}.txt"
echo "a report of ${1:-nothing}" > "$out"
echo "$out"
""",
    "ab-state": r"""#!/bin/sh
S=$STATE/ab
case $1 in
"") echo running=a; cat "$S" 2>/dev/null || printf 'ab_slot=a\nab_try=none\nab_left=0\nab_failed=none\n' ;;
version) [ "$2" = a ] && echo "2026-11-25 aaaaaaa"; [ "$2" = b ] && [ -e "$STATE/has-b" ] && echo "2026-11-24 bbbbbbb"; exit 0 ;;
try) printf 'ab_slot=a\nab_try=%s\nab_left=3\nab_failed=none\n' "$2" > "$S"; echo "try $2" >> "$STATE/calls" ;;
running) echo a ;;
*) exit 1 ;;
esac
""",
    # system-update [--info] FILE: as the device's says it, nothing written
    "system-update": r"""#!/bin/sh
if [ "$1" = --info ]; then
	tar -xOf "$2" update.ini 2>/dev/null || { echo "system-update: $2: not an update (no update.ini)" >&2; exit 1; }
	exit 0
fi
echo "run $1" >> "$STATE/calls"
echo "step 1/6 check"
while [ -e "$STATE/hold-update" ]; do sleep 0.05; done
[ -e "$STATE/fail-update" ] && { echo "system-update: $1: SYSTEM is damaged" >&2; exit 1; }
for s in verify format unpack; do echo "step $s"; done | sed 's/step \(.*\)/step 2\/6 \1/'
echo "progress 50"
echo "progress 100"
echo "step 6/6 boot"
echo "done 2026-11-25 test123-dirty"
""",
    "usb-disk": "#!/bin/sh\n[ -e \"$STATE/usb-disk\" ] && exit 0\nexit 1\n",
    "unit": "#!/bin/sh\ncase $1 in label) echo ogu-test ;; net) echo 192.168.7 ;; esac\n",
    "reboot": "#!/bin/sh\necho reboot >> \"$STATE/calls\"\n",
}

ENV = {
    "BARE_WEB_GAMES": GAMES, "BARE_WEB_DATA": DATA, "BARE_WEB_LOGS": LOGS, "BARE_WEB_STATIC": STATIC,
    "BARE_WEB_LOG": os.path.join(TOP, "bare-web.log"), "BARE_WEB_POWER": os.path.join(TOP, "power"),
    "BARE_WEB_RELEASE": os.path.join(TOP, "sdk-release"), "BARE_WEB_GAME_INSTALL": GAME_INSTALL,
    "BARE_WEB_BARE_REPORT": os.path.join(BIN, "bare-report"),
    "BARE_WEB_SYSTEM_UPDATE": os.path.join(BIN, "system-update"),
    "BARE_WEB_AB_STATE": os.path.join(BIN, "ab-state"), "BARE_WEB_USB_DISK": os.path.join(BIN, "usb-disk"),
    "BARE_WEB_UNIT": os.path.join(BIN, "unit"), "BARE_WEB_REBOOT": os.path.join(BIN, "reboot"),
    "BARE_WEB_UPDATE_LOCK": os.path.join(STATE, "system-update.lock"), "BARE_WEB_NET": "192.168.7",
    "GAME_INSTALL_GAMES": GAMES, "GAME_INSTALL_DATA": DATA, "GAME_INSTALL_RECIPES": os.path.join(TOP, "recipes"),
    "GAME_INSTALL_REDIST": os.path.join(TOP, "system-redist"), "GAME_INSTALL_LOCK": os.path.join(STATE, "gi.lock"),
    "STATE": STATE,
    # bare-backup (the real one) in the same places
    "BARE_WEB_BARE_BACKUP": BARE_BACKUP, "BARE_BACKUP_DATA": DATA, "BARE_BACKUP_GAMES": GAMES,
    "BARE_BACKUP_RUN": os.path.join(TOP, "run"), "BARE_BACKUP_CONF": os.path.join(TOP, "bare_app.conf"),
    "BARE_BACKUP_CTL": os.path.join(TOP, "no-ctl"), "BARE_BACKUP_RELEASE": os.path.join(TOP, "sdk-release"),
    "BARE_BACKUP_UNIT": os.path.join(BIN, "unit"), "BARE_BACKUP_USB_DISK": os.path.join(BIN, "usb-disk"),
    # bare_app's places for the workshop and the check of a game (stages 4, 5)
    "BARE_WEB_RUN": os.path.join(TOP, "run"), "BARE_WEB_CONF": os.path.join(TOP, "bare_app.conf"),
    "BARE_WEB_CTL": os.path.join(TOP, "ctl"), "BARE_WEB_WINE": os.path.join(BIN, "bare_app_wine"),
    "BARE_WEB_SHOT": os.path.join(TOP, "run", "shot.ppm"), "BARE_WEB_NATIVE_DIRS": GAMES,
    "BARE_WEB_SYS_INPUT": os.path.join(TOP, "sys-input"), "BARE_WEB_DEV_INPUT": os.path.join(TOP, "dev-input"),
}
# bare_app_wine of the PC's build (a copy) for --actions and --defaults
HOST_WINE = os.path.join(SDK, "apps", "bare_app", "build-host-ut", "bare_app_wine")


def make_world():
    for d in (GAMES, DATA, LOGS, BIN, STATE, os.path.join(GAMES, "install"), os.path.join(GAMES, "redist"),
              os.path.join(GAMES, "updates"), ENV["GAME_INSTALL_REDIST"]):
        os.makedirs(d, exist_ok=True)
    for name, text in FAKES.items():
        p = os.path.join(BIN, name)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)
    with open(ENV["BARE_WEB_RELEASE"], "w") as f:
        f.write("FIRMWARE=ogu\nBUILT=2026-11-25\nSDK=test123\nBARE_APP=test456\n")
    bat = os.path.join(ENV["BARE_WEB_POWER"], "rk818-battery")
    os.makedirs(bat)
    with open(os.path.join(bat, "uevent"), "w") as f:
        f.write("POWER_SUPPLY_TYPE=Battery\nPOWER_SUPPLY_STATUS=Charging\nPOWER_SUPPLY_CAPACITY=77\n"
                "POWER_SUPPLY_VOLTAGE_NOW=4000000\n")
    # the recipes as post-build.sh copies them (a copy: no link into the SDK)
    r = ENV["GAME_INSTALL_RECIPES"]
    shutil.copytree(os.path.join(SDK, "games"), os.path.join(r, "games"),
                    ignore=shutil.ignore_patterns("__pycache__"), symlinks=False)
    os.makedirs(os.path.join(r, "scripts"))
    for f in ("gamerecipe.py", "game_pictures.py"):
        shutil.copy(os.path.join(SDK, "scripts", f), os.path.join(r, "scripts", f))
    os.makedirs(os.path.join(r, "apps", "bare_app", "ports", "wine"))
    shutil.copy(os.path.join(SDK, "apps", "bare_app", "ports", "wine", "wine.ini"),
                os.path.join(r, "apps", "bare_app", "ports", "wine", "wine.ini"))
    # installed games and their logs
    os.makedirs(os.path.join(GAMES, "coldfear"))
    with open(os.path.join(GAMES, "coldfear", "wine.ini"), "w") as f:
        f.write("; a test\nname = Cold Fear\nexe = ColdFear_retail.exe\n")
    with open(os.path.join(GAMES, "coldfear", "big.dat"), "wb") as f:
        f.write(b"x" * 300000)
    for n in (1, 2):
        os.makedirs(os.path.join(LOGS, "coldfear"), exist_ok=True)
        with open(os.path.join(LOGS, "coldfear", "%d.log" % n), "w") as f:
            f.write("bare_app: a launch of a game\nlaunch %d\n" % n)
    if os.path.isfile(HOST_WINE):
        shutil.copy(HOST_WINE, ENV["BARE_WEB_WINE"])
    os.makedirs(os.path.join(LOGS, "homm3"))
    with open(os.path.join(LOGS, "homm3", "1.log"), "w") as f:
        f.write("homm3 log\n")


os.environ.update(ENV)
make_world()
sys.dont_write_bytecode = True	# no __pycache__ in the SDK's overlay
loader = importlib.machinery.SourceFileLoader("bare_web", BARE_WEB)
spec = importlib.util.spec_from_loader("bare_web", loader)
bw = importlib.util.module_from_spec(spec)
loader.exec_module(bw)
bw.setup_log()
SERVER = bw.make_server("127.0.0.1", 0)
PORT = SERVER.server_address[1]
threading.Thread(target=SERVER.serve_forever, daemon=True).start()


def req(method, path, body=None, headers=None, timeout=30):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheaders(), data


def jreq(method, path, body=None):
    s, h, d = req(method, path, body)
    return s, json.loads(d)


def events(job, timeout=60):
    """the job's events up to its done or fail"""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    c.request("GET", "/api/job/%d/events" % job)
    r = c.getresponse()
    assert r.status == 200, r.status
    assert r.getheader("Content-Type").startswith("text/event-stream")
    out = []
    for raw in r:
        line = raw.decode().rstrip("\n")
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
            if out[-1]["type"] in ("done", "fail"):
                break
    c.close()
    return out


def calls():
    try:
        return open(os.path.join(STATE, "calls")).read().split("\n")
    except OSError:
        return []


def touch(p, data=b""):
    with open(p, "wb") as f:
        f.write(data)


def make_upd(path, firmware="ogu", version="2026-11-25-test"):
    """an update file as mkimage.sh makes it: update.ini first"""
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as t:
        for name, data in (("update.ini", ("FIRMWARE=%s\nVERSION=%s\nSYSTEM=system.tar.xz\nSHA256=00\n"
                                           "SIZE_MB=1\n" % (firmware, version)).encode()),
                           ("system.tar.xz", b"not really")):
            i = tarfile.TarInfo(name)
            i.size = len(data)
            t.addfile(i, io.BytesIO(data))


class Test(unittest.TestCase):

    def setUp(self):
        for f in ("usb-disk", "hold-update", "fail-update", "has-b", "calls", "ab"):
            p = os.path.join(STATE, f)
            if os.path.exists(p):
                os.remove(p)
        os.environ.pop("FAIL_REPORT", None)
        # no job left running by a test before
        deadline = time.time() + 10
        while bw.Jobs.running() and time.time() < deadline:
            time.sleep(0.05)

    def test_status(self):
        s, st = jreq("GET", "/api/status")
        self.assertEqual(s, 200)
        self.assertEqual(st["release"]["SDK"], "test123")
        self.assertEqual(st["ab"]["running"], "a")
        self.assertEqual(st["unit"], "ogu-test")
        self.assertTrue(st["card"]["mounted"])
        self.assertFalse(st["card"]["usb_disk"])
        self.assertIn("free_mb", st["card"]["room"])
        self.assertIn("free_mb", st["data"])
        self.assertEqual(st["battery"]["capacity"], 77)
        touch(os.path.join(STATE, "usb-disk"))
        self.assertTrue(jreq("GET", "/api/status")[1]["card"]["usb_disk"])

    def test_static(self):
        s, h, d = req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn("Установка игр", d.decode())
        s, h, d = req("GET", "/app.js")
        self.assertEqual(s, 200)
        self.assertIn("text/javascript", dict(h)["Content-Type"])
        self.assertEqual(req("GET", "/../bare-web")[0], 404)
        self.assertEqual(req("GET", "/%2e%2e/x")[0], 404)

    def test_upload_whole(self):
        data = os.urandom(3 * 1024 * 1024 + 17)
        s, h, d = req("PUT", "/api/upload/install/setup_tiny.exe", data)
        self.assertEqual(s, 200, d)
        p = os.path.join(GAMES, "install", "setup_tiny.exe")
        self.assertEqual(open(p, "rb").read(), data)
        self.assertFalse(os.path.exists(p + ".part"))
        # again: replaced whole
        s, h, d = req("PUT", "/api/upload/install/setup_tiny.exe", b"second")
        self.assertEqual(s, 200)
        self.assertEqual(open(p, "rb").read(), b"second")
        # a name in Russian, into redist
        s, h, d = req("PUT", "/api/upload/redist/%D0%A8%D1%80%D0%B8%D1%84%D1%82.ttf", b"font")
        self.assertEqual(s, 200, d)
        self.assertTrue(os.path.isfile(os.path.join(GAMES, "redist", "Шрифт.ttf")))
        os.remove(p)
        os.remove(os.path.join(GAMES, "redist", "Шрифт.ttf"))

    def test_upload_bad_names(self):
        before = sorted(os.listdir(TOP)), sorted(os.listdir(GAMES))
        for path in ("/api/upload/install/..", "/api/upload/install/a..b.exe", "/api/upload/install/.hidden",
                     "/api/upload/install/..%2F..%2Fx", "/api/upload/install/a%2Fb", "/api/upload/install/a%5Cb",
                     "/api/upload/etc/passwd", "/api/upload/install/", "/api/upload/install/x%00y"):
            s, h, d = req("PUT", path, b"evil")
            self.assertIn(s, (400, 404), path)
        self.assertEqual(before, (sorted(os.listdir(TOP)), sorted(os.listdir(GAMES))))
        self.assertEqual(sorted(os.listdir(os.path.join(GAMES, "install"))), [])

    def test_upload_short(self):
        """the computer goes away mid-file: no file of that name, no .part"""
        s = socket.create_connection(("127.0.0.1", PORT))
        s.sendall(b"PUT /api/upload/install/setup_cut.exe HTTP/1.1\r\nHost: x\r\n"
                  b"Content-Length: 5000000\r\n\r\n" + b"y" * 100000)
        s.shutdown(socket.SHUT_WR)
        s.settimeout(10)
        answer = b""
        while True:
            k = s.recv(4096)
            if not k:
                break
            answer += k
        s.close()
        self.assertIn(b" 400 ", answer.split(b"\r\n")[0])
        p = os.path.join(GAMES, "install", "setup_cut.exe")
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(p + ".part"))

    def test_part_not_in_scan(self):
        part = os.path.join(GAMES, "install", "setup_half.exe.part")
        touch(part, b"MZ half")
        touch(os.path.join(GAMES, "install", "setup_half-1.bin.part"), b"half")
        try:
            s, r = jreq("GET", "/api/install/scan")
            self.assertEqual(s, 200)
            self.assertEqual([e for e in r["entries"] if "half" in e["path"]], [])
            files = jreq("GET", "/api/files/install")[1]["files"]
            self.assertTrue(all(f["part"] for f in files if "half" in f["name"]))
            # a part is deleted by the page; an entry is not deleted that way
            self.assertEqual(req("DELETE", "/api/files/install/setup_half.exe.part")[0], 200)
            self.assertFalse(os.path.exists(part))
            touch(os.path.join(GAMES, "install", "keep.exe"))
            self.assertEqual(req("DELETE", "/api/files/install/keep.exe")[0], 400)
            self.assertTrue(os.path.exists(os.path.join(GAMES, "install", "keep.exe")))
        finally:
            for n in ("setup_half-1.bin.part", "keep.exe"):
                p = os.path.join(GAMES, "install", n)
                if os.path.exists(p):
                    os.remove(p)

    def test_upload_same_name(self):
        """one upload of a name at a time: the second would write the same .part"""
        c = socket.create_connection(("127.0.0.1", PORT))
        c.sendall(b"PUT /api/upload/install/setup_two.exe HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nab")
        part = os.path.join(GAMES, "install", "setup_two.exe.part")
        deadline = time.time() + 5
        while not os.path.exists(part) and time.time() < deadline:
            time.sleep(0.02)
        s, h, d = req("PUT", "/api/upload/install/setup_two.exe", b"0123456789")
        self.assertEqual(s, 409, d)
        c.sendall(b"cdefghij")
        c.settimeout(10)
        self.assertIn(b" 200 ", c.recv(4096).split(b"\r\n")[0])
        c.close()
        p = os.path.join(GAMES, "install", "setup_two.exe")
        self.assertEqual(open(p, "rb").read(), b"abcdefghij")
        os.remove(p)

    def test_post_body_read(self):
        """a POST's body is read even when its request is refused: the next
        request on the connection is a request"""
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        c.request("POST", "/api/reboot-not", body=b'{"x": 1}', headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 404)
        c.request("GET", "/api/status")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()
        c.close()

    def test_upload_usb_disk(self):
        touch(os.path.join(STATE, "usb-disk"))
        s, h, d = req("PUT", "/api/upload/install/setup_x.exe", b"data")
        self.assertEqual(s, 503)
        self.assertIn("USB-диск", json.loads(d)["error"])
        # refused before the body with Expect: 100-continue
        c = socket.create_connection(("127.0.0.1", PORT))
        c.sendall(b"PUT /api/upload/install/setup_x.exe HTTP/1.1\r\nHost: x\r\nContent-Length: 999999999\r\n"
                  b"Expect: 100-continue\r\n\r\n")
        c.settimeout(10)
        first = c.recv(4096).split(b"\r\n")[0]
        c.close()
        self.assertIn(b" 503 ", first)
        self.assertFalse(os.path.exists(os.path.join(GAMES, "install", "setup_x.exe")))
        self.assertFalse(os.path.exists(os.path.join(GAMES, "install", "setup_x.exe.part")))
        s, r = jreq("GET", "/api/install/scan")
        self.assertIn("USB-диск", r["problem"])

    def test_upload_room(self):
        c = socket.create_connection(("127.0.0.1", PORT))
        c.sendall(b"PUT /api/upload/install/huge.exe HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n"
                  b"Expect: 100-continue\r\n\r\n" % (1 << 60))
        c.settimeout(10)
        first = c.recv(4096).split(b"\r\n")[0]
        c.close()
        self.assertIn(b" 507 ", first)

    def tiny_game(self, name="Tiny Game"):
        d = os.path.join(GAMES, "install", name)
        os.makedirs(d)
        touch(os.path.join(d, "tiny.exe"), b"MZ" + b"\0" * 200)
        touch(os.path.join(d, "setup.exe"), b"MZ" + b"\0" * 20)
        touch(os.path.join(d, "data.pak"), b"p" * 5000)
        return d

    def test_install_unknown(self):
        d = self.tiny_game()
        s, r = jreq("GET", "/api/install/scan")
        e = [x for x in r["entries"] if x["path"] == d]
        self.assertEqual(len(e), 1, r)
        self.assertEqual(e[0]["state"], "unknown")
        self.assertEqual(e[0]["exe"][0], "tiny.exe")
        s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Tiny Game"})
        self.assertEqual(s, 200, r)
        ev = events(r["job"])
        self.assertEqual(ev[-1]["type"], "done", ev)
        self.assertEqual(ev[-1]["folder"], "tiny-game")
        self.assertIn("Tiny Game", ev[-1]["text"])
        self.assertTrue(any(x["type"] == "step" and x["name"] == "find" and x["text"] == "поиск игры" for x in ev))
        game = os.path.join(GAMES, "tiny-game")
        self.assertIn("exe = tiny.exe", open(os.path.join(game, "wine.ini")).read())
        self.assertEqual(open(os.path.join(game, "data.pak"), "rb").read(), b"p" * 5000)
        self.assertFalse(os.path.exists(d))	# moved: the same "card"
        # the job is the last one
        j = jreq("GET", "/api/job")[1]["job"]
        self.assertTrue(j["ended"])
        # it is a game now
        g = [x for x in jreq("GET", "/api/games")[1]["games"] if x["id"] == "tiny-game"]
        self.assertEqual(g[0]["name"], "Tiny Game")
        # once more: a game without a recipe gets a folder of its own
        d = self.tiny_game()
        s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Tiny Game"})
        ev = events(r["job"])
        self.assertEqual((ev[-1]["type"], ev[-1]["folder"]), ("done", "tiny-game-2"))
        shutil.rmtree(game)
        shutil.rmtree(game + "-2")

    def test_fail_words(self):
        """game-install's fail codes in the words of the device's screen"""
        job = bw.Job("install", "x")
        bw.install_line(job, "fail exists /games/coldfear".split(" ", 2))
        self.assertEqual(job.events[-1]["text"], "Не удалось установить игру: на карте уже есть папка "
                         "/games/coldfear (другая игра или старая копия этой).")
        for line, words in (("fail room 1700", "игре нужно 1700 МБ"), ("fail card ", "не удаётся записать"),
                            ("fail busy ", "уже идёт установка"), ("fail strange it broke", "it broke")):
            job = bw.Job("install", "x")
            bw.install_line(job, line.split(" ", 2))
            self.assertIn(words, job.events[-1]["text"], line)

    def test_install_gone_and_outside(self):
        s, r = jreq("POST", "/api/install/run", {"path": os.path.join(GAMES, "install", "nothing")})
        self.assertEqual(s, 404)
        s, r = jreq("POST", "/api/install/run", {"path": os.path.join(GAMES, "coldfear")})
        self.assertEqual(s, 404)
        s, r = jreq("POST", "/api/install/remove", {"path": os.path.join(GAMES, "install", "..", "coldfear")})
        self.assertEqual(s, 404)
        self.assertTrue(r["error"].startswith("Не удалось удалить: "), r)
        self.assertTrue(os.path.isdir(os.path.join(GAMES, "coldfear")))
        d = self.tiny_game("Bad Exe")
        s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "../../x.exe"})
        self.assertEqual(s, 400)
        shutil.rmtree(d)

    def test_busy(self):
        """game-install's lock held (the device's install screen): busy"""
        d = self.tiny_game("Locked")
        with open(ENV["GAME_INSTALL_LOCK"], "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            s, r = jreq("POST", "/api/install/remove", {"path": d})
            self.assertEqual(s, 409, r)
            self.assertEqual(r["code"], "busy")
            self.assertEqual(r["error"], bw.REMOVE_FAILED % bw.INSTALL_FAIL["busy"])
            self.assertTrue(os.path.isdir(d))
            s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Locked"})
            ev = events(r["job"])
            self.assertEqual((ev[-1]["type"], ev[-1]["code"]), ("fail", "busy"))
            self.assertEqual(ev[-1]["text"], bw.INSTALL_FAILED % bw.INSTALL_FAIL["busy"])
            self.assertFalse(os.path.exists(os.path.join(GAMES, "locked")))
        # free again: removed
        s, r = jreq("POST", "/api/install/remove", {"path": d})
        self.assertEqual(s, 200, r)
        self.assertFalse(os.path.exists(d))

    def test_one_job(self):
        upd = os.path.join(GAMES, "updates", "ogu-hold.upd")
        make_upd(upd)
        touch(os.path.join(STATE, "hold-update"))
        try:
            s, r = jreq("POST", "/api/update/run", {"file": upd})
            self.assertEqual(s, 200)
            job = r["job"]
            d = self.tiny_game("Second")
            s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Second"})
            self.assertEqual((s, r["code"]), (409, "busy"))
            s, r = jreq("POST", "/api/update/run", {"file": upd})
            self.assertEqual(s, 409)
            self.assertEqual(jreq("POST", "/api/reboot")[0], 409)
            # the other slot is not mounted by ab-state while it runs
            st = jreq("GET", "/api/update/state")[1]
            self.assertIsNone(st["versions"]["b"])
            self.assertTrue(st["busy"])
        finally:
            os.remove(os.path.join(STATE, "hold-update"))
        self.assertEqual(events(job)[-1]["type"], "done")
        shutil.rmtree(d)
        os.remove(upd)

    def test_games_and_logs(self):
        deadline = time.time() + 10
        while True:
            g = {x["id"]: x for x in jreq("GET", "/api/games")[1]["games"]}
            if g["coldfear"]["size"] is not None or time.time() > deadline:
                break
            time.sleep(0.1)
        self.assertEqual(g["coldfear"]["name"], "Cold Fear")
        self.assertEqual(g["coldfear"]["size"], 300000 + len("; a test\nname = Cold Fear\nexe = ColdFear_retail.exe\n"))
        self.assertEqual([x["n"] for x in g["coldfear"]["logs"]], [1, 2])
        self.assertIsNotNone(g["coldfear"]["last"])
        self.assertEqual(g["homm3"]["kind"], "built-in")
        self.assertNotIn("halflife", g)
        s, h, d = req("GET", "/api/logs/coldfear/1")
        self.assertEqual(s, 200)
        self.assertEqual(d, b"bare_app: a launch of a game\nlaunch 1\n")
        s, h, d = req("GET", "/api/logs/coldfear/2?download=1")
        self.assertIn("attachment", dict(h)["Content-Disposition"])
        for bad in ("/api/logs/coldfear/4", "/api/logs/coldfear/3", "/api/logs/..%2Fcoldfear/1",
                    "/api/logs/.hidden/1", "/api/logs/coldfear/0"):
            self.assertEqual(req("GET", bad)[0], 404, bad)

    def test_reports(self):
        s, h, d = req("GET", "/api/report?game=coldfear")
        self.assertEqual(s, 200, d)
        self.assertEqual(d, b"a report of coldfear\n")
        name = "2026-11-25_12-00-00-coldfear.txt"
        self.assertIn(name, dict(h)["Content-Disposition"])
        r = jreq("GET", "/api/reports")[1]["reports"]
        self.assertEqual([(x["where"], x["name"]) for x in r], [("card", name)])
        self.assertEqual(req("GET", "/api/reports/card/" + name)[2], b"a report of coldfear\n")
        self.assertEqual(req("GET", "/api/report?game=..%2Fx")[0], 400)
        self.assertEqual(req("DELETE", "/api/reports/card/..%2Fcoldfear%2Fwine.ini")[0], 404)
        self.assertEqual(req("DELETE", "/api/reports/card/" + name)[0], 200)
        self.assertEqual(jreq("GET", "/api/reports")[1]["reports"], [])
        os.environ["FAIL_REPORT"] = "1"
        s, r = jreq("GET", "/api/report")
        self.assertEqual(s, 500)
        self.assertIn("cannot", r["error"])
        # one in /data
        os.makedirs(os.path.join(DATA, "reports"), exist_ok=True)
        touch(os.path.join(DATA, "reports", "x.txt"), b"in data")
        self.assertEqual(jreq("GET", "/api/reports")[1]["reports"][0]["where"], "data")
        self.assertEqual(req("DELETE", "/api/reports/data/x.txt")[0], 200)

    def test_update(self):
        upd = os.path.join(GAMES, "updates", "ogu-2026-11-25-test.upd")
        other = os.path.join(GAMES, "updates", "oga-2026-11-25.upd")
        make_upd(upd)
        make_upd(other, firmware="oga")
        touch(os.path.join(GAMES, "updates", "junk.upd"), b"not a tar")
        f = {x["name"]: x for x in jreq("GET", "/api/update/files")[1]["files"]}
        self.assertTrue(f["ogu-2026-11-25-test.upd"]["fits"])
        self.assertEqual(f["ogu-2026-11-25-test.upd"]["version"], "2026-11-25-test")
        self.assertFalse(f["oga-2026-11-25.upd"]["fits"])
        self.assertFalse(f["junk.upd"]["fits"])
        s, r = jreq("GET", "/api/update/info?file=" + upd)
        self.assertEqual(s, 200)
        self.assertEqual(r["info"]["VERSION"], "2026-11-25-test")
        s, r = jreq("GET", "/api/update/info?file=" + os.path.join(GAMES, "updates", "junk.upd"))
        self.assertEqual(s, 400)
        self.assertEqual(jreq("GET", "/api/update/info?file=" + os.path.join(TOP, "x.upd"))[0], 404)
        s, r = jreq("POST", "/api/update/run", {"file": upd})
        self.assertEqual(s, 200)
        ev = events(r["job"])
        self.assertEqual([e["n"] for e in ev if e["type"] == "step"], [1, 2, 2, 2, 6])
        self.assertEqual(ev[-1]["type"], "done")
        self.assertEqual(ev[-1]["version"], "2026-11-25 test123-dirty")
        self.assertIn("2026-11-25 test123-dirty установлено", ev[-1]["text"])
        self.assertIn("run " + upd, calls())
        # a failure: system-update's own words
        touch(os.path.join(STATE, "fail-update"))
        ev = events(jreq("POST", "/api/update/run", {"file": upd})[1]["job"])
        self.assertEqual(ev[-1]["type"], "fail")
        self.assertIn("SYSTEM is damaged", ev[-1]["text"])
        # the state; the switch to the spare one needs one
        st = jreq("GET", "/api/update/state")[1]
        self.assertEqual(st["versions"]["a"], "2026-11-25 aaaaaaa")
        self.assertEqual(st["versions"]["b"], None)
        self.assertEqual(jreq("POST", "/api/update/switch")[0], 400)
        self.assertNotIn("reboot", calls())
        touch(os.path.join(STATE, "has-b"))
        self.assertEqual(jreq("GET", "/api/update/state")[1]["versions"]["b"], "2026-11-24 bbbbbbb")
        self.assertEqual(jreq("POST", "/api/update/switch")[0], 200)
        deadline = time.time() + 5
        while "reboot" not in calls() and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual([c for c in calls() if c], ["run " + upd, "run " + upd, "try b", "reboot"])
        # files deleted: an update, not an entry of install
        self.assertEqual(req("DELETE", "/api/files/updates/junk.upd")[0], 200)
        for p in (upd, other):
            os.remove(p)

    def test_reboot(self):
        self.assertEqual(jreq("POST", "/api/reboot")[0], 200)
        deadline = time.time() + 5
        while "reboot" not in calls() and time.time() < deadline:
            time.sleep(0.1)
        self.assertIn("reboot", calls())

    def test_card_writing(self):
        """remounted writable once for all of this server's writers, read-only
        after the last; left alone when it was writable"""
        did = []
        opts = [["ro", "noatime"]]
        real = bw.card_opts, bw.run
        bw.card_opts = lambda: opts[0]

        def fake_run(argv, timeout=60):
            did.append(argv[2])
            opts[0] = [argv[2].split(",")[1]]
            return 0, "", ""
        bw.run = fake_run
        try:
            with bw.CardWriting():
                with bw.CardWriting():
                    pass
                self.assertEqual(did, ["remount,rw"])
            self.assertEqual(did, ["remount,rw", "remount,ro"])
            did.clear()
            opts[0] = ["rw"]
            with bw.CardWriting():
                pass
            self.assertEqual(did, [])
            self.assertEqual(opts[0], ["rw"])
        finally:
            bw.card_opts, bw.run = real

    def test_allowed(self):
        class H:
            allowed = bw.Handler.allowed
        for ip, ok in (("192.168.7.1", True), ("127.0.0.1", True), ("::ffff:192.168.7.1", True),
                       ("192.168.70.1", False), ("10.0.0.2", False), ("192.168.8.1", False)):
            h = H()
            h.client_address = (ip, 1)
            self.assertEqual(h.allowed(), ok, ip)

    def test_safe_name(self):
        for n in ("setup_cold_fear_1.0_gog_v3_(86830)-1.bin", "Шрифт.ttf", "a b.exe"):
            self.assertTrue(bw.safe_name(n), n)
        for n in ("", ".", "..", ".x", "a/b", "a\\b", "a..b", "x\ny", "x" * 300):
            self.assertFalse(bw.safe_name(n), n)


def tearDownModule():
    SERVER.shutdown()
    # nothing is mounted in it: a directory tree of this test's own
    with open("/proc/mounts") as f:
        assert not any(TOP in line for line in f), "a mount in " + TOP
    shutil.rmtree(TOP)


def tree_md5(top):
    out = {}
    for d, dirs, files in os.walk(top):
        for f in files:
            with open(os.path.join(d, f), "rb") as fh:
                out[os.path.relpath(os.path.join(d, f), top)] = hashlib.md5(fh.read()).hexdigest()
    return out


class SavesTest(unittest.TestCase):
    """the page "Сохранения": bare-backup (the real one) behind /api/saves"""

    def setUp(self):
        for f in ("usb-disk",):
            p = os.path.join(STATE, f)
            if os.path.exists(p):
                os.remove(p)
        self.saves = os.path.join(DATA, "wine", "prefix", "drive_c", "users", "root", "Documents",
                                  "My Games", "pirates")
        if os.path.isdir(self.saves):
            shutil.rmtree(self.saves)
        os.makedirs(self.saves)
        with open(os.path.join(self.saves, "Начало.pirates_savegame"), "wb") as f:
            f.write(os.urandom(50000))
        with open(os.path.join(self.saves, "Config.ini"), "w") as f:
            f.write("a=1\n")
        with open(ENV["BARE_BACKUP_CONF"], "w") as f:
            f.write("lang=ru\ncontrols.0000abcd=a=b\n")
        self.state()
        for d in (os.path.join(GAMES, "backups"), os.path.join(DATA, "backups")):
            if os.path.isdir(d):
                shutil.rmtree(d)

    def state(self, running=None):
        os.makedirs(ENV["BARE_BACKUP_RUN"], exist_ok=True)
        with open(os.path.join(ENV["BARE_BACKUP_RUN"], "games.json"), "w") as f:
            json.dump({"version": 1, "pid": os.getpid(), "running": running, "games": [
                {"folder": "pirates", "name": "Pirates", "kind": "wine", "key": "0000abcd",
                 "dir": os.path.join(GAMES, "pirates"), "available": True,
                 "storage": [os.path.join(DATA, "wine", "games", "pirates"), self.saves]}]}, f)

    def test_saves(self):
        s, r = jreq("GET", "/api/saves")
        self.assertEqual(s, 200, r)
        g = r["games"][0]
        self.assertEqual((g["folder"], g["files"]), ("pirates", 2))
        self.assertEqual(r["copies"], [])
        before = tree_md5(self.saves)
        # a copy made and sent
        s, h, d = req("GET", "/api/saves/pirates/backup", timeout=60)
        self.assertEqual(s, 200, d)
        h = dict(h)
        self.assertEqual(h["Content-Type"], "application/zip")
        self.assertIn("saves-pirates-", h["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(d)) as z:
            self.assertIn("manifest.json", z.namelist())
            self.assertIn("controls.0000abcd=a=b", z.read("settings.ini").decode())
        s, r = jreq("GET", "/api/saves")
        self.assertEqual([c["where"] for c in r["copies"]], ["card"])
        name = r["copies"][0]["name"]
        s, h, d2 = req("GET", "/api/saves/copy/card/" + urllib.parse.quote(name))
        self.assertEqual((s, d2), (200, d))
        # its manifest, then back after a change
        s, m = jreq("POST", "/api/saves/info", {"where": "card", "name": name})
        self.assertEqual(m["games"][0]["folder"], "pirates")
        with open(os.path.join(self.saves, "Config.ini"), "w") as f:
            f.write("changed")
        s, r = jreq("POST", "/api/saves/restore", {"where": "card", "name": name})
        self.assertEqual(s, 200, r)
        self.assertEqual(r["restored"], ["pirates"])
        self.assertEqual(tree_md5(self.saves), before)
        # not while the game runs
        self.state(running={"folder": "pirates", "key": "0000abcd", "pid": os.getpid()})
        s, r = jreq("POST", "/api/saves/restore", {"where": "card", "name": name})
        self.assertEqual(s, 409)
        self.assertIn("запущена", r["error"])
        self.state()
        # uploaded from the computer into /data/backups, then restored from there
        up = "saves-pirates-2026-01-01_00-00-00.zip"
        s, h, b = req("PUT", "/api/saves/upload/" + up, d)
        self.assertEqual(s, 200, b)
        self.assertTrue(os.path.isfile(os.path.join(DATA, "backups", up)))
        self.assertEqual(req("PUT", "/api/saves/upload/evil.zip", b"x")[0], 400)
        self.assertEqual(req("PUT", "/api/saves/upload/..%2fsaves-x.zip", b"x")[0], 400)
        with open(os.path.join(self.saves, "Config.ini"), "w") as f:
            f.write("changed again")
        s, r = jreq("POST", "/api/saves/restore", {"where": "data", "name": up})
        self.assertEqual(s, 200, r)
        self.assertEqual(tree_md5(self.saves), before)
        # a damaged copy: refused, the data as it was
        bad = "saves-pirates-2026-01-02_00-00-00.zip"
        self.assertEqual(req("PUT", "/api/saves/upload/" + bad, d[:len(d) // 2])[0], 200)
        with open(os.path.join(self.saves, "Config.ini"), "w") as f:
            f.write("mine")
        mine = tree_md5(self.saves)
        s, r = jreq("POST", "/api/saves/restore", {"where": "data", "name": bad})
        self.assertEqual(s, 500)
        self.assertEqual(tree_md5(self.saves), mine)
        # a copy of all
        s, h, d = req("GET", "/api/saves/all", timeout=60)
        self.assertEqual(s, 200, d)
        with zipfile.ZipFile(io.BytesIO(d)) as z:
            self.assertIn("bare_app.conf", z.namelist())
        # copies deleted; nothing else is
        s, r = jreq("GET", "/api/saves")
        self.assertEqual(len(r["copies"]), 4)
        for c in r["copies"]:
            self.assertEqual(req("DELETE", "/api/saves/copy/%s/%s" % (c["where"], urllib.parse.quote(c["name"])))[0], 200)
        self.assertEqual(jreq("GET", "/api/saves")[1]["copies"], [])
        self.assertEqual(req("DELETE", "/api/saves/copy/data/..%2fbare_app.conf")[0], 404)
        self.assertEqual(req("GET", "/api/saves/copy/data/x.zip")[0], 404)

    def test_saves_without_bare_app(self):
        os.remove(os.path.join(ENV["BARE_BACKUP_RUN"], "games.json"))
        s, r = jreq("GET", "/api/saves")
        self.assertEqual(s, 200)
        self.assertIn("bare_app не запущен", r["error"])
        s, h, d = req("GET", "/api/saves/pirates/backup")
        self.assertEqual(s, 500)
        self.assertIn("bare_app не запущен", json.loads(d)["error"])


class FakeBareApp:
    """bare_app's FIFO (BARE_WEB_CTL): its lines kept; "reload FOLDER" writes
    the effective ini as bare_app would (the server's merge stands in for
    ini_layer.c here), "import-settings FILE" replaces those games' entries
    of bare_app.conf as ctl_settings.c does"""

    def __init__(self):
        self.lines = []
        self.fd = None
        self.games = {}	# folder: (base path, layer path, effective path)

    def start(self):
        if not os.path.exists(ENV["BARE_WEB_CTL"]):
            os.mkfifo(ENV["BARE_WEB_CTL"])
        self.fd = os.open(ENV["BARE_WEB_CTL"], os.O_RDWR)
        threading.Thread(target=self.loop, args=(self.fd,), daemon=True).start()

    def stop(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.write(fd, b"\x00stop\n")
            time.sleep(0.1)

    def loop(self, fd):
        buf = b""
        while True:
            b = os.read(fd, 4096)
            buf += b
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode()
                if line == "\x00stop":
                    os.close(fd)
                    return
                self.lines.append(line)
                self.react(line)

    def react(self, line):
        cmd, _, arg = line.partition(" ")
        if cmd == "reload" and arg in self.games:
            base, layer, eff = self.games[arg]
            if os.path.exists(layer):
                os.makedirs(os.path.dirname(eff), exist_ok=True)
                m = bw.ini_merge(bw.ini_parse(open(base).read()), bw.ini_parse(open(layer).read()))
                with open(eff, "w") as f:
                    f.write("; merged by bare_app from %s + %s\n" % (base, layer))
                    sec = None
                    for e in [e for e in m if not e[0]] + [e for e in m if e[0]]:
                        if e[0] != sec and e[0]:
                            f.write("\n[%s]\n" % e[0])
                        sec = e[0]
                        f.write("%s = %s\n" % (e[1], e[2]))
            elif os.path.exists(eff):
                os.remove(eff)
        elif cmd == "import-settings":
            text = open(arg).read()
            names = set()
            for l in text.splitlines():
                k, eq, v = l.partition("=")
                if not eq or l.startswith(";"):
                    continue
                names.add(v if k == "game" else k.split(".", 1)[1])
            conf = open(ENV["BARE_WEB_CONF"]).read().splitlines()
            keep = [l for l in conf if not any(l.startswith(("controls.%s=" % n, "options.%s=" % n)) for n in names)]
            new = [l for l in text.splitlines() if l.startswith(("controls.", "options.")) and l.split("=", 1)[1]]
            with open(ENV["BARE_WEB_CONF"], "w") as f:
                f.write("\n".join(keep + new) + "\n")


BARE_APP = FakeBareApp()
BARE_APP.start()
PIRATES_KEY = "0ecf99f4"


def file_lines(p):
    return [l for l in open(p).read().splitlines() if l and not l.startswith(";")]


class RecipeTest(unittest.TestCase):
    """the workshop: /api/recipe over a copy of the reference wine.ini"""

    def setUp(self):
        for d in (os.path.join(GAMES, "recipes"), os.path.join(ENV["BARE_WEB_RUN"], "ini")):
            if os.path.isdir(d):
                shutil.rmtree(d)
        self.pirates = os.path.join(GAMES, "pirates")
        os.makedirs(self.pirates, exist_ok=True)
        shutil.copy(os.path.join(SDK, "apps", "bare_app", "ports", "wine", "wine.ini"),
                    os.path.join(self.pirates, "wine.ini"))
        os.makedirs(os.path.join(GAMES, "fake"), exist_ok=True)
        with open(os.path.join(GAMES, "fake", "game.ini"), "w") as f:
            f.write("name = Fake game\nexe = fake\nneeds = data.pak\nfps_limit = 60\n[labels]\na = jump\n")
        with open(ENV["BARE_WEB_CONF"], "w") as f:
            f.write("lang=ru\ncontrols.%s=a=b,b=a,x=-,ly=invert\noptions.%s=fps=25\ncontrols.0badc0de=a=b\n"
                    % (PIRATES_KEY, PIRATES_KEY))
        self.state()
        run = ENV["BARE_WEB_RUN"]
        BARE_APP.games = {
            "pirates": (os.path.join(self.pirates, "wine.ini"), os.path.join(GAMES, "recipes", "pirates", "wine.ini"),
                        os.path.join(run, "ini", "pirates.ini")),
            "fake": (os.path.join(GAMES, "fake", "game.ini"), os.path.join(GAMES, "recipes", "fake", "game.ini"),
                     os.path.join(run, "ini", "fake.game.ini"))}
        del BARE_APP.lines[:]
        for f in ("state.json",):
            p = os.path.join(run, f)
            if os.path.exists(p):
                os.remove(p)

    def state(self, running=None, pid=None):
        os.makedirs(ENV["BARE_WEB_RUN"], exist_ok=True)
        with open(os.path.join(ENV["BARE_WEB_RUN"], "games.json"), "w") as f:
            json.dump({"version": 1, "pid": pid or os.getpid(), "running": running, "games": [
                {"folder": "pirates", "name": "Sid Meier's Pirates!", "kind": "wine", "key": PIRATES_KEY,
                 "dir": self.pirates, "available": True, "storage": [], "has_layer": False, "layer": "none"},
                {"folder": "fake", "name": "Fake game", "kind": "native", "key": "00000fa4",
                 "dir": os.path.join(GAMES, "fake"), "available": True, "storage": []},
                {"folder": "homm3", "name": "Heroes", "kind": "homm3", "key": "fef6251f",
                 "dir": os.path.join(GAMES, "heroes3"), "available": True, "storage": []}]}, f)

    def layer(self, folder="pirates", ini="wine.ini"):
        return os.path.join(GAMES, "recipes", folder, ini)

    def test_get_without_layer(self):
        s, r = jreq("GET", "/api/recipe/pirates")
        self.assertEqual(s, 200, r)
        self.assertTrue(r["editable"])
        self.assertEqual((r["kind"], r["layer"], r["effective_source"]), ("wine", None, "base"))
        self.assertEqual(r["effective"], r["base"])
        self.assertEqual(r["base"][""]["mode"], "800x600")
        self.assertEqual(r["base"][""]["saves"], ["Documents/My Games/pirates"])
        self.assertEqual(r["base"]["keys"]["b"], "esc")
        self.assertEqual(r["player_controls"]["value"], "a=b,b=a,x=-,ly=invert")
        self.assertEqual(r["player_options"]["value"], "fps=25")
        self.assertIn({"from": "x", "to": "-"}, r["player_controls"]["pairs"])
        self.assertEqual(r["defaults"][""]["fps_limit"], "none")	# the schema's
        if os.path.isfile(HOST_WINE):	# bare_app_wine --defaults
            self.assertEqual(r["defaults"]["keys"]["l1"], "pgup")
            self.assertEqual(r["defaults"][""]["modes"], ["640x480", "800x600", "1024x768"])
        # a game of bare_app's own: no recipe to edit; one that is not there
        s, r = jreq("GET", "/api/recipe/homm3")
        self.assertEqual((s, r["kind"], r["editable"]), (200, "built-in", False))
        self.assertNotIn("base", r)
        self.assertEqual(jreq("GET", "/api/recipe/nothere")[0], 404)
        self.assertEqual(jreq("GET", "/api/recipe/..")[0], 400)
        self.assertEqual(jreq("GET", "/api/recipe/.hidden")[0], 400)

    def test_put_only_what_differs(self):
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {
            "": {"mode": "1024x768", "fps_limit": "30", "name": "Sid Meier's Pirates!",
                 "modes": ["1280x960"], "Locale": "ru_RU"},
            "keys": {"select": "esc", "a": "lbutton", "R1": "kp5"},
            "Labels.RU": {"a": "клик", "f4": "карта мира"}}})
        self.assertEqual(s, 200, r)
        self.assertEqual(file_lines(self.layer()), ["mode = 1024x768", "[keys]", "select = esc", "[labels.ru]",
                                                    "f4 = карта мира"])
        self.assertIn("reload pirates", BARE_APP.lines)
        self.assertEqual(r["layer"], {"": {"mode": "1024x768"}, "keys": {"select": "esc"},
                                      "labels.ru": {"f4": "карта мира"}})
        self.assertEqual(r["effective_source"], "bare_app")
        self.assertEqual((r["effective"][""]["mode"], r["base"][""]["mode"]), ("1024x768", "800x600"))
        self.assertEqual(r["effective"]["keys"]["select"], "esc")
        self.assertEqual(r["effective"]["labels.ru"]["f4"], "карта мира")
        # a second PUT replaces the whole layer: only what it says
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"gamma": "1.3"}}})
        self.assertEqual(s, 200, r)
        self.assertEqual(file_lines(self.layer()), ["gamma = 1.3"])
        self.assertEqual(r["effective"][""]["mode"], "800x600")
        # without bare_app's file of it the server merges by the same rules
        os.remove(os.path.join(ENV["BARE_WEB_RUN"], "ini", "pirates.ini"))
        s, r = jreq("GET", "/api/recipe/pirates")
        self.assertEqual((r["effective_source"], r["effective"][""]["gamma"]), ("server", "1.3"))

    def test_empty_value_drops(self):
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {
            "": {"dlls": "", "args": "", "saves": [], "modes": ["1280x960", "1600x1200"], "esc_delay": ""},
            "labels": {"x": ""}}})
        self.assertEqual(s, 200, r)
        # dlls, saves and the label are the game's: dropped; args is empty in
        # it and esc_delay not there: nothing to drop
        self.assertEqual(file_lines(self.layer()), ["dlls =", "saves =", "modes = 1280x960",
                                                    "modes = 1600x1200", "[labels]", "x ="])
        eff = r["effective"]
        self.assertNotIn("dlls", eff[""])
        self.assertNotIn("saves", eff[""])	# "saves =": no list at all
        self.assertEqual(eff[""]["modes"], ["1280x960", "1600x1200"])
        self.assertNotIn("x", eff["labels"])
        self.assertEqual(eff["labels"]["a"], "click")
        # a layer the same as the game: no file at all
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"mode": "800x600"}}})
        self.assertEqual((s, r["lines"], r["layer"]), (200, 0, None))
        self.assertFalse(os.path.exists(os.path.join(GAMES, "recipes")))

    def test_put_checked(self):
        for sections, what in (({"": {"mode": "big"}}, "mode"), ({"": {"fps_limit": "500"}}, "fps_limit"),
                               ({"": {"scale": "zoom"}}, "scale"), ({"keys": {"a": "esc ;x"}}, "комментарий"),
                               ({"": {"reg": ["noslash=1"]}}, "reg"), ({"": {"mode": ["800x600"]}}, "список"),
                               ({"": {"bad key": "1"}}, "ключ"), ({"": {"exe": "a\nb"}}, "управляющие")) + \
                ((({"keys": {"a": "nokey"}}, "клавиша"), ({"keys": {"dpad": "numpad"}}, "dpad"),
                  ({"keys": {"a": "a+b+c+d+e"}}, "клавиша")) if os.path.isfile(HOST_WINE) else ()):
            s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": sections})
            self.assertEqual(s, 400, (sections, r))
            self.assertIn(what, r["error"])
        self.assertFalse(os.path.exists(self.layer()))
        # allowed: an unknown key (a warning), fps_limit none, kp+, ctrl+s, the ini as text
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {
            "": {"newthing": "1", "fps_limit": "none"}, "keys": {"l1": "kp+", "l2": "ctrl+s", "stick_up": "w"}}})
        self.assertEqual(s, 200, r)
        self.assertTrue(any("newthing" in w for w in r["warnings"]), r["warnings"])
        s, h, d = req("PUT", "/api/recipe/pirates/layer", "mode = 640x480\n[keys]\ny = esc\n".encode(),
                      {"Content-Type": "text/plain"})
        self.assertEqual(s, 200, d)
        self.assertEqual(file_lines(self.layer()), ["mode = 640x480", "[keys]", "y = esc"])
        s, h, d = req("PUT", "/api/recipe/pirates/layer", b"mode 640x480\n", {"Content-Type": "text/plain"})
        self.assertEqual(s, 400)
        # games without a recipe, names
        self.assertEqual(jreq("PUT", "/api/recipe/homm3/layer", {"sections": {"": {"a": "1"}}})[0], 400)
        self.assertEqual(jreq("PUT", "/api/recipe/nothere/layer", {"sections": {}})[0], 404)
        self.assertEqual(jreq("PUT", "/api/recipe/a%2Fb/layer", {"sections": {}})[0], 400)
        self.assertEqual(jreq("PUT", "/api/recipe/pirates/other", {"sections": {}})[0], 404)

    def test_delete(self):
        jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"mode": "1024x768"}}})
        self.assertTrue(os.path.exists(os.path.join(ENV["BARE_WEB_RUN"], "ini", "pirates.ini")))
        del BARE_APP.lines[:]
        # a file of someone else's in the game's folder of the recipes stays
        touch(os.path.join(GAMES, "recipes", "pirates", "notes.txt"), b"mine")
        s, r = jreq("DELETE", "/api/recipe/pirates/layer")
        self.assertEqual(s, 200, r)
        self.assertEqual((r["layer"], r["effective_source"], r["effective"][""]["mode"]), (None, "base", "800x600"))
        self.assertEqual(BARE_APP.lines, ["reload pirates"])
        self.assertFalse(os.path.exists(self.layer()))
        self.assertEqual(os.listdir(os.path.join(GAMES, "recipes", "pirates")), ["notes.txt"])
        self.assertFalse(os.path.exists(os.path.join(ENV["BARE_WEB_RUN"], "ini", "pirates.ini")))
        os.remove(os.path.join(GAMES, "recipes", "pirates", "notes.txt"))
        s, r = jreq("DELETE", "/api/recipe/pirates/layer")
        self.assertEqual(s, 200)
        self.assertFalse(os.path.exists(os.path.join(GAMES, "recipes")))

    def test_without_fifo(self):
        BARE_APP.stop()
        try:
            s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"mode": "1024x768"}}})
            self.assertEqual((s, r["reloaded"], r["effective_source"]), (200, False, "server"))
            self.assertEqual(r["effective"][""]["mode"], "1024x768")
            s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
            self.assertEqual(s, 503, r)
            self.assertEqual(jreq("POST", "/api/game/pirates/launch")[0], 503)
        finally:
            BARE_APP.start()

    def test_adopt_controls(self):
        conf_before = open(ENV["BARE_WEB_CONF"]).read()
        jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"mode": "1024x768"}, "keys": {"y": "esc"}}})
        del BARE_APP.lines[:]
        s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
        self.assertEqual(s, 200, r)
        # A is B for the player: A does what B did (esc, "back (Esc)"), B what A
        # did, X nothing; the axis stays the player's
        self.assertEqual(file_lines(self.layer()), [
            "mode = 1024x768", "[keys]", "y = esc", "a = esc", "b = lbutton", "x = none",
            "[labels]", "a = back (Esc)", "b = click", "x =",
            "[labels.ru]", "a = назад (Esc)", "b = клик", "x ="])
        self.assertEqual(BARE_APP.lines[0], "reload pirates")
        self.assertTrue(BARE_APP.lines[1].startswith("import-settings "), BARE_APP.lines)
        self.assertFalse(os.path.exists(BARE_APP.lines[1].split(" ", 1)[1]))	# removed after
        self.assertTrue(r["settings_done"])
        self.assertEqual(r["kept"], [{"from": "ly", "to": "invert"}])
        conf = open(ENV["BARE_WEB_CONF"]).read()
        self.assertIn("controls.%s=ly=invert\n" % PIRATES_KEY, conf)
        self.assertIn("options.%s=fps=25\n" % PIRATES_KEY, conf)	# the options stay
        self.assertIn("controls.0badc0de=a=b\n", conf)	# another game's too
        self.assertIn("lang=ru\n", conf)
        self.assertEqual(r["player_controls"]["value"], "ly=invert")
        self.assertEqual(r["effective"]["keys"]["a"], "esc")
        # nothing left to move: refused, nothing changed
        layer = open(self.layer()).read()
        s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
        self.assertEqual(s, 409, r)
        self.assertEqual(open(self.layer()).read(), layer)
        self.assertNotEqual(conf, conf_before)

    def test_adopt_refused(self):
        self.state(running={"folder": "pirates", "key": PIRATES_KEY, "pid": os.getpid()})
        s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
        self.assertEqual(s, 409, r)
        self.state()
        # the D-pad as the mouse: its directions are no [keys] buttons then
        with open(ENV["BARE_WEB_CONF"], "w") as f:
            f.write("controls.%s=up=a\n" % PIRATES_KEY)
        jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"keys": {"dpad": "mouse"}}})
        s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
        self.assertEqual(s, 409, r)
        self.assertEqual(file_lines(self.layer()), ["[keys]", "dpad = mouse"])
        self.assertEqual(jreq("POST", "/api/recipe/fake/adopt-controls")[0], 400)

    def test_native(self):
        s, r = jreq("GET", "/api/recipe/fake")
        self.assertEqual((s, r["kind"], r["ini"]), (200, "native", "game.ini"))
        self.assertEqual(r["base"][""]["needs"], ["data.pak"])
        s, r = jreq("PUT", "/api/recipe/fake/layer", {"sections": {"": {"fps_limit": "30", "filter": "nearest"},
                                                                  "labels": {"a": "jump"}}})
        self.assertEqual(s, 200, r)
        self.assertEqual(file_lines(self.layer("fake", "game.ini")), ["fps_limit = 30", "filter = nearest"])
        self.assertEqual(r["effective"][""]["filter"], "nearest")
        self.assertEqual(jreq("PUT", "/api/recipe/fake/layer", {"sections": {"": {"filter": "x"}}})[0], 400)

    def test_schema(self):
        s, r = jreq("GET", "/api/schema")
        self.assertEqual(s, 200)
        keys = {(e["section"], e["key"]): e for e in r["wine"]}
        for k in (("", "mode"), ("", "env"), ("", "reg"), ("keys", "stick"), ("keys", "f6"), ("labels.ru", "a")):
            self.assertIn(k, keys)
        self.assertTrue(keys[("", "reg")]["repeat"])
        self.assertFalse(r["start_select"])	# FIRMWARE=ogu has none
        self.assertTrue(r["env_presets"])
        if os.path.isfile(HOST_WINE):
            names = {(a["group"], a["name"]) for a in r["actions"]}
            self.assertLessEqual({("key", "esc"), ("mouse", "lbutton"), ("pad", "pad_a"), ("stick", "numpad")}, names)


SHOT_HELPER = r"""
import os, signal, sys, time
path, mode = sys.argv[1], sys.argv[2]
def shot(*_):
    if mode == "deaf":
        return
    time.sleep(0.05)
    w, h = 64, 32
    px = bytes((x * 4, y * 8, 128) [c] for y in range(h) for x in range(w) for c in range(3))
    with open(path + ".tmp", "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (w, h) + px)
    os.rename(path + ".tmp", path)
    with open(path + ".count", "a") as f:
        f.write("1")
signal.signal(signal.SIGUSR1, shot)
print("ready", flush=True)
while True:
    time.sleep(1)
"""


class CheckTest(unittest.TestCase):
    """the check of a game: state, launch/quit, screenshot, pad, live log"""

    setUp = RecipeTest.setUp
    state = RecipeTest.state

    def write_state(self, running, age=0):
        p = os.path.join(ENV["BARE_WEB_RUN"], "state.json")
        with open(p, "w") as f:
            json.dump({"running": running, "pid": 123 if running else 0, "fps": 30.5 if running else None,
                       "cpu_pct": 80, "time": int(time.time())}, f)
        t = time.time() - age
        os.utime(p, (t, t))

    def test_state(self):
        self.assertEqual(jreq("GET", "/api/state")[1]["running"], None)
        self.write_state("pirates")
        s, r = jreq("GET", "/api/state")
        self.assertEqual((s, r["running"], r["fps"], r["stale"]), (200, "pirates", 30.5, False))
        self.write_state("pirates", age=5)	# not renewed: no game
        self.assertEqual(jreq("GET", "/api/state")[1]["running"], None)

    def test_launch_quit_options(self):
        self.write_state("coldfear")
        s, r = jreq("POST", "/api/game/pirates/launch")
        self.assertEqual(s, 409, r)
        self.assertIn("coldfear", r["error"])
        self.assertEqual(jreq("POST", "/api/game/pirates/options")[0], 409)
        self.assertEqual(BARE_APP.lines, [])
        self.write_state("pirates")
        s, r = jreq("POST", "/api/game/pirates/launch")
        self.assertEqual((s, r.get("already")), (200, True))
        os.remove(os.path.join(ENV["BARE_WEB_RUN"], "state.json"))
        self.assertEqual(jreq("POST", "/api/game/pirates/launch")[0], 200)
        self.assertEqual(jreq("POST", "/api/game/pirates/options")[0], 200)
        self.assertEqual(jreq("POST", "/api/game/pirates/quit")[0], 200)
        time.sleep(0.1)
        self.assertEqual(BARE_APP.lines, ["launch pirates", "options pirates", "quit-game"])
        # games.json says one runs (state.json not there yet)
        self.state(running={"folder": "coldfear", "key": "1", "pid": os.getpid()})
        self.assertEqual(jreq("POST", "/api/game/pirates/launch")[0], 409)
        self.assertEqual(jreq("POST", "/api/game/nothere/launch")[0], 404)
        self.assertEqual(jreq("POST", "/api/game/pirates/kill")[0], 404)

    def test_shot(self):
        path = ENV["BARE_WEB_SHOT"]
        for mode in ("draw", "deaf"):
            p = subprocess.Popen([sys.executable, "-c", SHOT_HELPER, path, mode], stdout=subprocess.PIPE)
            try:
                self.assertEqual(p.stdout.readline().strip(), b"ready")
                self.state(pid=p.pid)	# SIGUSR1 goes to the helper, never to this test
                if mode == "deaf":
                    old, bw.SHOT_WAIT = bw.SHOT_WAIT, 0.5
                    try:
                        s, h, d = req("GET", "/api/shot.png")
                    finally:
                        bw.SHOT_WAIT = old
                    self.assertEqual(s, 504, d)
                    continue
                s, h, d = req("GET", "/api/shot.png")
                self.assertEqual((s, dict(h)["Content-Type"]), (200, "image/png"), d)
                from PIL import Image
                im = Image.open(io.BytesIO(d))
                self.assertEqual(im.size, (64, 32))
                self.assertFalse(os.path.exists(path))	# not left in /run
                s, h, d = req("GET", "/api/shot.png?w=32")
                self.assertEqual(Image.open(io.BytesIO(d)).size, (32, 16))
                # at the same time: one after another, each its own picture
                res = []
                ts = [threading.Thread(target=lambda: res.append(req("GET", "/api/shot.png")[0])) for _ in range(3)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join()
                self.assertEqual(res, [200, 200, 200])
                self.assertEqual(open(path + ".count").read(), "11111")
            finally:
                p.kill()
                p.wait()
                p.stdout.close()
                self.state()
                for f in (path + ".count",):
                    if os.path.exists(f):
                        os.remove(f)

    def test_pad(self):
        self.assertEqual(jreq("POST", "/api/pad", {"button": "f1", "down": True})[0], 200)
        self.assertEqual(jreq("POST", "/api/pad", {"button": "f1", "down": False})[0], 200)
        self.assertEqual(jreq("POST", "/api/pad", {"button": "power", "down": True})[0], 400)
        self.assertEqual(jreq("POST", "/api/pad", {"button": "a; reboot", "down": True})[0], 400)
        old, bw.PRESS_MAX = bw.PRESS_MAX, 0.2
        try:
            jreq("POST", "/api/pad", {"button": "a", "down": True})
            time.sleep(0.5)	# the page never let go: released on its own
        finally:
            bw.PRESS_MAX = old
        self.assertEqual(BARE_APP.lines, ["press f1", "release f1", "press a", "release a"])
        # the sticks: no device in this test
        s, r = jreq("POST", "/api/stick", {"stick": "stick", "x": 1, "y": 0})
        self.assertEqual(s, 503, r)
        self.assertEqual(jreq("POST", "/api/stick", {"stick": "stick", "x": 5, "y": 0})[0], 400)

    def test_log_live(self):
        d = os.path.join(LOGS, "livegame")
        os.makedirs(d, exist_ok=True)
        log1 = os.path.join(d, "1.log")
        with open(log1, "w") as f:
            f.write("first\nsecond\n")
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
        c.request("GET", "/api/logs/livegame/live")
        r = c.getresponse()
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream; charset=utf-8")

        def next_events(n):
            out = []
            while len(out) < n:
                line = r.readline().decode().rstrip("\n")
                if line.startswith("data: "):
                    out.append(json.loads(line[6:]))
            return out
        self.assertEqual(next_events(2), [{"line": "first"}, {"line": "second"}])
        with open(log1, "a") as f:
            f.write("third\nhalf")
        self.assertEqual(next_events(1), [{"line": "third"}])
        with open(log1, "a") as f:
            f.write(" of it\n")
        self.assertEqual(next_events(1), [{"line": "half of it"}])
        # the next start: a new 1.log
        os.rename(log1, os.path.join(d, "2.log"))
        with open(log1, "w") as f:
            f.write("new start\n")
        self.assertEqual(next_events(2), [{"reset": True}, {"line": "new start"}])
        c.close()
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
