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
    # card-rw begin|end PID: each call written down (who, by its pid); a begin
    # fails with $STATE/no-card-rw
    "card-rw": r"""#!/bin/sh
[ "$1" = begin ] && [ -e "$STATE/no-card-rw" ] && { echo "card-rw: cannot" >&2; exit 1; }
echo "$1 $2 $(cat /proc/$2/comm 2>/dev/null)" >> "$STATE/card-rw.log"
""",
    # ip -o -4 addr show: the device's addresses (usb0, wlan0, lo)
    "ip": r"""#!/bin/sh
echo "1: lo    inet 127.0.0.1/8 scope host lo"
echo "3: usb0    inet 192.168.7.2/24 brd 192.168.7.255 scope global usb0"
echo "4: wlan0    inet 10.1.2.3/24 brd 10.1.2.255 scope global wlan0"
""",
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
    "BARE_WEB_CARD_RW": os.path.join(BIN, "card-rw"), "BARE_WEB_IP": os.path.join(BIN, "ip"),
    "BARE_WEB_ERRORS": os.path.join(SDK, "apps", "bare_app", "data", "errors.ini"),
    "GAME_INSTALL_GAMES": GAMES, "GAME_INSTALL_DATA": DATA, "GAME_INSTALL_RECIPES": os.path.join(TOP, "recipes"),
    "GAME_INSTALL_REDIST": os.path.join(TOP, "system-redist"), "GAME_INSTALL_LOCK": os.path.join(STATE, "gi.lock"),
    "GAME_INSTALL_CARD_RW": os.path.join(BIN, "card-rw"), "GAME_INSTALL_GUIDE": os.path.join(TOP, "guide.html"),
    "STATE": STATE,
    # bare-backup (the real one) in the same places
    "BARE_WEB_BARE_BACKUP": BARE_BACKUP, "BARE_BACKUP_DATA": DATA, "BARE_BACKUP_GAMES": GAMES,
    "BARE_BACKUP_RUN": os.path.join(TOP, "run"), "BARE_BACKUP_CONF": os.path.join(TOP, "bare_app.conf"),
    "BARE_BACKUP_CTL": os.path.join(TOP, "no-ctl"), "BARE_BACKUP_RELEASE": os.path.join(TOP, "sdk-release"),
    "BARE_BACKUP_UNIT": os.path.join(BIN, "unit"), "BARE_BACKUP_USB_DISK": os.path.join(BIN, "usb-disk"),
    "BARE_BACKUP_CARD_RW": os.path.join(BIN, "card-rw"),
    # bare_app's places for the workshop and the check of a game (stages 4, 5)
    "BARE_WEB_RUN": os.path.join(TOP, "run"), "BARE_WEB_CONF": os.path.join(TOP, "bare_app.conf"),
    "BARE_WEB_CTL": os.path.join(TOP, "ctl"), "BARE_WEB_WINE": os.path.join(BIN, "bare_app_wine"),
    "BARE_WEB_SHOT": os.path.join(TOP, "run", "shot.ppm"), "BARE_WEB_NATIVE_DIRS": GAMES,
    "BARE_WEB_SYS_INPUT": os.path.join(TOP, "sys-input"), "BARE_WEB_DEV_INPUT": os.path.join(TOP, "dev-input"),
    # the locks a game's delete takes (game-install's, the real one's here) and
    # looks at (bare-backup's: RUN/bare-backup.lock in its tests), the mounts
    "BARE_WEB_INSTALL_LOCK": os.path.join(STATE, "gi.lock"),
    "BARE_WEB_BACKUP_LOCK": os.path.join(TOP, "run", "bare-backup.lock"),
    "BARE_WEB_MOUNTS": os.path.join(TOP, "mounts"),
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
    os.makedirs(os.path.join(TOP, "run"), exist_ok=True)
    with open(ENV["BARE_WEB_MOUNTS"], "w") as f:
        f.write("/dev/root / ext4 ro 0 0\nproc /proc proc rw 0 0\n")


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


def req(method, path, body=None, headers=None, timeout=30, page=True):
    """a request as the page sends it (page: with X-Requested-With)"""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = dict(headers or {})
    if page:
        h.setdefault("X-Requested-With", "bare-web")
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


# a raw request's Host and its X-Requested-With, as the page's
HOSTB = b"Host: 127.0.0.1:%d\r\nX-Requested-With: bare-web\r\n" % PORT


def card_rw_calls():
    """[(begin|end, pid, comm)] of card-rw"""
    try:
        with open(os.path.join(STATE, "card-rw.log")) as f:
            return [tuple((line.split() + ["", ""])[:3]) for line in f]
    except OSError:
        return []


