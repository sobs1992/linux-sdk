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
import io
import json
import os
import shutil
import socket
import sys
import tarfile
import tempfile
import threading
import time
import unittest

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY = os.path.join(SDK, "board", "common", "buildroot", "rootfs-overlay")
BARE_WEB = os.path.join(OVERLAY, "usr", "lib", "bare-web", "bare_web.py")
STATIC = os.path.join(OVERLAY, "usr", "share", "bare-web")
GAME_INSTALL = os.path.join(SDK, "scripts", "game-install")

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
echo "done 2026-11-25-test"
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
}


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
        self.assertEqual(ev[-1]["version"], "2026-11-25-test")
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


if __name__ == "__main__":
    unittest.main()