def card_rw_balanced(test, since=0):
    """every begin of card-rw since then had its end, by the same process"""
    depth = {}
    for cmd, pid, _ in card_rw_calls()[since:]:
        depth[pid] = depth.get(pid, 0) + (1 if cmd == "begin" else -1)
        test.assertGreaterEqual(depth[pid], 0, card_rw_calls())
    test.assertEqual(set(depth.values()) - {0}, set(), card_rw_calls())


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
        s.sendall(b"PUT /api/upload/install/setup_cut.exe HTTP/1.1\r\n" + HOSTB + b""
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
        c.sendall(b"PUT /api/upload/install/setup_two.exe HTTP/1.1\r\n" + HOSTB + b"Content-Length: 10\r\n\r\nab")
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
        c.sendall(b"PUT /api/upload/install/setup_x.exe HTTP/1.1\r\n" + HOSTB + b"Content-Length: 999999999\r\n"
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
        c.sendall(b"PUT /api/upload/install/huge.exe HTTP/1.1\r\n" + HOSTB + b"Content-Length: %d\r\n"
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
        n = len(card_rw_calls())
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
        # game-install wrote through card-rw: its begin, its end
        gi = [c[0] for c in card_rw_calls()[n:] if c[2] in ("game-install", "python3")]
        self.assertEqual(gi, ["begin", "end"], card_rw_calls()[n:])
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

    def test_install_unknown_gog_registry(self):
        """a game without a recipe: the registry values of its goggame-*.script into its wine.ini"""
        d = self.tiny_game("Reg Game")
        def act(root, sub, name=None, data=None, typ="string", langs=("*",), action="setRegistry", **more):
            a = {"root": root, "subkey": sub, **more}
            if name is not None:
                a.update(valueName=name, valueData=data, valueType=typ)
            return {"install": {"action": action, "arguments": a}, "languages": list(langs), "name": "r"}
        script = {"productId": "77", "actions": [
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", deleteSubkeys=True),	# a key deleted: nothing
            act("HKEY_CURRENT_USER", "SOFTWARE\\Pub\\Game", "Install Path", "{app}\\"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Product_Path", "{app}"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Lang", "25", langs=("ru-RU", "uk-UA")),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Lang", "9", langs=("en-US",)),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Lang", "1", langs=("*",)),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Lang", "7", langs=("de-DE",)),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Release", "Retail EMEA"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game\\1.0", "Only English", "yes", langs=("en-US",)),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", "Count", "1", typ="dword"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", "Docs", "{userdocs}\\Game"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", "a=b", "x"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", "", "default"),
            act("HKEY_LOCAL_MACHINE", "SOFTWARE\\Pub\\Game", "Comment", "a ;b"),
            {"install": {"action": "supportData", "arguments": {"source": "{supportDir}\\x", "target": "{app}"}},
             "languages": ["*"], "name": "copy"},
        ]}
        touch(os.path.join(d, "goggame-77.script"), json.dumps(script).encode("utf-8-sig"))
        try:
            s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Reg Game"})
            self.assertEqual(s, 200, r)
            ev = events(r["job"])
            self.assertEqual((ev[-1]["type"], ev[-1]["folder"]), ("done", "reg-game"), ev)
            ini = open(os.path.join(GAMES, "reg-game", "wine.ini"), encoding="utf-8").read()
            self.assertEqual([l for l in ini.splitlines() if l.startswith("reg")], [
                "reg = HKCU\\SOFTWARE\\Pub\\Game\\Install Path=D:\\reg-game\\",
                "reg = HKLM\\SOFTWARE\\Pub\\Game\\1.0\\Product_Path=D:\\reg-game",
                "reg = HKLM\\SOFTWARE\\Pub\\Game\\1.0\\Lang=25",
                "reg = HKLM\\SOFTWARE\\Pub\\Game\\1.0\\Release=Retail EMEA",
                "reg = HKLM\\SOFTWARE\\Pub\\Game\\1.0\\Only English=yes"])
            # as bare_app reads it (the server's reader: ini.c's rules)
            regs = bw.ini_sections(bw.ini_parse(ini))[""]["reg"]
            self.assertEqual(regs[0], "HKCU\\SOFTWARE\\Pub\\Game\\Install Path=D:\\reg-game\\")
        finally:
            shutil.rmtree(os.path.join(GAMES, "reg-game"), True)
        # more than bare_app_wine takes (16): the first 16
        d = self.tiny_game("Reg Many")
        many = {"actions": [act("HKEY_CURRENT_USER", "SOFTWARE\\M", "v%02d" % i, str(i)) for i in range(20)]}
        touch(os.path.join(d, "goggame-78.script"), json.dumps(many).encode())
        try:
            s, r = jreq("POST", "/api/install/run", {"path": d, "exe": "tiny.exe", "title": "Reg Many"})
            ev = events(r["job"])
            self.assertEqual(ev[-1]["type"], "done", ev)
            ini = open(os.path.join(GAMES, "reg-many", "wine.ini"), encoding="utf-8").read()
            regs = [l for l in ini.splitlines() if l.startswith("reg")]
            self.assertEqual(len(regs), 16)
            self.assertEqual(regs[-1], "reg = HKCU\\SOFTWARE\\M\\v15=15")
        finally:
            shutil.rmtree(os.path.join(GAMES, "reg-many"), True)

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
        # made by POST (no GET makes one), then downloaded
        self.assertIn(req("GET", "/api/report?game=coldfear")[0], (404, 405))
        self.assertEqual(jreq("GET", "/api/reports")[1]["reports"], [])
        s, r = jreq("POST", "/api/report", {"game": "coldfear"})
        self.assertEqual(s, 200, r)
        name = "2026-11-25_12-00-00-coldfear.txt"
        self.assertEqual((r["where"], r["name"]), ("card", name))
        s, h, d = req("GET", "/api/reports/card/%s?download=1" % name)
        self.assertEqual(d, b"a report of coldfear\n")
        self.assertIn(name, dict(h)["Content-Disposition"])
        r = jreq("GET", "/api/reports")[1]["reports"]
        self.assertEqual([(x["where"], x["name"]) for x in r], [("card", name)])
        self.assertEqual(req("GET", "/api/reports/card/" + name)[2], b"a report of coldfear\n")
        self.assertEqual(jreq("POST", "/api/report", {"game": "../x"})[0], 400)
        self.assertEqual(req("DELETE", "/api/reports/card/..%2Fcoldfear%2Fwine.ini")[0], 404)
        self.assertEqual(req("DELETE", "/api/reports/card/" + name)[0], 200)
        self.assertEqual(jreq("GET", "/api/reports")[1]["reports"], [])
        os.environ["FAIL_REPORT"] = "1"
        s, r = jreq("POST", "/api/report", {})
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
        """each writer of this server a begin of card-rw (this pid) and its end,
        nested ones too, an exception inside too; a begin that fails no end"""
        n = len(card_rw_calls())
        me = str(os.getpid())
        with bw.CardWriting():
            with bw.CardWriting():
                pass
            self.assertEqual([c[:2] for c in card_rw_calls()[n:]], [("begin", me), ("begin", me), ("end", me)])
        with self.assertRaises(ZeroDivisionError):
            with bw.CardWriting():
                1 / 0
        self.assertEqual([c[0] for c in card_rw_calls()[n:]], ["begin", "begin", "end", "end", "begin", "end"])
        touch(os.path.join(STATE, "no-card-rw"))
        try:
            with self.assertRaises(bw.CardError):
                with bw.CardWriting():
                    self.fail("written without the card writable")
            # an upload: refused, nothing written
            s, h, d = req("PUT", "/api/upload/install/setup_rw.exe", b"data")
            self.assertEqual(s, 503, d)
            self.assertFalse(os.path.exists(os.path.join(GAMES, "install", "setup_rw.exe")))
        finally:
            os.remove(os.path.join(STATE, "no-card-rw"))
        self.assertEqual(len(card_rw_calls()), n + 6)
        # uploads (a whole one, one cut short) and deletions through the server: pairs
        k = len(card_rw_calls())
        self.assertEqual(req("PUT", "/api/upload/updates/x.upd", b"data")[0], 200)
        self.assertEqual(req("DELETE", "/api/files/updates/x.upd")[0], 200)
        c = socket.create_connection(("127.0.0.1", PORT))
        c.sendall(b"PUT /api/upload/install/setup_cut2.exe HTTP/1.1\r\n" + HOSTB +
                  b"Content-Length: 5000\r\n\r\nabc")
        c.shutdown(socket.SHUT_WR)
        c.settimeout(10)
        c.recv(4096)
        c.close()
        deadline = time.time() + 5
        while len(card_rw_calls()) < k + 6 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual([c[0] for c in card_rw_calls()[k:]], ["begin", "end"] * 3)
        card_rw_balanced(self)

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


class GateTest(unittest.TestCase):
    """who is answered: Host of the device, Origin of the page, no simple
    request of another site's form or image; bodies; names; the hooks"""

    def raw(self, text, body=b""):
        """a request as bytes; its status line and the connection's state"""
        c = socket.create_connection(("127.0.0.1", PORT))
        c.settimeout(10)
        c.sendall(text.encode() + body)
        data = b""
        while b"\r\n\r\n" not in data:
            b = c.recv(65536)
            if not b:
                break
            data += b
        return c, data

    def test_host(self):
        for host, ok in (("127.0.0.1:%d" % PORT, True), ("192.168.7.2:%d" % PORT, True),
                         ("10.1.2.3:%d" % PORT, True),		# wlan0's
                         ("127.0.0.1", False),			# another port (80)
                         ("evil.example:%d" % PORT, False), ("localhost:%d" % PORT, False),
                         ("192.168.7.1:%d" % PORT, False), ("", False)):
            for path in ("/", "/app.js", "/api/status"):
                s, h, d = req("GET", path, headers={"Host": host})
                self.assertEqual(s == 200, ok, (host, path, s))
                if not ok:
                    self.assertEqual(s, 421, (host, path))
        # none at all, two of them
        c, d = self.raw("GET /api/status HTTP/1.1\r\n\r\n")
        c.close()
        self.assertIn(b" 421 ", d.split(b"\r\n")[0])
        c, d = self.raw("GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nHost: evil\r\n\r\n" % PORT)
        c.close()
        self.assertIn(b" 421 ", d.split(b"\r\n")[0])
        # a POST with another Host: nothing done
        k = len(calls())
        s, h, d = req("POST", "/api/reboot", headers={"Host": "evil.example"})
        self.assertEqual(s, 421)
        time.sleep(1.3)
        self.assertNotIn("reboot", calls()[k:])

    def test_origin(self):
        me = "http://127.0.0.1:%d" % PORT
        for origin, ok in ((me, True), ("http://evil.example", False), ("null", False),
                           ("http://127.0.0.1:1", False), ("https://127.0.0.1:%d" % PORT, False),
                           ("http://192.168.7.2:%d" % PORT, False)):	# a device address, not this Host
            s, h, d = req("GET", "/api/status", headers={"Origin": origin}, page=False)
            self.assertEqual(s == 200, ok, (origin, s))
            s, h, d = req("POST", "/api/report", b"", page=False,
                          headers={"Origin": origin, "Content-Type": "text/plain"})
            self.assertEqual(s == 200, ok, (origin, s, d))
            if not ok:
                self.assertEqual(s, 403)

    def test_simple_requests_refused(self):
        """what a form or an image of another site can send: no Origin (an old
        browser, curl), no X-Requested-With, not JSON"""
        k = len(calls())
        for method, path, body, ctype in (
                ("POST", "/api/reboot", b"", "text/plain"),
                ("POST", "/api/update/switch", b"x", "text/plain"),
                ("POST", "/api/install/remove", b'{"path": "x"}', "text/plain"),
                ("POST", "/api/saves/restore", b'{"where": "data", "name": "x"}',
                 "application/x-www-form-urlencoded"),
                ("POST", "/api/report", b"", "multipart/form-data; boundary=x"),
                ("PUT", "/api/upload/updates/evil.upd", b"data", "text/plain"),
                ("DELETE", "/api/files/updates/x.upd", b"", "")):
            h = {"Content-Type": ctype} if ctype else {}
            s, _, d = req(method, path, body, headers=h, page=False)
            self.assertEqual(s, 403, (method, path, d))
        time.sleep(1.3)
        self.assertNotIn("reboot", calls()[k:])
        self.assertFalse(os.path.exists(os.path.join(GAMES, "updates", "evil.upd")))
        # the same with the page's header: answered
        s, h, d = req("POST", "/api/report", b"", headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 200, d)
        # JSON without the header: answered (no other site's form sends JSON)
        s, h, d = req("POST", "/api/report", b"{}", headers={"Content-Type": "application/json"}, page=False)
        self.assertEqual(s, 200, d)
        for r in jreq("GET", "/api/reports")[1]["reports"]:
            req("DELETE", "/api/reports/%s/%s" % (r["where"], r["name"]))
        # GETs change nothing: the old ones that did are gone
        for path in ("/api/report", "/api/report?game=coldfear", "/api/saves/all",
                     "/api/saves/coldfear/backup"):
            self.assertIn(req("GET", path)[0], (404, 405), path)

    def test_json_only_as_json(self):
        # a JSON body that is not sent as application/json is not read
        s, h, d = req("POST", "/api/saves/info", b'{"where": "data", "name": "saves-x.zip"}',
                      headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 400, d)
        s, h, d = req("POST", "/api/pad", b'{"button": "a", "down": true}', headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 400, d)
        # as JSON it is read (no copy of that name: 404)
        s, r = jreq("POST", "/api/saves/info", {"where": "data", "name": "saves-x.zip"})
        self.assertEqual(s, 404, r)

    def test_unread_body_closes(self):
        """a PUT that no handler reads: the answer closes the connection; a
        POST's body is read and dropped: what is in it is no next request"""
        for method, path in (("PUT", "/api/nothing"), ("PUT", "/nothing.html"), ("POST", "/api/nothing"),
                             ("PUT", "/api/upload/elsewhere/x")):
            body = b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n" * 3
            c, d = self.raw("%s %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Requested-With: bare-web\r\n"
                            "Content-Length: %d\r\n\r\n" % (method, path, PORT, len(body)), body)
            head = d.split(b"\r\n\r\n")[0]
            self.assertRegex(head.split(b"\r\n")[0], rb" (404|405) ", (method, path))
            rest, closed = b"", False
            c.settimeout(1.5)
            try:
                while True:
                    b = c.recv(65536)
                    if not b:
                        closed = True
                        break
                    rest += b
            except socket.timeout:
                pass
            c.close()
            if method == "PUT":
                self.assertTrue(closed, "the connection stays open: %s %s" % (method, path))
            self.assertNotIn(b"HTTP/1.1 ", rest.split(b"\r\n\r\n", 1)[-1], (method, path))
            self.assertNotIn(b"421", rest, (method, path))
        # a body over 64 KB for a POST: refused, closed
        c, d = self.raw("POST /api/report HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Requested-With: bare-web\r\n"
                        "Content-Length: 70000\r\n\r\n" % PORT)
        c.close()
        self.assertIn(b" 413 ", d.split(b"\r\n")[0])

    def test_chunked_refused(self):
        """a body of chunks: 411 (with Content-Length too: 400), Connection:
        close, the connection closed, nothing of the body answered"""
        inner = b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n" % PORT
        chunk = b"%x\r\n%s\r\n0\r\n\r\n" % (len(inner), inner)
        for method, path, extra, code in (("POST", "/api/report", "", b"411"),
                                          ("PUT", "/api/upload/install/x.bin", "", b"411"),
                                          ("GET", "/api/status", "", b"411"),
                                          ("POST", "/api/report", "Content-Length: %d\r\n" % len(chunk), b"400")):
            with self.subTest(method=method, extra=extra):
                c, d = self.raw("%s %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Requested-With: bare-web\r\n"
                                "Transfer-Encoding: chunked\r\n%s\r\n" % (method, path, PORT, extra), chunk)
                head = d.split(b"\r\n\r\n")[0]
                self.assertIn(b" %s " % code, head.split(b"\r\n")[0])
                self.assertIn(b"\r\nConnection: close", head)
                rest, closed = d.split(b"\r\n\r\n", 1)[1], False
                c.settimeout(1.5)
                try:
                    while True:
                        b = c.recv(65536)
                        if not b:
                            closed = True
                            break
                        rest += b
                except socket.timeout:
                    pass
                c.close()
                self.assertTrue(closed)
                self.assertNotIn(b"HTTP/1.1 ", rest)
        self.assertFalse(os.path.exists(os.path.join(GAMES, "install", "x.bin.part")))

    def test_logs_numbers(self):
        for n in ("0", "4", "01", "1.0", "1 ", "+1", "-1", "1x", "١", "", "12"):
            self.assertEqual(req("GET", "/api/logs/coldfear/" + urllib.parse.quote(n))[0], 404, n)
        self.assertEqual(req("GET", "/api/logs/coldfear/1")[0], 200)

    def test_card_names(self):
        for bad in ('a:b.exe', 'a?.exe', 'a<b', 'a>b', 'a"b', 'a|b', 'a*b', 'a\\b', 'a\x01b', 'a\x7fb',
                    'trail.', 'trail '):
            s, h, d = req("PUT", "/api/upload/install/" + urllib.parse.quote(bad), b"data")
            self.assertEqual(s, 400, bad)
            self.assertIn("не подходит", json.loads(d)["error"], bad)
        self.assertEqual(os.listdir(os.path.join(GAMES, "install")) and
                         [n for n in os.listdir(os.path.join(GAMES, "install")) if n.startswith(("a", "trail"))], [])
        s, h, d = req("PUT", "/api/saves/upload/" + urllib.parse.quote("saves-a:b.zip"), b"x")
        self.assertEqual(s, 400)
        self.assertTrue(bw.card_name_ok("setup_cold_fear_(86830)-1.bin") and bw.card_name_ok("Шрифт #1.ttf"))

    def test_copy_path_no_links(self):
        d = os.path.join(DATA, "backups")
        os.makedirs(d, exist_ok=True)
        outside = os.path.join(TOP, "outside.zip")
        touch(outside, b"secret")
        link = os.path.join(d, "saves-link-2026-01-01_00-00-00.zip")
        os.symlink(outside, link)
        try:
            self.assertEqual(req("GET", "/api/saves/copy/data/" + os.path.basename(link))[0], 404)
            self.assertEqual(req("DELETE", "/api/saves/copy/data/" + os.path.basename(link))[0], 404)
            self.assertTrue(os.path.exists(outside))
        finally:
            os.remove(link)
        # the directory itself a link
        real_dir = os.path.join(TOP, "elsewhere")
        os.makedirs(real_dir)
        touch(os.path.join(real_dir, "saves-x-2026-01-01_00-00-00.zip"), b"x")
        card = os.path.join(GAMES, "backups")
        had = os.path.lexists(card)
        if not had:
            os.symlink(real_dir, card)
            try:
                self.assertEqual(req("GET", "/api/saves/copy/card/saves-x-2026-01-01_00-00-00.zip")[0], 404)
            finally:
                os.remove(card)

    def test_saves_info_not_json(self):
        d = os.path.join(DATA, "backups")
        os.makedirs(d, exist_ok=True)
        name = "saves-odd-2026-01-01_00-00-00.zip"
        touch(os.path.join(d, name), b"x")
        real = bw.run
        bw.run = lambda argv, timeout=60: (0, "not json", "")
        try:
            s, r = jreq("POST", "/api/saves/info", {"where": "data", "name": name})
        finally:
            bw.run = real
            os.remove(os.path.join(d, name))
        self.assertEqual(s, 500)
        self.assertIn("не JSON", r["error"])

    def test_hooks_all_or_none(self):
        """bare-web, game-install: one test place set and not all of them refused
        at the start (never the device's own place for the rest)"""
        code = ("import importlib.machinery, importlib.util, sys\n"
                "l = importlib.machinery.SourceFileLoader('bw', %r)\n"
                "m = importlib.util.module_from_spec(importlib.util.spec_from_loader('bw', l))\n"
                "l.exec_module(m)\nprint('started')\n" % BARE_WEB)
        base = {k: v for k, v in os.environ.items() if not k.startswith(("BARE_WEB_", "GAME_INSTALL_"))}
        for drop in ("BARE_WEB_CARD_RW", "BARE_WEB_GAMES", "BARE_WEB_RUN", "BARE_WEB_IP"):
            env = dict(base, **{k: v for k, v in ENV.items() if k.startswith("BARE_WEB_") and k != drop})
            r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, drop)
            self.assertIn("refused", r.stderr, drop)
            self.assertIn(drop, r.stderr)
        env = dict(base, BARE_WEB_LOG=os.path.join(TOP, "x.log"))
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        env = dict(base, **{k: v for k, v in ENV.items() if k.startswith("BARE_WEB_")}, BARE_WEB_TYPO="x")
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertIn("unknown BARE_WEB_TYPO", r.stderr)
        env = dict(base, **{k: v for k, v in ENV.items() if k.startswith("BARE_WEB_")})
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "started", r.stderr)
        # what /usr/sbin/bare-web sets on the device is no test hook
        env = dict(base, BARE_WEB_THP="off", BARE_WEB_LIB="/usr/lib/bare-web")
        r = subprocess.run([sys.executable, "-c", code + "print(m.TEST)\n"], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ["started", "False"], r.stderr)
        # game-install: the lock and card-rw too, never /run's
        gi = {k: v for k, v in ENV.items() if k.startswith("GAME_INSTALL_")}
        for drop in ("GAME_INSTALL_LOCK", "GAME_INSTALL_CARD_RW", "GAME_INSTALL_GAMES"):
            env = dict(base, **{k: v for k, v in gi.items() if k != drop})
            r = subprocess.run([sys.executable, GAME_INSTALL, "scan"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, drop)
            self.assertIn("refused", r.stderr)
            self.assertIn("fail error", r.stdout)
        env = dict(base, **gi)
        r = subprocess.run([sys.executable, GAME_INSTALL, "scan"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)



FOREIGN = "127.0.0.9"	# a client of another address than the USB computer's (Wi-Fi)
FOREIGN2 = "127.0.0.10"	# another one of the same network


def freq(method, path, body=None, headers=None, cookie=None, page=True, source=FOREIGN):
    """a request from FOREIGN (its own source address: the server sees it as is)"""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30, source_address=(source, 0))
    h = dict(headers or {})
    if page:
        h.setdefault("X-Requested-With", "bare-web")
    if cookie:
        h["Cookie"] = cookie
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data


class PinTest(unittest.TestCase):
    """an address other than the USB computer's: nothing but the PIN's page and
    POST /api/pin without a session; the session a cookie of the right PIN"""
    PIN = os.path.join(DATA, "bare-web.pin")

    def setUp(self):
        with bw.PIN_LOCK:
            bw.PIN_STATE.clear()
            bw.SESSIONS.clear()
        self.set_pin("123456")

    def tearDown(self):
        if os.path.lexists(self.PIN):
            os.unlink(self.PIN)
        with bw.PIN_LOCK:
            bw.PIN_STATE.clear()

    def set_pin(self, pin):
        if os.path.lexists(self.PIN):
            os.unlink(self.PIN)
        if pin is not None:
            with open(self.PIN, "w") as f:
                f.write(pin + "\n")

    def login(self, pin="123456"):
        s, h, d = freq("POST", "/api/pin", {"pin": pin})
        self.assertEqual(s, 200, d)
        c = h["set-cookie"]
        self.assertIn("HttpOnly", c)
        self.assertIn("SameSite=Strict", c)
        self.assertIn("Max-Age=86400", c)
        self.assertIn("Path=/", c)
        return c.split(";")[0]

    def assert_closed(self, cookie=None):
        """nothing but the PIN's page: no static file, no API"""
        app = open(os.path.join(STATIC, "app.js"), "rb").read()
        for path in ("/", "/index.html", "/app.js", "/app.css", "/x", "/API/status"):
            for m in ("GET", "HEAD"):
                s, h, d = freq(m, path, cookie=cookie)
                self.assertEqual(s, 401, (m, path))
                if m == "GET":
                    self.assertIn("PIN".encode(), d, path)
                    self.assertNotIn(app[:200], d)
                    self.assertTrue(h["content-type"].startswith("text/html"), (path, h, d[:200]))
        for m, path in (("GET", "/api/status"), ("GET", "/api/games"), ("GET", "/api"), ("GET", "/api/job"),
                        ("GET", "/api/job/1/events"), ("GET", "/api/shot.png"), ("GET", "/api/saves"),
                        ("POST", "/api/report"), ("POST", "/api/reboot"), ("DELETE", "/api/files/updates/x.upd"),
                        ("GET", "/api/pin"), ("GET", "//api/status")):
            k = len(calls())
            s, h, d = freq(m, path, b"" if m != "GET" else None, cookie=cookie)
            self.assertEqual(s, 401, (m, path, d))
            self.assertIn("PIN", json.loads(d)["error"])
            self.assertEqual(calls()[k:], [], path)
        # an upload: refused before its body (Expect: 100-continue)
        c = socket.create_connection(("127.0.0.1", PORT), source_address=(FOREIGN, 0))
        c.settimeout(10)
        c.sendall(b"PUT /api/upload/updates/p.upd HTTP/1.1\r\n" + HOSTB + b"Content-Length: 4\r\n" +
                  (b"Cookie: %s\r\n" % cookie.encode() if cookie else b"") + b"Expect: 100-continue\r\n\r\n")
        self.assertIn(b" 401 ", c.recv(4096).split(b"\r\n")[0])
        c.close()
        self.assertFalse(os.path.exists(os.path.join(GAMES, "updates", "p.upd")))

    def test_rules(self):
        self.assertEqual((bw.PIN_TRIES, bw.PIN_PAUSE, bw.SESSION_AGE), (5, 60.0, 86400))
        self.assertEqual(bw.PIN_FILE, os.path.join(DATA, "bare-web.pin"))

    def test_closed_without_session(self):
        self.assert_closed()
        self.assert_closed(cookie="bare_web_session=" + "0" * 48)
        self.assert_closed(cookie="other=1")

    def test_usb_and_device_as_before(self):
        """the USB computer and the device itself: no PIN, no cookie"""
        self.set_pin(None)
        for path in ("/", "/app.js", "/api/status"):
            self.assertEqual(req("GET", path)[0], 200, path)
        class H:
            allowed = bw.Handler.allowed
        for ip, ok in (("192.168.7.1", True), ("192.168.7.200", True), ("127.0.0.1", True),
                       ("10.1.2.50", False), ("127.0.0.9", False), ("192.168.70.1", False)):
            h = H()
            h.client_address = (ip, 1)
            self.assertEqual(h.allowed(), ok, ip)

    def test_pin_opens(self):
        cookie = self.login()
        app = open(os.path.join(STATIC, "app.js"), "rb").read()
        s, h, d = freq("GET", "/app.js", cookie=cookie)
        self.assertEqual((s, d), (200, app))
        s, h, d = freq("GET", "/", cookie=cookie)
        self.assertEqual(s, 200)
        self.assertNotIn(b"/api/pin", d)
        s, h, d = freq("GET", "/api/status", cookie=cookie)
        self.assertEqual(s, 200)
        self.assertIn("release", json.loads(d))
        s, h, d = freq("PUT", "/api/upload/updates/p.upd", b"data", cookie=cookie)
        self.assertEqual(s, 200, d)
        self.assertEqual(freq("DELETE", "/api/files/updates/p.upd", cookie=cookie)[0], 200)
        # the cookie among others
        self.assertEqual(freq("GET", "/api/status", cookie="a=1; " + cookie + "; b=2")[0], 200)
        # the Host and Origin rules still hold
        self.assertEqual(freq("GET", "/api/status", cookie=cookie, headers={"Host": "evil.example"})[0], 421)
        self.assertEqual(freq("POST", "/api/report", b"", cookie=cookie, page=False,
                              headers={"Origin": "http://evil.example"})[0], 403)

    def test_session_ends(self):
        cookie = self.login()
        self.assertEqual(freq("GET", "/api/status", cookie=cookie)[0], 200)
        # a new PIN: every session of the old one over
        self.set_pin("654321")
        self.assert_closed(cookie)
        self.set_pin("123456")
        self.assertEqual(freq("GET", "/api/status", cookie=cookie)[0], 401)	# dropped, not back
        # no PIN at all
        cookie = self.login()
        self.set_pin(None)
        self.assertEqual(freq("GET", "/api/status", cookie=cookie)[0], 401)
        # 24 h over
        self.set_pin("123456")
        cookie = self.login()
        token = cookie.split("=", 1)[1]
        with bw.PIN_LOCK:
            until, pin = bw.SESSIONS[token]
            bw.SESSIONS[token] = (time.monotonic() - 0.01, pin)
        self.assertEqual(freq("GET", "/api/status", cookie=cookie)[0], 401)
        # two sessions side by side, each its own
        a, b = self.login(), self.login()
        self.assertNotEqual(a, b)
        self.assertEqual(freq("GET", "/api/status", cookie=a)[0], 200)
        self.assertEqual(freq("GET", "/api/status", cookie=b)[0], 200)

    def stream(self, path, cookie):
        """an event stream opened from FOREIGN with the cookie: the socket, its headers read"""
        c = socket.create_connection(("127.0.0.1", PORT), source_address=(FOREIGN, 0))
        c.settimeout(10)
        c.sendall(b"GET %s HTTP/1.1\r\n" % path.encode() + HOSTB + b"Cookie: %s\r\n\r\n" % cookie.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            d = c.recv(4096)
            self.assertTrue(d, head)
            head += d
        self.assertIn(b" 200 ", head.split(b"\r\n")[0])
        return c

    def ends_within(self, c, seconds):
        """the stream closed by the server within seconds (its data read away)"""
        end = time.monotonic() + seconds
        c.settimeout(0.2)
        while time.monotonic() < end:
            try:
                if not c.recv(65536):
                    return True
            except socket.timeout:
                continue
            except OSError:
                return True
        return False

    def test_streams_end_with_pin(self):
        """a new PIN ends the event streams of the old one's sessions (asked
        again every SSE_RECHECK); with the PIN the same they go on"""
        saved = bw.SSE_RECHECK
        bw.SSE_RECHECK = 0.3
        job = None
        try:
            os.makedirs(os.path.join(LOGS, "streamtest"), exist_ok=True)
            with bw.Jobs.lock:
                job = bw.Jobs.current = bw.Job("install", "stream test")
            cookie = self.login()
            log_s = self.stream("/api/logs/streamtest/live", cookie)
            job_s = self.stream("/api/job/%d/events" % job.id, cookie)
            self.assertFalse(self.ends_within(log_s, 1.5))	# the PIN the same: open
            self.assertFalse(self.ends_within(job_s, 0.5))
            self.set_pin("654321")
            self.assertTrue(self.ends_within(log_s, 3))
            self.assertTrue(self.ends_within(job_s, 3))
            log_s.close()
            job_s.close()
        finally:
            bw.SSE_RECHECK = saved
            if job:
                with job.cond:
                    job.ended = True
                    job.cond.notify_all()
            shutil.rmtree(os.path.join(LOGS, "streamtest"), ignore_errors=True)

    def test_no_pin_yet(self):
        for text in (None, "12345", "1234567", "abcdef", "12 456", ""):
            self.set_pin(text)
            s, h, d = freq("POST", "/api/pin", {"pin": text or "123456"})
            self.assertEqual(s, 503, text)
            self.assertIn("Приставка в браузере", json.loads(d)["error"])
            self.assertNotIn("set-cookie", h)
        # a link is no PIN file
        other = os.path.join(TOP, "pin-elsewhere")
        with open(other, "w") as f:
            f.write("123456\n")
        self.set_pin(None)
        os.symlink(other, self.PIN)
        self.assertEqual(freq("POST", "/api/pin", {"pin": "123456"})[0], 503)
        os.unlink(other)

    def test_wrong_pins_pause(self):
        for i, pin in enumerate(("000000", "12345", "1234567", 123456)):
            s, h, d = freq("POST", "/api/pin", {"pin": pin})
            self.assertEqual(s, 403, pin)
            self.assertEqual(json.loads(d)["left"], 4 - i)
            self.assertNotIn("set-cookie", h)
        s, h, d = freq("POST", "/api/pin", {"pin": "999999"})	# the 5th
        self.assertEqual(s, 429)
        self.assertEqual(json.loads(d)["wait"], 60)
        # paused: the right one too, from this address
        s, h, d = freq("POST", "/api/pin", {"pin": "123456"})
        self.assertEqual(s, 429)
        self.assertNotIn("set-cookie", h)
        self.assertGreater(json.loads(d)["wait"], 50)
        # another address of the same network is not held by it: its own count
        s, h, d = freq("POST", "/api/pin", {"pin": "000000"}, source=FOREIGN2)
        self.assertEqual((s, json.loads(d)["left"]), (403, 4))
        s, h, d = freq("POST", "/api/pin", {"pin": "123456"}, source=FOREIGN2)
        self.assertEqual(s, 200, d)
        self.assertIn("set-cookie", h)
        self.assertEqual(freq("POST", "/api/pin", {"pin": "123456"})[0], 429)	# the first still paused
        # the pause over (made short): five more
        with bw.PIN_LOCK:
            bw.PIN_STATE[FOREIGN]["until"] = time.monotonic() + 0.3
        time.sleep(0.4)
        for i in range(4):
            self.assertEqual(freq("POST", "/api/pin", {"pin": "000001"})[0], 403)
        self.login()	# a right one: the count starts again
        for i in range(4):
            self.assertEqual(freq("POST", "/api/pin", {"pin": "000001"})[0], 403)
        self.assertEqual(freq("POST", "/api/pin", {"pin": "000001"})[0], 429)

    def test_forwarded_for_not_counted(self):
        """the address counted is the connection's: X-Forwarded-For (or any
        header) does not give another one"""
        for i in range(5):
            s, h, d = freq("POST", "/api/pin", {"pin": "000000"},
                           headers={"X-Forwarded-For": "10.9.9.%d" % i, "X-Real-IP": "10.9.8.%d" % i})
            self.assertEqual(s, 403 if i < 4 else 429, (i, d))
        self.assertEqual(list(bw.PIN_STATE), [FOREIGN])
        s, h, d = freq("POST", "/api/pin", {"pin": "123456"}, headers={"X-Forwarded-For": "10.9.9.99"})
        self.assertEqual(s, 429)	# paused for FOREIGN whatever the header says

    def test_wrong_pins_addresses_kept(self):
        """at most PIN_ADDRS addresses: the one longest untouched dropped, the others
        keep their counts"""
        for i in range(bw.PIN_ADDRS):
            self.assertEqual(bw.pin_try("000000", "10.0.0.%d" % i)[0], 403)
        self.assertEqual(len(bw.PIN_STATE), bw.PIN_ADDRS)
        self.assertEqual(bw.pin_try("000000", "10.0.0.1")[1]["left"], 3)	# touched again
        self.assertEqual(bw.pin_try("000000", "10.0.1.0")[0], 403)	# one more address
        self.assertEqual(len(bw.PIN_STATE), bw.PIN_ADDRS)
        self.assertNotIn("10.0.0.0", bw.PIN_STATE)	# the one longest untouched
        self.assertEqual(bw.PIN_STATE["10.0.0.1"]["wrong"], 2)
        self.assertEqual(bw.pin_try("000000", "10.0.0.2")[1]["left"], 3)
        self.assertEqual(bw.pin_try("000000", "10.0.0.0")[1]["left"], 4)	# counted anew
        # dropped by when last tried, not by when first: 10.0.0.1 (tried again) stays
        self.assertIn("10.0.0.1", bw.PIN_STATE)
        self.assertNotIn("10.0.0.3", bw.PIN_STATE)

    def test_wifi_address_changes(self):
        """DHCP gives Wi-Fi another address: the new one is the device's (its Host
        answered) once the addresses are read again (HOSTS_AGE), the old one not"""
        ip = os.path.join(BIN, "ip")
        old = open(ip).read()
        cookie = self.login()
        try:
            with open(ip, "w") as f:
                f.write(old.replace("10.1.2.3/24", "10.1.2.77/24"))
            self.assertEqual(bw.HOSTS_AGE, 5.0)
            with bw.HOSTS_LOCK:
                bw.HOSTS["at"] = time.monotonic() - bw.HOSTS_AGE - 0.1	# as 5 s later
            port = ":%d" % PORT
            self.assertEqual(freq("GET", "/api/status", cookie=cookie, headers={"Host": "10.1.2.77" + port})[0], 200)
            self.assertEqual(freq("GET", "/api/status", cookie=cookie, headers={"Host": "10.1.2.3" + port})[0], 421)
            self.assertEqual(freq("GET", "/", headers={"Host": "10.1.2.77" + port})[0], 401)	# the PIN's page
        finally:
            with open(ip, "w") as f:
                f.write(old)
            with bw.HOSTS_LOCK:
                bw.HOSTS["at"] = 0.0

    def test_pin_request_rules(self):
        # a form of another site: refused as every other change
        s, h, d = freq("POST", "/api/pin", b"pin=123456", page=False,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(s, 403)
        s, h, d = freq("POST", "/api/pin", {"pin": "123456"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(s, 403)
        s, h, d = freq("POST", "/api/pin", b"123456", headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 400)
        self.assertEqual(bw.PIN_STATE.get(FOREIGN, {"wrong": 0})["wrong"], 0)

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
        # a copy made by POST (no GET makes one), then downloaded
        for old in ("/api/saves/pirates/backup", "/api/saves/all"):
            self.assertIn(req("GET", old)[0], (404, 405), old)
        self.assertFalse(os.path.isdir(os.path.join(GAMES, "backups")))
        n = len(card_rw_calls())
        s, r = jreq("POST", "/api/saves/backup", {"game": "pirates"})
        self.assertEqual(s, 200, r)
        self.assertEqual(r["where"], "card")
        name = r["name"]
        self.assertIn("saves-pirates-", name)
        self.assertEqual([c[0] for c in card_rw_calls()[n:]], ["begin", "end"])	# bare-backup's
        s, h, d = req("GET", "/api/saves/copy/card/" + urllib.parse.quote(name))
        self.assertEqual(s, 200, d)
        h = dict(h)
        self.assertEqual(h["Content-Type"], "application/zip")
        self.assertIn("saves-pirates-", h["Content-Disposition"])
        self.assertEqual(r["size"], len(d))
        with zipfile.ZipFile(io.BytesIO(d)) as z:
            self.assertIn("manifest.json", z.namelist())
            self.assertIn("controls.0000abcd=a=b", z.read("settings.ini").decode())
        s, r = jreq("GET", "/api/saves")
        self.assertEqual([c["where"] for c in r["copies"]], ["card"])
        self.assertEqual(jreq("POST", "/api/saves/backup", {"game": "../x"})[0], 400)
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
        s, r = jreq("POST", "/api/saves/backup", {"game": "all"})
        self.assertEqual(s, 200, r)
        s, h, d = req("GET", "/api/saves/copy/%s/%s" % (r["where"], r["name"]), timeout=60)
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
        s, r = jreq("POST", "/api/saves/backup", {"game": "pirates"})
        self.assertEqual(s, 500)
        self.assertIn("bare_app не запущен", r["error"])


class FakeBareApp:
    """bare_app's FIFO (BARE_WEB_CTL): its lines kept; "reload FOLDER" writes
    the effective ini as bare_app would (the server's merge stands in for
    ini_layer.c here), "import-settings FILE" replaces those games' entries
    of bare_app.conf as ctl_settings.c does"""

    def __init__(self):
        self.lines = []
        self.fd = None
        self.games = {}	# folder: (base path, layer path, effective path)
        self.importing = "now"
        self.taken_back = []	# import files gone when it came to take them

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
        if cmd == "reload":	# games.json written anew, as bare_app does
            time.sleep(0.01)
            gj = os.path.join(ENV["BARE_WEB_RUN"], "games.json")
            if os.path.exists(gj):
                os.utime(gj)
        if cmd == "reload" and arg in self.games:
            base, layer, eff = self.games[arg]
            # ini_layer.c base_fits(): a line of the base over 1000 bytes, the layer broken
            fits = all(len(l.rstrip(b"\n")) <= 1000 for l in open(base, "rb"))
            if os.path.exists(layer) and fits:
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
            # as ctl_settings.c: taken (FILE.taken), then removed when in,
            # FILE.bad when not; self.importing: "now", "late" (after the
            # server's wait, in a thread), "never", "bad", "stuck"
            mode = self.importing
            if mode == "never":
                return
            if mode == "stuck":	# taken, never done
                os.rename(arg, arg + ".taken")
                return
            if mode == "late":
                threading.Thread(target=self.take_late, args=(arg,), daemon=True).start()
                return
            self.take(arg, mode == "bad")

    def take_late(self, path):
        time.sleep(bw.IMPORT_WAIT + 0.5)
        self.take(path, False)

    def take(self, path, bad):
        try:
            os.rename(path, path + ".taken")
        except FileNotFoundError:
            self.taken_back.append(path)
            return
        arg = path + ".taken"
        if bad:
            os.rename(arg, path + ".bad")
            return
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
        os.remove(arg)


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

    def test_games_list_of_the_workshop(self):
        """GET /api/games: the keys of each layer, the game running"""
        def pirates():
            return {g["id"]: g for g in jreq("GET", "/api/games")[1]["games"]}["pirates"]
        self.assertEqual((pirates()["layer_keys"], pirates()["running"]), (0, False))
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {
            "": {"mode": "1024x768", "modes": ["1280x960", "640x480"]}, "keys": {"select": "esc"}}})
        self.assertEqual(s, 200, r)
        self.assertEqual(pirates()["layer_keys"], 3)	# mode, modes (two lines: one key), select
        with open(os.path.join(ENV["BARE_WEB_RUN"], "state.json"), "w") as f:
            json.dump({"running": "pirates", "pid": 1, "time": int(time.time())}, f)
        self.assertTrue(pirates()["running"])
        os.remove(os.path.join(ENV["BARE_WEB_RUN"], "state.json"))
        with open(self.layer(), "a") as f:
            f.write("not a line of an ini\n")
        self.assertIsNone(pirates()["layer_keys"])
        with open(self.layer(), "w") as f:	# an empty file: no changes
            f.write("")
        self.assertEqual(pirates()["layer_keys"], 0)
        with open(self.layer(), "w") as f:	# comments only: none either
            f.write("; nothing\n\n")
        self.assertEqual(pirates()["layer_keys"], 0)
        self.assertEqual({g["id"]: g for g in jreq("GET", "/api/games")[1]["games"]}["fake"]["layer_keys"], 0)

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

    def test_base_line_too_long(self):
        """a line of the game's ini over 1000 bytes: bare_app does not use the
        layer (ini_layer.c), the server says the game's ini is in effect"""
        base = os.path.join(self.pirates, "wine.ini")
        text = open(base).read()
        for n, used in ((1001, False), (1000, True)):
            with self.subTest(n=n):
                with open(base, "w") as f:
                    f.write(text + ";" + "x" * (n - 1) + "\n")
                os.utime(base)
                eff = os.path.join(ENV["BARE_WEB_RUN"], "ini", "pirates.ini")
                if os.path.exists(eff):
                    os.remove(eff)
                s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"": {"mode": "1024x768"}}})
                self.assertEqual(s, 200, r)
                s, r = jreq("GET", "/api/recipe/pirates")
                if used:
                    self.assertEqual((r["effective"][""]["mode"], r["layer_problem"]), ("1024x768", None))
                else:
                    self.assertEqual(r["effective_source"], "base")
                    self.assertEqual(r["effective"][""]["mode"], r["base"][""]["mode"])
                    self.assertIn("длиннее 1000 байт", r["layer_problem"])

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
        imp = BARE_APP.lines[1].split(" ", 1)[1]
        self.assertEqual([p for p in (imp, imp + ".taken", imp + ".bad") if os.path.exists(p)], [])
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

    def test_adopt_not_applied(self):
        """bare_app takes the import after the server's wait, never, or
        cannot: the layer as it was, bare_app.conf untouched, an error; the
        late one finds the file taken back and changes nothing"""
        old_wait, bw.IMPORT_WAIT = bw.IMPORT_WAIT, 1.0
        try:
            for mode in ("late", "never", "bad", "stuck"):
                with self.subTest(mode=mode):
                    self.setUp()
                    jreq("PUT", "/api/recipe/pirates/layer", {"sections": {"keys": {"y": "esc"}}})
                    layer, conf = open(self.layer()).read(), open(ENV["BARE_WEB_CONF"]).read()
                    del BARE_APP.lines[:], BARE_APP.taken_back[:]
                    BARE_APP.importing = mode
                    s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
                    self.assertEqual(s, 503, r)
                    self.assertIn("не применила настройки, ничего не изменено", r["error"])
                    self.assertEqual(open(self.layer()).read(), layer)
                    imp = [l for l in BARE_APP.lines if l.startswith("import-settings ")][0].split(" ", 1)[1]
                    if mode == "late":
                        time.sleep(1.0)
                        self.assertEqual(BARE_APP.taken_back, [imp])
                    self.assertEqual(open(ENV["BARE_WEB_CONF"]).read(), conf)
                    if mode == "stuck":
                        os.remove(imp + ".taken")
                    self.assertEqual([p for p in (imp, imp + ".taken", imp + ".bad") if os.path.exists(p)], [])
                    self.assertEqual(BARE_APP.lines[-1], "reload pirates")	# the layer read again
                    BARE_APP.importing = "now"
            # and the same with no layer before: none after
            self.setUp()
            BARE_APP.importing = "never"
            s, r = jreq("POST", "/api/recipe/pirates/adopt-controls")
            self.assertEqual(s, 503, r)
            self.assertFalse(os.path.exists(self.layer()))
        finally:
            bw.IMPORT_WAIT = old_wait
            BARE_APP.importing = "now"

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
    def export(self, folder):
        s, h, d = req("POST", "/api/recipe/%s/export" % folder)
        return s, dict(h), d

    def test_export(self):
        """POST export: the zip of a recipe for the SDK (stage 6)"""
        s, r = jreq("PUT", "/api/recipe/pirates/layer", {"sections": {
            "": {"mode": "1024x768", "modes": ["1280x960", "1600x1200"], "dlls": ""},
            "keys": {"select": "esc"}, "labels.ru": {"f4": "карта мира"}, "newsec": {"k": "v"}}})
        self.assertEqual(s, 200, r)
        info = {"gameId": "1234567", "name": "Pirates GOG", "playTasks": [
            {"isPrimary": True, "path": "Pirates!.exe", "type": "FileTask"}]}
        for n, data in (("goggame-1234567.info", json.dumps(info).encode()), ("cover.png", b"\x89PNG-cover"),
                        ("__redist/x.cab", b"c"), ("tmp/t", b"t")):
            os.makedirs(os.path.dirname(os.path.join(self.pirates, n)), exist_ok=True)
            touch(os.path.join(self.pirates, n), data)
        os.makedirs(os.path.join(LOGS, "pirates"), exist_ok=True)
        log = "bare_app: a launch\n\xff not utf-8\n".encode("latin-1")
        touch(os.path.join(LOGS, "pirates", "1.log"), log)
        before = card_rw_calls()
        pop = os.path.join(GAMES, "pop")
        try:
            s, h, d = self.export("pirates")
            self.assertEqual(s, 200, d[:300])
            self.assertEqual(h["Content-Type"], "application/zip")
            self.assertIn("recipe-pirates-ogu-test-", h["Content-Disposition"])
            z = zipfile.ZipFile(io.BytesIO(d))
            self.assertEqual(sorted(z.namelist()), sorted([
                "games/pirates/overlay/wine.ini", "games/pirates/cover.png", "games/pirates/README.md",
                "manifest.section", "needs.txt", "logs/1.log"]))
            ini = z.read("games/pirates/overlay/wine.ini").decode()
            self.assertRegex(ini.splitlines()[0], r"^; made on the device ogu-test \d{4}-\d\d-\d\d, from "
                             r"GOG 1234567 \(Pirates GOG\), with the player's changes$")
            # the effective values (as the page shows them), the recipe's comments kept
            s, r = jreq("GET", "/api/recipe/pirates")
            self.assertEqual(bw.ini_sections(bw.ini_parse(ini)), r["effective"])
            self.assertEqual(r["effective"][""]["modes"], ["1280x960", "1600x1200"])
            self.assertNotIn("dlls", r["effective"][""])
            self.assertEqual(r["effective"]["newsec"], {"k": "v"})
            base = open(os.path.join(self.pirates, "wine.ini")).read()
            comments = [l for l in base.splitlines() if l.startswith(";")]
            self.assertEqual([l for l in ini.splitlines()[1:] if l.startswith(";")], comments)
            self.assertEqual(z.read("games/pirates/cover.png"), b"\x89PNG-cover")
            self.assertEqual(z.read("logs/1.log"), log)
            self.assertEqual(z.read("needs.txt"), b"")
            sec = z.read("manifest.section").decode().splitlines()
            self.assertEqual(sec[0], "[pirates]")
            for line in ("detect = Pirates!.exe", "gog = 1234567", "source = lab/games/Sid Meier's Pirates!",
                         "exclude = goggame-*", "exclude = __redist", "exclude = tmp",
                         "overlay = games/pirates/overlay", "cover = games/pirates/cover.png"):
                self.assertIn(line, sec)
            self.assertNotIn("exclude = commonappdata", sec)
            readme = z.read("games/pirates/README.md").decode()
            self.assertTrue(readme.startswith("# Sid Meier's Pirates!\n"), readme)
            self.assertIn("GOG id 1234567", readme)
            # nothing written on the card for it
            self.assertEqual(card_rw_calls()[len(before):], [])
            # a game of a firmware recipe (pop: detect, gog of the manifest), no layer, no cover or log
            os.makedirs(pop, exist_ok=True)
            touch(os.path.join(pop, "POP.EXE"))
            touch(os.path.join(pop, "prince.bf"))
            touch(os.path.join(pop, "wine.ini"), b"; pop\nname = Prince\nexe = poplaunch.exe\n")
            with open(os.path.join(ENV["BARE_WEB_RUN"], "games.json")) as f:
                gj = json.load(f)
            gj["games"].append({"folder": "pop", "name": "Prince", "kind": "wine", "key": "0000f0f0", "dir": pop})
            with open(os.path.join(ENV["BARE_WEB_RUN"], "games.json"), "w") as f:
                json.dump(gj, f)
            s, h, d = self.export("pop")
            self.assertEqual(s, 200, d[:300])
            z = zipfile.ZipFile(io.BytesIO(d))
            self.assertEqual(sorted(z.namelist()), ["games/pop/README.md", "games/pop/overlay/wine.ini",
                                                    "manifest.section", "needs.txt"])
            ini = z.read("games/pop/overlay/wine.ini").decode()
            self.assertEqual(ini.splitlines()[1:], ["; pop", "name = Prince", "exe = poplaunch.exe"])
            self.assertIn("the firmware's recipe [pop]", ini.splitlines()[0])
            self.assertNotIn("player's changes", ini.splitlines()[0])
            sec = z.read("manifest.section").decode().splitlines()
            self.assertIn("detect = POP.EXE | prince.bf", sec)
            self.assertFalse([l for l in sec if l.startswith(("gog", "exclude", "cover"))], sec)
            # a game.ini game: its game.ini; bare_app's own games and none: refused
            s, h, d = self.export("fake")
            self.assertEqual(s, 200, d[:300])
            self.assertIn("games/fake/overlay/game.ini", zipfile.ZipFile(io.BytesIO(d)).namelist())
            self.assertEqual(self.export("homm3")[0], 400)
            self.assertEqual(self.export("nothere")[0], 404)
            self.assertEqual(self.export("..")[0], 400)
            self.assertEqual(req("GET", "/api/recipe/pirates/export")[0], 404)	# no GET
            self.assertEqual(req("POST", "/api/recipe/pirates/export", page=False)[0], 403)
        finally:
            for n in ("goggame-1234567.info", "cover.png"):
                os.remove(os.path.join(self.pirates, n))
            for n in ("__redist", "tmp"):
                shutil.rmtree(os.path.join(self.pirates, n))
            shutil.rmtree(pop, True)
            os.remove(os.path.join(LOGS, "pirates", "1.log"))

    def test_merge_text(self):
        """the effective ini as text: the same values as ini_merge(), the game's lines kept"""
        base = ("; top\nname = G\nreg = A=1\n; between\nreg = B=2\nmode = 800x600 ; inline\nMode = 640x480\n"
                "dlls = d3d9\n\n[keys]\n; k\na = esc\nb = enter\n[Labels]\na = x\n")
        layers = [
            [],
            [("", "mode", "1024x768")],
            [("", "MODE", "1024x768"), ("", "reg", "C=3"), ("", "reg", "D=4")],
            [("", "reg", ""), ("", "dlls", "")],
            [("", "gamma", "1.2"), ("keys", "A", "lbutton"), ("keys", "x", "f1"), ("labels", "b", "y")],
            [("new", "k", "v"), ("", "saves", "S"), ("keys", "b", "")],
            [("", "mode", "1"), ("", "mode", "2"), ("", "modes", "1280x960")],
            [("", "nothere", "")],
        ]
        for layer in layers:
            with self.subTest(layer=layer):
                text = bw.merge_text(base, layer)
                want = bw.ini_sections(bw.ini_merge(bw.ini_parse(base), layer))
                self.assertEqual(bw.ini_sections(bw.ini_parse(text)), want, text)
                # a key the layer sets: one line of it (the base's others dropped)
                keys = [(e[0].lower(), e[1].lower()) for e in bw.ini_parse(text)]
                for sec, k, v in layer:
                    if v and not bw.is_list(sec, k):
                        self.assertEqual(keys.count((sec.lower(), k.lower())), 1, text)
                self.assertEqual([l for l in text.splitlines() if l.startswith(";")], ["; top", "; between", "; k"])
        # a base without top lines
        text = bw.merge_text("[keys]\na = b\n", [("", "mode", "1024x768")])
        self.assertEqual(bw.ini_sections(bw.ini_parse(text)), {"": {"mode": "1024x768"}, "keys": {"a": "b"}})

def pe_i386(tag=b""):
    """a file game-install takes for a 32-bit Windows DLL (MZ, PE, machine 0x14c)"""
    h = bytearray(b"MZ" + b"\0" * 0x3a + (0x40).to_bytes(4, "little"))
    h += b"PE\0\0" + (0x14c).to_bytes(2, "little") + b"\0" * 18 + tag
    return bytes(h)


def cab(name, data):
    """a cabinet (MSCF) of one file, not compressed: as cabextract reads them"""
    fname = name.encode() + b"\0"
    files_off = 36 + 8
    data_off = files_off + 16 + len(fname)
    total = data_off + 8 + len(data)
    out = b"MSCF" + (0).to_bytes(4, "little") + total.to_bytes(4, "little") + (0).to_bytes(4, "little")
    out += files_off.to_bytes(4, "little") + (0).to_bytes(4, "little") + bytes([3, 1])
    out += (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + b"\0\0" + b"\0\0" + b"\0\0"
    out += data_off.to_bytes(4, "little") + (1).to_bytes(2, "little") + (0).to_bytes(2, "little")
    out += len(data).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\0\0" + (0x5b21).to_bytes(2, "little")
    out += (0).to_bytes(2, "little") + (0x20).to_bytes(2, "little") + fname
    out += (0).to_bytes(4, "little") + len(data).to_bytes(2, "little") + len(data).to_bytes(2, "little") + data
    return out


HEAL_LOG = """bare_app: a launch of healme
err:module:import_dll Library xinput1_3.dll (which is needed by L"C:\\\\windows\\\\system32\\\\x.exe") not found
err:module:import_dll Library D3DX9_43.dll (which is needed by L"D:\\\\healme\\\\bin\\\\game.exe") not found
err:module:loader_init Importing dlls for L"D:\\\\healme\\\\bin\\\\game.exe" failed, status c0000135
fopen /games/healme/Save/slot1.sav: Read-only file system
"""


class HealTest(unittest.TestCase):
    """stage 8: game-install heal through /api/heal (a game without a recipe)"""

    def setUp(self):
        self.game = os.path.join(GAMES, "healme")
        for d in (self.game, os.path.join(GAMES, "recipes", "healme"), os.path.join(GAMES, "redist", "DirectX")):
            shutil.rmtree(d, True)
        os.makedirs(os.path.join(self.game, "bin"))
        os.makedirs(os.path.join(self.game, "Save"))
        touch(os.path.join(self.game, "bin", "game.exe"), b"MZ")
        touch(os.path.join(self.game, "wine.ini"), b"name = Heal me\nexe = bin/game.exe\nwritable = Data\n")
        os.makedirs(os.path.join(LOGS, "healme"), exist_ok=True)
        touch(os.path.join(LOGS, "healme", "1.log"), HEAL_LOG.encode())
        os.makedirs(os.path.join(GAMES, "redist", "DirectX"))
        self.dll = pe_i386(b"d3dx9_43")
        touch(os.path.join(GAMES, "redist", "DirectX", "Jun2010_d3dx9_43_x86.cab"), cab("d3dx9_43.dll", self.dll))
        touch(os.path.join(GAMES, "redist", "xinput1_3.dll"), pe_i386(b"xinput"))
        touch(os.path.join(GAMES, "redist", "x64only.dll"), pe_i386(b"")[:0x44] + (0x8664).to_bytes(2, "little"))
        self.games_json()
        del BARE_APP.lines[:]

    def tearDown(self):
        for d in (self.game, os.path.join(GAMES, "recipes"), os.path.join(GAMES, "redist", "DirectX"),
                  os.path.join(LOGS, "healme")):
            shutil.rmtree(d, True)
        for f in ("xinput1_3.dll", "x64only.dll"):
            os.remove(os.path.join(GAMES, "redist", f))

    def games_json(self, running=None):
        os.makedirs(ENV["BARE_WEB_RUN"], exist_ok=True)
        with open(os.path.join(ENV["BARE_WEB_RUN"], "games.json"), "w") as f:
            json.dump({"version": 1, "pid": os.getpid(), "running": running, "games": [
                {"folder": "healme", "name": "Heal me", "kind": "wine", "key": "0000beef", "dir": self.game},
                {"folder": "fake", "name": "Fake", "kind": "native", "key": "00000fa4",
                 "dir": os.path.join(GAMES, "fake")},
                {"folder": "homm3", "name": "Heroes", "kind": "homm3", "key": "fef6251f",
                 "dir": os.path.join(GAMES, "heroes3")}]}, f)

    def heal(self, kind, arg):
        return jreq("POST", "/api/heal/healme", {"kind": kind, "arg": arg})

    def test_suggestions(self):
        s, r = jreq("GET", "/api/heal/healme")
        self.assertEqual(s, 200, r)
        self.assertEqual([(x["kind"], x["arg"]) for x in r["suggestions"]],
                         [("dll", "D3DX9_43.dll"), ("writable", "Save/slot1.sav")])
        # without loader_init's line (required) no library; a log without them: nothing
        touch(os.path.join(LOGS, "healme", "1.log"), HEAL_LOG.replace("loader_init", "x").encode())
        self.assertEqual([x["kind"] for x in jreq("GET", "/api/heal/healme")[1]["suggestions"]], ["writable"])
        touch(os.path.join(LOGS, "healme", "1.log"), b"all well\n")
        self.assertEqual(jreq("GET", "/api/heal/healme")[1]["suggestions"], [])
        self.assertEqual(jreq("GET", "/api/heal/fake")[0], 400)
        self.assertEqual(jreq("GET", "/api/heal/homm3")[0], 400)
        self.assertEqual(jreq("GET", "/api/heal/nothere")[0], 404)

    def test_dll(self):
        n = len(card_rw_calls())
        s, r = self.heal("dll", "D3DX9_43.dll")	# the log's case; the cabinet's member in lower case
        self.assertEqual(s, 200, r)
        self.assertEqual(r["line"], "done dll bin/D3DX9_43.dll")
        self.assertEqual(open(os.path.join(self.game, "bin", "D3DX9_43.dll"), "rb").read(), self.dll)
        gi = [c[0] for c in card_rw_calls()[n:] if c[2] in ("game-install", "python3")]
        self.assertEqual(gi, ["begin", "end"])
        self.assertEqual(self.heal("dll", "d3dx9_43.dll")[0], 400)	# there already (any case)
        s, r = self.heal("dll", "xinput1_3.dll")	# a file of redist itself
        self.assertEqual(s, 200, r)
        s, r = self.heal("dll", "x64only.dll")	# 64-bit only: none
        self.assertEqual(s, 400)
        self.assertIn("redist", r["error"])
        s, r = self.heal("dll", "nothere.dll")
        self.assertEqual(s, 400)
        self.assertFalse(os.path.exists(os.path.join(self.game, "bin", "nothere.dll")))
        for bad in ("../x.dll", "a/b.dll", "x.exe", ""):
            self.assertEqual(self.heal("dll", bad)[0], 400, bad)
        self.assertEqual(sorted(os.listdir(os.path.join(self.game, "bin"))),
                         ["D3DX9_43.dll", "game.exe", "xinput1_3.dll"])
        card_rw_balanced(self, n)

    def test_writable(self):
        layer = os.path.join(GAMES, "recipes", "healme", "wine.ini")
        s, r = self.heal("writable", "Save/slot1.sav")	# not there: its directory
        self.assertEqual(s, 200, r)
        self.assertEqual(r["line"], "done writable Data Save")
        self.assertIn("reload healme", BARE_APP.lines)
        self.assertEqual([l for l in open(layer).read().splitlines() if not l.startswith(";")],
                         ["writable = Data Save"])
        mtime = os.stat(layer).st_mtime_ns
        s, r = self.heal("writable", "save\\slot2.sav")	# there already (any case, "\\"): nothing written
        self.assertEqual((s, r["line"]), (200, "done writable Data Save"))
        self.assertEqual(os.stat(layer).st_mtime_ns, mtime)
        # a layer of the player's: its other lines kept, its writable replaced
        touch(layer, b"; mine\nmode = 640x480\nwritable = Data Save\n[keys]\na = esc\n")
        touch(os.path.join(self.game, "game.cfg"), b"c")
        s, r = self.heal("writable", "GAME.CFG")
        self.assertEqual(s, 200, r)
        self.assertEqual(open(layer).read(), "; mine\nmode = 640x480\nwritable = Data Save game.cfg\n[keys]\na = esc\n")
        # a layer without writable: one line before its first section
        touch(layer, b"[keys]\na = esc\n")
        s, r = self.heal("writable", "new.ini")
        self.assertEqual(r["line"], "done writable Data new.ini")
        self.assertEqual(open(layer).read(), "writable = Data new.ini\n[keys]\na = esc\n")
        # what writable cannot say, outside the game
        for bad in ("../x", "/etc/x", "a b", "a,b", "C:\\x", ""):
            self.assertEqual(self.heal("writable", bad)[0], 400, bad)
        self.assertEqual(open(layer).read(), "writable = Data new.ini\n[keys]\na = esc\n")
        # bare_app reads the layer: it is one by ini_layer's rules
        self.assertEqual(bw.ini_sections(bw.ini_merge(bw.ini_parse(open(os.path.join(self.game, "wine.ini")).read()),
                                                      bw.ini_parse(open(layer).read(), strict=True)))[""]["writable"],
                         "Data new.ini")

    def test_writable_one_layer_change_at_a_time(self):
        """heal writable waits while the workshop changes a layer (RECIPE_LOCK
        held), then writes; dll does not wait"""
        layer = os.path.join(GAMES, "recipes", "healme", "wine.ini")
        res = []
        with bw.RECIPE_LOCK:
            t = threading.Thread(target=lambda: res.append(self.heal("writable", "Save/slot1.sav")))
            t.start()
            t.join(1.0)
            self.assertTrue(t.is_alive())
            self.assertFalse(os.path.exists(layer))
            s, r = self.heal("dll", "D3DX9_43.dll")
            self.assertEqual(s, 200, r)
        t.join(30)
        self.assertEqual(res[0][0], 200, res)
        self.assertEqual([l for l in open(layer).read().splitlines() if not l.startswith(";")],
                         ["writable = Data Save"])

    def test_refused_while_running(self):
        self.games_json(running={"folder": "healme"})
        self.assertEqual(self.heal("dll", "xinput1_3.dll")[0], 409)
        self.assertFalse(os.path.exists(os.path.join(self.game, "bin", "xinput1_3.dll")))
        self.assertEqual(jreq("POST", "/api/heal/healme", {"kind": "rm", "arg": "x"})[0], 400)
        # an install or removal running (game-install's lock): busy, nothing written
        self.games_json()
        with open(ENV["GAME_INSTALL_LOCK"], "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            for kind, arg in (("dll", "xinput1_3.dll"), ("writable", "Save")):
                s, r = self.heal(kind, arg)
                self.assertEqual((s, r["line"].split(" ")[:2]), (409, ["fail", "busy"]), r)
        self.assertFalse(os.path.exists(os.path.join(self.game, "bin", "xinput1_3.dll")))
        self.assertFalse(os.path.exists(os.path.join(GAMES, "recipes", "healme")))


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
                    # a picture of before is there: not the screen now
                    with open(path, "wb") as f:
                        f.write(b"P6\n2 2\n255\n" + bytes(12))
                    old, bw.SHOT_WAIT = bw.SHOT_WAIT, 0.5
                    try:
                        s, h, d = req("GET", "/api/shot.png")
                    finally:
                        bw.SHOT_WAIT = old
                    self.assertEqual(s, 504, d)
                    self.assertFalse(os.path.exists(path))
                    continue
                s, h, d = req("GET", "/api/shot.png")
                self.assertEqual((s, dict(h)["Content-Type"]), (200, "image/png"), d)
                from PIL import Image
                im = Image.open(io.BytesIO(d))
                self.assertEqual(im.size, (64, 32))
                want = bytes((x * 4, y * 8, 128)[c] for y in range(32) for x in range(64) for c in range(3))
                self.assertEqual(im.convert("RGB").tobytes(), want)	# every pixel as bare_app wrote it
                self.assertFalse(os.path.exists(path))	# not left in /run
                s, h, d = req("GET", "/api/shot.png?w=32")
                small = Image.open(io.BytesIO(d))
                self.assertEqual(small.size, (32, 16))	# every 2nd pixel and row
                self.assertEqual(small.convert("RGB").getpixel((5, 3)), (40, 48, 128))
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



class DeleteTest(unittest.TestCase):
    """a game deleted from the card (POST /api/game/FOLDER/delete): only its own
    folder, as a job, under card-rw, game-install's lock held meanwhile; refused
    while it runs or anything else works on the games"""

    setUp_state = RecipeTest.state

    def setUp(self):
        self.pirates = os.path.join(GAMES, "pirates")	# for games.json (RecipeTest.state)
        os.makedirs(self.pirates, exist_ok=True)
        self.setUp_state()
        del BARE_APP.lines[:]
        for f in ("state.json",):
            p = os.path.join(ENV["BARE_WEB_RUN"], f)
            if os.path.exists(p):
                os.remove(p)
        # the game: files, folders, a link to a file outside and to a folder outside
        self.top = os.path.join(GAMES, "deltest")
        self.outside = os.path.join(TOP, "outside")
        os.makedirs(os.path.join(self.outside, "dir"), exist_ok=True)
        touch(os.path.join(self.outside, "keep.txt"), b"keep")
        touch(os.path.join(self.outside, "dir", "keep2.txt"), b"keep")
        os.makedirs(os.path.join(self.top, "data", "deep", "er"))
        with open(os.path.join(self.top, "wine.ini"), "w") as f:
            f.write("name = Delete Test\nexe = game.exe\n")
        for i in range(30):
            touch(os.path.join(self.top, "data", "f%d.bin" % i), b"x" * 100)
        touch(os.path.join(self.top, "data", "deep", "er", "z.bin"), b"z")
        os.symlink(os.path.join(self.outside, "keep.txt"), os.path.join(self.top, "link-file"))
        os.symlink(os.path.join(self.outside, "dir"), os.path.join(self.top, "data", "link-dir"))
        # its layer and its saved games stay
        self.layer = os.path.join(GAMES, "recipes", "deltest", "wine.ini")
        os.makedirs(os.path.dirname(self.layer), exist_ok=True)
        touch(self.layer, b"mode = 640x480\n")
        self.mark = os.path.join(ENV["BARE_WEB_RUN"], "deleting", "deltest")
        self.saves = os.path.join(DATA, "saves-deltest", "slot1.sav")
        os.makedirs(os.path.dirname(self.saves), exist_ok=True)
        touch(self.saves, b"save")
        self.rw = len(card_rw_calls())

    def tearDown(self):
        for d in (self.top, self.outside, os.path.dirname(self.layer), os.path.dirname(self.saves)):
            if os.path.isdir(d) and not os.path.islink(d):
                for root, dirs, files in os.walk(d):
                    os.chmod(root, 0o755)
                shutil.rmtree(d)
        for p in (os.path.join(GAMES, "dellink"),):
            if os.path.lexists(p):
                os.unlink(p)
        with open(ENV["BARE_WEB_MOUNTS"], "w") as f:
            f.write("/dev/root / ext4 ro 0 0\n")

    def untouched(self):
        for p, data in ((os.path.join(self.outside, "keep.txt"), b"keep"),
                        (os.path.join(self.outside, "dir", "keep2.txt"), b"keep"),
                        (self.layer, b"mode = 640x480\n"), (self.saves, b"save")):
            with open(p, "rb") as f:
                self.assertEqual(f.read(), data, p)

    def install_lock_free(self):
        """game-install can take its lock (none holds it)"""
        fd = os.open(ENV["GAME_INSTALL_LOCK"], os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
        finally:
            os.close(fd)

    def test_delete(self):
        s, r = jreq("POST", "/api/game/deltest/delete")
        self.assertEqual(s, 200, r)
        ev = events(r["job"])
        self.assertEqual(ev[-1]["type"], "done", ev)
        self.assertIn("Delete Test", ev[-1]["text"])
        self.assertEqual([e["n"] for e in ev if e["type"] == "step"], [1, 2])
        self.assertFalse(os.path.lexists(self.top))
        self.untouched()
        card_rw_balanced(self)
        self.assertEqual([c[0] for c in card_rw_calls()[self.rw:]], ["begin", "end"])
        self.assertTrue(self.install_lock_free())
        time.sleep(0.1)
        self.assertEqual(BARE_APP.lines, ["reload deltest"])
        self.assertEqual(jreq("GET", "/api/job")[1]["job"]["kind"], "delete")
        # gone: 404, nothing written
        self.assertEqual(jreq("POST", "/api/game/deltest/delete")[0], 404)
        self.assertEqual(len(card_rw_calls()), self.rw + 2)

    def test_refused_while_it_runs(self):
        with open(os.path.join(ENV["BARE_WEB_RUN"], "state.json"), "w") as f:
            json.dump({"running": "deltest", "pid": 1, "time": int(time.time())}, f)
        s, r = jreq("POST", "/api/game/deltest/delete")
        self.assertEqual(s, 409, r)
        self.assertIn("идёт", r["error"])
        os.remove(os.path.join(ENV["BARE_WEB_RUN"], "state.json"))
        # games.json says it runs (state.json not there yet)
        self.setUp_state(running={"folder": "deltest", "key": "1", "pid": os.getpid()})
        self.assertEqual(jreq("POST", "/api/game/deltest/delete")[0], 409)
        self.assertTrue(os.path.isfile(os.path.join(self.top, "wine.ini")))
        self.assertEqual(len(card_rw_calls()), self.rw)
        self.assertFalse(os.path.lexists(self.mark))	# the refusal takes its mark back
        self.assertTrue(self.install_lock_free())

    def test_refused_while_installing(self):
        # game-install holds its lock (an install, a removal, a heal of the device's)
        fd = os.open(ENV["GAME_INSTALL_LOCK"], os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            s, r = jreq("POST", "/api/game/deltest/delete")
            self.assertEqual((s, r.get("code")), (409, "busy"), r)
            self.assertIn("ставит", r["error"])
        finally:
            os.close(fd)
        # bare-backup makes or restores a copy
        fd = os.open(ENV["BARE_WEB_BACKUP_LOCK"], os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            s, r = jreq("POST", "/api/game/deltest/delete")
            self.assertEqual((s, r.get("code")), (409, "busy"), r)
            self.assertIn("копия", r["error"])
        finally:
            os.close(fd)
        self.assertTrue(self.install_lock_free())	# the refusal let it go
        # a job of the site runs (an update held)
        upd = os.path.join(GAMES, "updates", "ogu-hold2.upd")
        make_upd(upd)
        touch(os.path.join(STATE, "hold-update"))
        try:
            s, r = jreq("POST", "/api/update/run", {"file": upd})
            self.assertEqual(s, 200)
            job = r["job"]
            s, r = jreq("POST", "/api/game/deltest/delete")
            self.assertEqual((s, r.get("code")), (409, "busy"), r)
        finally:
            os.remove(os.path.join(STATE, "hold-update"))
        self.assertEqual(events(job)[-1]["type"], "done")
        os.remove(upd)
        self.assertTrue(os.path.isfile(os.path.join(self.top, "wine.ini")))
        self.assertTrue(self.install_lock_free())

    def test_holds_install_lock(self):
        """while it deletes, game-install (the real one) says busy"""
        go = threading.Event()
        walk = bw.walk_up

        def slow(top, dev):
            for x in walk(top, dev):
                go.wait(10)
                yield x
        bw.walk_up = slow
        try:
            s, r = jreq("POST", "/api/game/deltest/delete")
            self.assertEqual(s, 200, r)
            time.sleep(0.2)
            p = subprocess.run([sys.executable, GAME_INSTALL, "remove", os.path.join(GAMES, "install", "x")],
                               capture_output=True, text=True, timeout=60)
            self.assertIn("fail busy", p.stdout, (p.stdout, p.stderr))
            # bare_app's mark: this game is being deleted, by the server's pid
            with open(self.mark) as f:
                self.assertEqual(f.read(), "%d\n" % os.getpid())
            self.assertEqual(jreq("POST", "/api/game/deltest/delete")[0], 409)	# one at a time
        finally:
            go.set()
            bw.walk_up = walk
        self.assertEqual(events(r["job"])[-1]["type"], "done")
        self.assertFalse(os.path.lexists(self.top))
        self.assertTrue(self.install_lock_free())
        self.assertFalse(os.path.lexists(self.mark))	# gone with the job

    def test_other_file_system(self):
        """a folder inside of another file system (its st_dev differs from the
        game's folder's): refused before anything is deleted"""
        real = os.lstat
        top = self.top

        def lstat(p, *a, **k):
            st = real(p, *a, **k)
            if os.fspath(p) == top:
                v = list(st)
                v[2] = st.st_dev + 1	# st_dev
                return os.stat_result(v)
            return st
        os.lstat = lstat
        try:
            s, r = jreq("POST", "/api/game/deltest/delete")
            self.assertEqual(s, 200, r)
            ev = events(r["job"])
        finally:
            os.lstat = real
        self.assertEqual(ev[-1]["type"], "fail", ev)
        self.assertIn("другая файловая система", ev[-1]["text"])
        self.assertEqual(len(os.listdir(os.path.join(self.top, "data"))), 32)	# nothing deleted
        self.assertEqual(len(card_rw_calls()), self.rw)	# the card not made writable
        self.assertTrue(self.install_lock_free())
        self.assertFalse(os.path.lexists(self.mark))

    def test_only_its_own_folder(self):
        # a link in /games to a game elsewhere: not deleted, nor what it points at
        other = os.path.join(self.outside, "game")
        os.makedirs(other)
        touch(os.path.join(other, "wine.ini"), b"name = Elsewhere\n")
        os.symlink(other, os.path.join(GAMES, "dellink"))
        s, r = jreq("POST", "/api/game/dellink/delete")
        self.assertEqual(s, 400, r)
        self.assertIn("ссылка", r["error"])
        self.assertTrue(os.path.isfile(os.path.join(other, "wine.ini")))
        # no game in it, a built-in one, names that are no folder's
        self.assertEqual(jreq("POST", "/api/game/install/delete")[0], 404)
        self.assertEqual(jreq("POST", "/api/game/heroes3/delete")[0], 400)
        self.assertEqual(jreq("POST", "/api/game/..%2Fdata/delete")[0], 400)
        self.assertEqual(jreq("POST", "/api/game/nothere/delete")[0], 404)
        # a GET changes nothing; a form of another site is refused
        self.assertNotEqual(req("GET", "/api/game/deltest/delete")[0], 200)
        self.assertEqual(req("POST", "/api/game/deltest/delete", b"", page=False,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 403)
        self.assertTrue(os.path.isfile(os.path.join(self.top, "wine.ini")))
        self.assertEqual(len(card_rw_calls()), self.rw)
        self.untouched()

    def test_mount_inside(self):
        with open(ENV["BARE_WEB_MOUNTS"], "w") as f:
            f.write("/dev/root / ext4 ro 0 0\n/dev/sdz1 %s vfat rw 0 0\n" %
                    os.path.join(os.path.realpath(self.top), "data", "deep").replace(" ", "\\040"))
        s, r = jreq("POST", "/api/game/deltest/delete")
        self.assertEqual(s, 409, r)
        self.assertIn("смонтирован", r["error"])
        self.assertTrue(os.path.isfile(os.path.join(self.top, "data", "deep", "er", "z.bin")))
        self.assertEqual(len(card_rw_calls()), self.rw)

    def test_fails_midway(self):
        """a file that cannot be removed: the job fails saying so, the card's
        writer ends, the lock goes, bare_app reloads what is left"""
        os.chmod(os.path.join(self.top, "data", "deep"), 0o555)
        s, r = jreq("POST", "/api/game/deltest/delete")
        self.assertEqual(s, 200, r)
        ev = events(r["job"])
        self.assertEqual(ev[-1]["type"], "fail", ev)
        self.assertIn("не до конца", ev[-1]["text"])
        self.assertTrue(os.path.isdir(os.path.join(self.top, "data", "deep", "er")))	# its folder could not go
        card_rw_balanced(self)
        self.assertTrue(self.install_lock_free())
        time.sleep(0.1)
        self.assertEqual(BARE_APP.lines, ["reload deltest"])
        self.untouched()


if __name__ == "__main__":
    unittest.main()
