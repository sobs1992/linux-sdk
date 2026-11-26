"""
bare-web (/usr/sbin/bare-web starts it): the device in a browser of the
computer on its USB cable (docs/web-service-plan.md): games installed from
what the computer has, their launch logs and the reports read, the system
updated. One HTTP server (port 80), its pages in /usr/share/bare-web, a
JSON API under /api; what takes long (an installation, an update) is a job
whose lines come as server-sent events. Only the USB network's computer
(<net>.1, /usr/sbin/unit net) and the device itself are answered: no
password (Wi-Fi is later, with a PIN on the screen).

  GET  /api/status                 the system (/etc/sdk-release), the A/B
                                   state, room on /games and /data, the
                                   battery, the unit, the card, the job
  PUT  /api/upload/PLACE/NAME      the body into /games/PLACE/NAME (PLACE
                                   install, redist or updates; NAME no "/",
                                   "..", not hidden): written as NAME.part,
                                   renamed once whole; 503 without the card
                                   or while it is the computer's USB disk
  GET  /api/files/PLACE            the files there (name, size, part)
  DELETE /api/files/PLACE/NAME     an update file or a .part left over
  GET  /api/install/scan           game-install scan, an object per entry
  POST /api/install/run            {path, replace, exe, title}: a job of
                                   game-install install
  POST /api/install/remove         {path}: game-install remove
  GET  /api/games                  the games on the card (wine.ini,
                                   game.ini) and the built-in ones: size,
                                   last launch, logs, running, the keys of
                                   their layer (layer_keys: 0 none, null broken)
  GET  /api/logs/GAME/N            /data/logs/GAME/N.log (N 1..3)
  POST /api/report                 {game}: bare-report [GAME]; {where, name} of
                                   the report it wrote (GET /api/reports/... then)
  GET  /api/reports                the reports on the card and in /data
  GET|DELETE /api/reports/WHERE/NAME   one of them (WHERE card or data)
  GET  /api/update/files           the .upd files (/games/updates, /games,
                                   /data/updates) with their update.ini
  GET  /api/update/info?file=F     system-update --info F
  POST /api/update/run             {file}: a job of system-update
  GET  /api/update/state           ab-state and both slots' versions
  POST /api/update/switch          the spare system from the next start
                                   (ab-state try), then the restart
  POST /api/reboot                 the restart
  GET  /api/saves                  bare-backup list: the games' data, the copies
                                   on the card and in /data
  POST /api/saves/backup           {game: FOLDER|all}: a copy made (bare-backup
                                   backup); {where, name, size} (GET .../copy/ then)
  GET|DELETE /api/saves/copy/WHERE/NAME   one of the copies (WHERE card, data)
  PUT  /api/saves/upload/NAME      a copy from the computer into /data/backups
  POST /api/saves/info             {where, name}: its manifest (bare-backup info)
  POST /api/saves/restore          {where, name, game}: bare-backup restore;
                                   409 while the game runs
  GET  /api/schema                 the keys of wine.ini and game.ini (schema.json),
                                   bare_app_wine --actions and --defaults
  GET  /api/recipe/FOLDER          the game's recipe: base (its ini), layer (the
                                   player's changes, /games/recipes/FOLDER), the
                                   effective ini (bare_app's merge), defaults,
                                   the player's own buttons and options
  PUT  /api/recipe/FOLDER/layer    {sections: {...}} or ini text: the layer
                                   written with only what differs from the
                                   game's ini, then FIFO "reload FOLDER"
  DELETE /api/recipe/FOLDER/layer  the layer removed, "reload"
  POST /api/recipe/FOLDER/adopt-controls  the player's buttons (controls.<key>)
                                   into the layer's [keys] and [labels], then
                                   dropped from bare_app.conf (import-settings)
  POST /api/recipe/FOLDER/export   a zip of a recipe made of the game for the SDK
                                   (scripts/recipe-import.py): games/FOLDER/overlay/
                                   wine.ini (the effective one: the game's with
                                   the layer), cover.png, README.md, manifest.section,
                                   needs.txt, logs/1.log
  GET  /api/heal/FOLDER            what game-install heal can do for the game's last
                                   launch (1.log by errors.ini's rules wine-missing-dll,
                                   card-read-only): [{kind dll|writable, arg, text}]
  POST /api/heal/FOLDER            {kind, arg}: game-install heal FOLDER KIND ARG
                                   (writable: then FIFO "reload FOLDER"); 409 while it runs
  GET  /api/state                  state.json of bare_app: the game running, its
                                   frames a second, CPU, GPU, memory
  POST /api/game/FOLDER/launch|quit|options   FIFO launch, quit-game, options
                                   (launch: 409 while another game runs)
  POST /api/game/FOLDER/delete     a job: the game's folder /games/FOLDER (a
                                   folder of its own on the card, not a link,
                                   with its wine.ini or game.ini) removed, then
                                   FIFO "reload FOLDER"; its layer (/games/
                                   recipes) and saved games (/data) stay; 409
                                   while it runs, a job runs, game-install or
                                   bare-backup holds its lock (the delete holds
                                   game-install's while it runs, and marks
                                   <run>/deleting/FOLDER with its pid: bare_app
                                   does not start the game meanwhile)
  GET  /api/shot.png[?w=W]         the screen now (SIGUSR1, bare_app's PPM)
  POST /api/pad                    {button, down}: FIFO press/release
  POST /api/stick                  {stick, x, y, ms}: the stick held there
  POST /api/stream                 {on: true|false}: FIFO "stream on|off" (bare_app's
                                   stream for a while: it stops a minute after its
                                   last player, or once nobody plays after off)
  GET  /api/stream.ts              the stream as MPEG-TS (H.264, Layer II sound):
                                   bare_app's http://127.0.0.1:8554/live.ts passed
                                   on as it comes (bare_app answers that GET from
                                   127.0.0.1 only, so the PIN is not passed by);
                                   waits up to 4 s for a stream just asked for,
                                   else 503; ends when either side closes
  GET  /api/logs/GAME/live         1.log as it grows (text/event-stream)
  GET  /api/job                    the job running or the last one
  GET  /api/job/ID/events          its lines (text/event-stream)

One job at a time (409 otherwise); game-install takes its own lock too
(/run/game-install.lock), so the device's install screen and this one do
not run two installs: "fail busy". The card is read-only: made writable
while anyone writes on it by /usr/sbin/card-rw (one count of all its
writers: this server, game-install, bare-report, bare-backup), read-only
again after the last one, unless it was writable before.

Who is answered: a Host that is one of the device's addresses (ip -o -4
addr, <net>.2, 127.0.0.1), else 421 (a name of another site resolving here);
an Origin, if sent, of the same Host; a request other than GET or HEAD
without Origin only with "X-Requested-With: bare-web" (app.js sends it) or
as application/json, else 403 (a form or an image of another site). No GET
changes anything; a JSON body is read only when sent as application/json.
The USB computer (<net>.*) and the device itself (127.0.0.1) as they are;
any other address (Wi-Fi) only with a session of the PIN: until then a
page (GET not under /api) is the page asking for the PIN (401), POST
/api/pin {pin} the only request, anything else 401. The PIN is six digits
in /data/bare-web.pin, written by bare_app (Settings, System, "The device
in a browser"), read at every check: a new PIN ends every session of the
old one. A right PIN gives a random cookie (HttpOnly, SameSite=Strict) for
24 h (the sessions are this process's: a restart asks again); after 5
wrong ones in a row from an address no PIN is taken from it for 60 s (counted
per client address, so no one in the same network keeps the PIN closed for
the others; at most 64 addresses kept, the longest untouched one dropped).

  POST /api/pin                    {pin}: the session cookie; 403 wrong, 429 a
                                   pause, 503 no PIN yet

Tests (scripts/test-bare-web.py) name other places: BARE_WEB_GAMES (then
the card is that directory as it is: no mount test),
BARE_WEB_DATA, BARE_WEB_LOGS, BARE_WEB_STATIC, BARE_WEB_LOG (the server's
log), BARE_WEB_POWER (/sys/class/power_supply), BARE_WEB_RELEASE, the
programs BARE_WEB_GAME_INSTALL, BARE_WEB_BARE_REPORT, BARE_WEB_SYSTEM_UPDATE,
BARE_WEB_AB_STATE, BARE_WEB_USB_DISK, BARE_WEB_UNIT, BARE_WEB_REBOOT,
BARE_WEB_UPDATE_LOCK, BARE_WEB_BARE_BACKUP, and BARE_WEB_NET (the network answered), BARE_WEB_PORT,
BARE_WEB_BIND, BARE_WEB_CARD_RW (card-rw), BARE_WEB_IP (ip); of bare_app BARE_WEB_RUN (games.json, state.json, ini/), BARE_WEB_CONF,
BARE_WEB_CTL (its FIFO), BARE_WEB_WINE (bare_app_wine), BARE_WEB_SHOT, BARE_WEB_NATIVE_DIRS,
BARE_WEB_SYS_INPUT and BARE_WEB_DEV_INPUT (the sticks), BARE_WEB_ERRORS (errors.ini),
BARE_WEB_INSTALL_LOCK and BARE_WEB_BACKUP_LOCK (game-install's and bare-backup's locks),
BARE_WEB_MOUNTS (/proc/mounts), BARE_WEB_STREAM (the port of bare_app's stream on
127.0.0.1). A test names all of them (but PORT,
BIND, NET) or none: one of them set and not all is refused at the start, never the device's
own place for the rest.
"""
import errno
import fcntl
import hashlib
import http.server
import io
import json
import os
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import zipfile
import zlib

E = os.environ.get
# a test names every place and program (all of them or none: a test never falls
# back to the device's own); PORT, BIND, NET are no places, THP and LIB the
# launcher's (/usr/sbin/bare-web)
HOOKS = ("BARE_WEB_GAMES", "BARE_WEB_DATA", "BARE_WEB_LOGS", "BARE_WEB_STATIC", "BARE_WEB_LOG",
         "BARE_WEB_POWER", "BARE_WEB_RELEASE", "BARE_WEB_GAME_INSTALL", "BARE_WEB_BARE_REPORT",
         "BARE_WEB_SYSTEM_UPDATE", "BARE_WEB_AB_STATE", "BARE_WEB_USB_DISK", "BARE_WEB_UNIT",
         "BARE_WEB_REBOOT", "BARE_WEB_BARE_BACKUP", "BARE_WEB_UPDATE_LOCK", "BARE_WEB_RUN",
         "BARE_WEB_CONF", "BARE_WEB_CTL", "BARE_WEB_WINE", "BARE_WEB_SHOT", "BARE_WEB_SYS_INPUT",
         "BARE_WEB_DEV_INPUT", "BARE_WEB_NATIVE_DIRS", "BARE_WEB_CARD_RW", "BARE_WEB_IP",
         "BARE_WEB_ERRORS", "BARE_WEB_INSTALL_LOCK", "BARE_WEB_BACKUP_LOCK", "BARE_WEB_MOUNTS",
         "BARE_WEB_STREAM")
NOT_HOOKS = ("BARE_WEB_PORT", "BARE_WEB_BIND", "BARE_WEB_NET", "BARE_WEB_THP", "BARE_WEB_LIB")
TEST = any(k.startswith("BARE_WEB_") and k not in NOT_HOOKS for k in os.environ)
if TEST:
    _missing = [k for k in HOOKS if not E(k)]
    _unknown = [k for k in os.environ if k.startswith("BARE_WEB_") and k not in HOOKS + NOT_HOOKS]
    if _missing or _unknown:
        sys.exit("bare-web: test hooks %s: refused" % "; ".join(
            (["without " + ", ".join(_missing)] if _missing else []) +
            (["unknown " + ", ".join(_unknown)] if _unknown else [])))
GAMES = E("BARE_WEB_GAMES", "/games")
DATA = E("BARE_WEB_DATA", "/data")
LOGS = E("BARE_WEB_LOGS", os.path.join(DATA, "logs"))
STATIC = E("BARE_WEB_STATIC", "/usr/share/bare-web")
LOG = E("BARE_WEB_LOG", "/var/log/bare-web.log")
POWER = E("BARE_WEB_POWER", "/sys/class/power_supply")
RELEASE = E("BARE_WEB_RELEASE", "/etc/sdk-release")
GAME_INSTALL = E("BARE_WEB_GAME_INSTALL", "/usr/bin/game-install")
BARE_REPORT = E("BARE_WEB_BARE_REPORT", "/usr/sbin/bare-report")
SYSTEM_UPDATE = E("BARE_WEB_SYSTEM_UPDATE", "/usr/sbin/system-update")
AB_STATE = E("BARE_WEB_AB_STATE", "/usr/sbin/ab-state")
USB_DISK = E("BARE_WEB_USB_DISK", "/usr/sbin/usb-disk")
UNIT = E("BARE_WEB_UNIT", "/usr/sbin/unit")
REBOOT = E("BARE_WEB_REBOOT", "/sbin/reboot")
BARE_BACKUP = E("BARE_WEB_BARE_BACKUP", "/usr/sbin/bare-backup")
CARD_RW = E("BARE_WEB_CARD_RW", "/usr/sbin/card-rw")	# the one count of the card's writers
IP = E("BARE_WEB_IP", "/sbin/ip")	# the device's addresses (ip -o -4 addr)
SAVES_NAME = re.compile(r"^saves-[^/\\]+\.zip$")
SAVES_MAX = 4 << 30	# a copy uploaded: at most this
UPDATE_LOCK = E("BARE_WEB_UPDATE_LOCK", "/run/system-update.lock")	# system-update's own
INSTALL_LOCK = E("BARE_WEB_INSTALL_LOCK", "/run/game-install.lock")	# game-install's own
BACKUP_LOCK = E("BARE_WEB_BACKUP_LOCK", "/run/bare-backup.lock")	# bare-backup's own
MOUNTS = E("BARE_WEB_MOUNTS", "/proc/mounts")
PLACES = ("install", "redist", "updates")
CHUNK = 1 << 20
ROOM_LEFT = 16 << 20	# what an upload leaves free on the card
# the built-in games: their logs' name, their folder, their name
BUILT_IN = (("homm3", "heroes3", "Heroes of Might and Magic III"),
            ("halflife", "halflife", "Half-Life"),
            ("doom", "doom", "DOOM"))



class Log:
    """the server's log, LOG: 256 KB at most, the one before as LOG.1 (not
    the logging module: 2.5 MB of the device's memory)"""
    LIMIT = 256 << 10

    def __init__(self):
        self.lock = threading.Lock()
        self.path = None

    def put(self, level, msg, *args):
        line = "%s %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, msg % args if args else msg)
        with self.lock:
            if not self.path:
                sys.stderr.write(line)
                return
            try:
                if os.path.getsize(self.path) > self.LIMIT:
                    os.replace(self.path, self.path + ".1")
            except OSError:
                pass
            try:
                with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(line)
            except OSError:
                sys.stderr.write(line)

    def info(self, msg, *args):
        self.put("INFO", msg, *args)

    def warning(self, msg, *args):
        self.put("WARNING", msg, *args)

    def error(self, msg, *args):
        self.put("ERROR", msg, *args)

    def exception(self, msg, *args):
        import traceback
        self.put("ERROR", msg + "\n" + traceback.format_exc().rstrip(), *args)


log = Log()

# What game-install's "fail CODE ARG" and "step N/M NAME" say, in the words
# of the device's install screen: the same as bare_app's
# apps/bare_app/src/gui/view/core/i18n.c (S_INST_ERR_*, S_INST_STEP_*,
# S_INST_FAILED_FMT): a change there is made here too.
INSTALL_FAIL = {
    "gone": "её папки или программы больше нет в папке install.",
    "unknown": "приставка не знает эту игру, выберите её программу.",
    "exists": "на карте уже есть папка %s (другая игра или старая копия этой).",
    "room": "на карте игр не хватает места, игре нужно %s МБ.",
    "card": "на карту игр не удаётся записать. Возможно, она повреждена: проверьте её на компьютере.",
    "setup": "установщик не удалось распаковать: он повреждён или скопированы не все его файлы .bin.",
    "busy": "сейчас уже идёт установка или удаление другой игры (на экране приставки или в "
            "браузере), дождитесь её окончания.",
}
INSTALL_FAILED = "Не удалось установить игру: %s"
REMOVE_FAILED = "Не удалось удалить: %s"
INSTALL_STEP = {
    "find": "поиск игры", "unpack": "распаковка установщика", "files": "перенос файлов",
    "extras": "настройки для приставки", "cover": "обложка", "prepare": "подготовка игры",
    "data": "файлы в памяти приставки", "finish": "последние шаги",
}
# the update screen's (S_UPD_STEP_*)
UPDATE_STEP = {
    "check": "проверка файла", "verify": "проверка целостности", "format": "подготовка раздела",
    "unpack": "распаковка системы", "keep": "перенос настроек", "boot": "последние шаги",
}
NO_CARD = "Карты игр нет в приставке. Вставьте её и подождите несколько секунд."
USB_DISK_ON = ("Карта игр сейчас отдана компьютеру как USB-диск. Отключите «USB-диск» на "
               "приставке (или извлеките диск на компьютере), потом повторите.")


def run(argv, timeout=60):
    """argv's exit status and output (stdout, stderr); 127 if it is not there"""
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def safe_name(n):
    """a file's own name: no directory in it, not hidden, no control
    characters"""
    return (bool(n) and len(n.encode()) <= 255 and "/" not in n and "\\" not in n and
            ".." not in n and not n.startswith(".") and not any(ord(c) < 32 for c in n))


EXFAT_BAD = set(':?<>"|*\\')
NAME_BAD = "Имя «%s» не подходит: на карте нельзя знаки : ? < > \" | * \\, управляющие и точку или пробел в конце."


def card_name_ok(n):
    """a file's own name the card (exFAT, and Windows reading it) can have"""
    return (safe_name(n) and not any(c in EXFAT_BAD or ord(c) < 32 or ord(c) == 127 for c in n) and
            not n.endswith((".", " ")))


def kv(text):
    """the "name=value" lines of text"""
    out = {}
    for line in text.splitlines():
        k, eq, v = line.partition("=")
        if eq and k.strip():
            out[k.strip()] = v.strip()
    return out


def read(path, limit=1 << 16):
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


# ---- the card ---------------------------------------------------------------

def card_opts():
    """the mount options of /games, None if it is not a mount point"""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                p = line.split()
                if len(p) > 3 and p[1] == GAMES:
                    return p[3].split(",")
    except OSError:
        pass
    return None


def usb_disk_shared():
    """the card is the computer's USB disk now (usb-disk status: 1 not shared)"""
    if TEST and "BARE_WEB_USB_DISK" not in os.environ:
        return False
    rc, _, _ = run([USB_DISK, "status"], timeout=10)
    return rc not in (1, 127)


def card_mounted():
    return os.path.isdir(GAMES) if TEST else os.path.ismount(GAMES)


def card_problem():
    """why nothing can be written onto the card now (a text for the page),
    None: it can"""
    if usb_disk_shared():
        return USB_DISK_ON
    if not card_mounted():
        return NO_CARD
    return None


class CardError(Exception):
    pass


class CardWriting:
    """with CardWriting(): the card writable inside. card-rw keeps one count of
    all the card's writers (this server, game-install, bare-report, bare-backup,
    by their pids): the first one makes it writable, the last one read-only
    again (unless it was writable before); every begin here has its end, an
    exception inside too"""

    def __enter__(self):
        rc, _, err = run([CARD_RW, "begin", str(os.getpid())], timeout=60)
        if rc:
            log.warning("card-rw begin: %s", err.strip() or "exit %d" % rc)
            raise CardError(NO_CARD if rc == 3 else INSTALL_FAIL["card"])
        return self

    def __exit__(self, *exc):
        os.sync()
        rc, _, err = run([CARD_RW, "end", str(os.getpid())], timeout=60)
        if rc or err.strip():
            log.warning("card-rw end: %s", err.strip() or "exit %d" % rc)
        return False


# ---- jobs -------------------------------------------------------------------

class Job:
    """an installation or an update: its lines as events, the last one done
    or fail"""
    seq = 0

    def __init__(self, kind, title):
        Job.seq += 1
        self.id = Job.seq
        self.kind = kind
        self.title = title
        self.events = []
        self.ended = False
        self.started = time.time()
        self.cond = threading.Condition()

    def emit(self, type_, **data):
        with self.cond:
            if self.ended:
                return
            data["type"] = type_
            self.events.append(data)
            if type_ in ("done", "fail"):
                self.ended = True
            self.cond.notify_all()

    def summary(self):
        with self.cond:
            return {"id": self.id, "kind": self.kind, "title": self.title, "ended": self.ended,
                    "started": int(self.started), "events": list(self.events)}


class Jobs:
    lock = threading.Lock()
    current = None

    @classmethod
    def start(cls, kind, title, work):
        """work(job) in a thread of its own; None if a job runs already"""
        with cls.lock:
            if cls.current and not cls.current.ended:
                return None
            job = cls.current = Job(kind, title)

        def body():
            try:
                work(job)
            except Exception as e:  # noqa: BLE001: the job ends whatever happened
                log.exception("job %d", job.id)
                job.emit("fail", code="error", arg=str(e), text=str(e))
            job.emit("fail", code="error", arg="", text="задание закончилось без результата")
        threading.Thread(target=body, daemon=True).start()
        return job

    @classmethod
    def running(cls, kind=None):
        with cls.lock:
            j = cls.current
            return bool(j and not j.ended and (kind is None or j.kind == kind))


def lines_of(argv, job, stderr_tail):
    """argv run, its stdout's lines given back one by one; its stderr's last
    lines into stderr_tail; the exit status at the end (None while it runs)"""
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)

    def errors():
        for raw in p.stderr:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            log.info("%s: %s", os.path.basename(argv[0]), line)
            stderr_tail.append(line)
            del stderr_tail[:-20]
    t = threading.Thread(target=errors, daemon=True)
    t.start()
    for raw in p.stdout:
        yield raw.decode("utf-8", "replace").rstrip("\n")
    rc = p.wait()
    t.join(5)
    p.stdout.close()
    p.stderr.close()
    yield rc


def install_text(code, arg, removing=False):
    why = INSTALL_FAIL.get(code)
    if why is None:
        why = arg or code
    elif "%s" in why:
        why = why % arg
    return (REMOVE_FAILED if removing else INSTALL_FAILED) % why


def install_work(argv):
    def work(job):
        err = []
        for line in lines_of(argv, job, err):
            if isinstance(line, int):
                if line == 0:
                    job.emit("done", folder="", title=job.title, text="Готово.")
                else:
                    msg = err[-1] if err else "код выхода %d" % line
                    job.emit("fail", code="error", arg=msg, text=install_text("error", msg))
                return
            log.info("game-install: %s", line)
            try:
                install_line(job, line.split(" ", 2))
            except (ValueError, IndexError):
                log.warning("game-install said %r", line)
    return work


def install_line(job, w):
    """one line of game-install's (its words split: w)"""
    if w[0] == "step" and len(w) == 3 and "/" in w[1]:
        n, _, m = w[1].partition("/")
        job.emit("step", n=int(n), m=int(m), name=w[2], text=INSTALL_STEP.get(w[2], w[2]))
    elif w[0] == "progress" and len(w) >= 2:
        job.emit("progress", percent=int(w[1]))
    elif w[0] == "skip" and len(w) >= 2:
        job.emit("skip", what=w[1], arg=w[2] if len(w) > 2 else "")
    elif w[0] == "done":
        folder = w[1] if len(w) > 1 else ""
        title = w[2] if len(w) > 2 else folder
        job.emit("done", folder=folder, title=title,
                 text="Игра «%s» установлена и появилась на главном экране." % title)
    elif w[0] == "fail":
        code = w[1] if len(w) > 1 else "error"
        arg = w[2] if len(w) > 2 else ""
        job.emit("fail", code=code, arg=arg, text=install_text(code, arg))


def update_work(path):
    def work(job):
        err = []
        for line in lines_of([SYSTEM_UPDATE, path], job, err):
            if isinstance(line, int):
                if line == 0:
                    job.emit("done", version="", text="Обновление установлено. Оно заработает после "
                             "перезагрузки.")
                else:
                    msg = err[-1] if err else "код выхода %d" % line
                    if msg.startswith("system-update: "):
                        msg = msg[15:]
                    job.emit("fail", code="error", arg=msg, text="Не удалось установить обновление: %s" % msg)
                return
            log.info("system-update: %s", line)
            try:
                update_line(job, line.split(" ", 2))
            except (ValueError, IndexError):
                log.warning("system-update said %r", line)
    return work


def update_line(job, w):
    """one line of system-update's (its words split: w)"""
    if w[0] == "step" and len(w) == 3 and "/" in w[1]:
        n, _, m = w[1].partition("/")
        job.emit("step", n=int(n), m=int(m), name=w[2], text=UPDATE_STEP.get(w[2], w[2]))
    elif w[0] == "progress" and len(w) >= 2:
        job.emit("progress", percent=int(w[1]))
    elif w[0] == "done":
        v = " ".join(w[1:])	# "<built> <SDK commit>": a space in it
        job.emit("done", version=v, text="Обновление %s установлено. Оно заработает после "
                 "перезагрузки." % v)


# ---- what the pages show ----------------------------------------------------

def df(path):
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return {"total_mb": (st.f_blocks * st.f_frsize) >> 20, "free_mb": (st.f_bavail * st.f_frsize) >> 20}


def battery():
    out = {}
    try:
        names = sorted(os.listdir(POWER))
    except OSError:
        return out
    for n in names:
        u = kv((read(os.path.join(POWER, n, "uevent")) or "").replace("POWER_SUPPLY_", ""))
        if u.get("TYPE") == "Battery":
            for k in ("CAPACITY", "STATUS", "VOLTAGE_NOW", "CURRENT_NOW"):
                if k in u:
                    out[k.lower()] = int(u[k]) if u[k].lstrip("-").isdigit() else u[k]
        elif u.get("ONLINE") == "1" or (u.get("TYPE") in ("USB", "Mains") and u.get("PRESENT") == "1" and
                                        u.get("ONLINE") is None):
            out["external"] = True
    return out


def ab_state():
    rc, out, _ = run([AB_STATE], timeout=10)
    return kv(out) if rc == 0 else {}


def status():
    opts = card_opts()
    _, label, _ = run([UNIT, "label"], timeout=5)
    j = Jobs.current
    return {
        "release": kv(read(RELEASE) or ""),
        "ab": ab_state(),
        "unit": label.strip(),
        "card": {"mounted": card_mounted(), "usb_disk": usb_disk_shared(),
                 "rw": bool(opts and "rw" in opts), "room": df(GAMES) if card_mounted() else None},
        "data": df(DATA),
        "battery": battery(),
        "job": j.summary() if j else None,
    }


def ini_name(path):
    """name = of a wine.ini or game.ini"""
    for line in (read(path) or "").splitlines():
        k, eq, v = line.partition("=")
        if eq and k.strip() == "name":
            return v.strip()
    return None


SIZES = {}	# folder: bytes, worked out in the background
SIZES_LOCK = threading.Lock()
SIZING = set()


def tree_size(top):
    n = 0
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            n += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return n


def size_later(folders):
    with SIZES_LOCK:
        todo = [f for f in folders if f not in SIZES and f not in SIZING]
        SIZING.update(todo)
    if not todo:
        return

    def body():
        for f in todo:
            s = tree_size(os.path.join(GAMES, f))
            with SIZES_LOCK:
                SIZES[f] = s
                SIZING.discard(f)
    threading.Thread(target=body, daemon=True).start()


def forget_sizes():
    with SIZES_LOCK:
        SIZES.clear()


def logs_of(game):
    out = []
    for n in (1, 2, 3):
        try:
            st = os.stat(os.path.join(LOGS, game, "%d.log" % n))
            out.append({"n": n, "size": st.st_size, "time": int(st.st_mtime)})
        except OSError:
            pass
    return out


def games():
    found = {}
    try:
        names = sorted(os.listdir(GAMES)) if card_mounted() else []
    except OSError:
        names = []
    for f in names:
        p = os.path.join(GAMES, f)
        if f.startswith(".") or not os.path.isdir(p):
            continue
        for ini in ("wine.ini", "game.ini"):
            if os.path.isfile(os.path.join(p, ini)):
                found[f] = {"id": f, "folder": f, "name": ini_name(os.path.join(p, ini)) or f, "kind": ini}
                break
    for gid, folder, name in BUILT_IN:
        if gid in found:
            continue
        if os.path.isdir(os.path.join(LOGS, gid)) or (card_mounted() and os.path.isdir(os.path.join(GAMES, folder))):
            found[gid] = {"id": gid, "folder": folder if os.path.isdir(os.path.join(GAMES, folder)) else None,
                          "name": name, "kind": "built-in"}
    folders = [g["folder"] for g in found.values() if g["folder"]]
    size_later(folders)
    with SIZES_LOCK:
        for g in found.values():
            g["size"] = SIZES.get(g["folder"]) if g["folder"] else None
    now = running_game()
    for g in found.values():
        g["logs"] = logs_of(g["id"])
        g["last"] = g["logs"][0]["time"] if g["logs"] and g["logs"][0]["n"] == 1 else None
        g["running"] = bool(now) and now in (g["folder"], g["id"])
        g["layer_keys"] = layer_keys(g)
    return sorted(found.values(), key=lambda g: (-(g["last"] or 0), g["name"].lower()))


def layer_keys(g):
    """the keys of a game's layer (/games/recipes/FOLDER/wine.ini or game.ini),
    for the workshop's list: each (section, key) once (a repeated one, reg or
    writable, is one key); 0 none (no file, an empty one), None a layer that
    does not read"""
    ini = {"wine.ini": "wine.ini", "game.ini": "game.ini"}.get(g["kind"])
    if not ini or not g["folder"]:
        return 0
    p = os.path.join(GAMES, "recipes", g["folder"], ini)
    if os.path.islink(p) or not os.path.isfile(p):
        return 0
    try:
        return len({(e[0], e[1]) for e in ini_parse(read(p, 1 << 20) or "", strict=True)})
    except IniError:
        return None


def scan():
    rc, out, err = run([GAME_INSTALL, "scan", os.path.join(GAMES, "install")], timeout=300)
    entries = {}
    order = []
    for line in out.splitlines():
        f = line.split("\t")
        if f[0] == "entry" and len(f) >= 7:
            entries[f[1]] = {"path": f[1], "name": os.path.basename(f[1]), "kind": f[2],
                             "recipe": None if f[3] == "-" else f[3], "title": f[4], "game": f[5],
                             "state": f[6], "need": [], "exe": [], "size_mb": None}
            order.append(f[1])
        elif f[0] in ("need", "exe") and len(f) >= 3 and f[1] in entries:
            entries[f[1]][f[0]] = [x for x in f[2].split("|") if x]
        elif f[0] == "size" and len(f) >= 3 and f[1] in entries and f[2].isdigit():
            entries[f[1]]["size_mb"] = int(f[2])
    return {"ok": rc == 0, "error": err.strip().splitlines()[-1] if rc and err.strip() else None,
            "entries": [entries[p] for p in order]}


def files(place):
    d = os.path.join(GAMES, place)
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.startswith(".") or not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat(follow_symlinks=False)
                out.append({"name": e.name, "size": st.st_size, "time": int(st.st_mtime),
                            "part": e.name.endswith(".part")})
    except OSError:
        pass
    return sorted(out, key=lambda x: x["name"].lower())


REPORT_DIRS = {"card": lambda: os.path.join(GAMES, "reports"), "data": lambda: os.path.join(DATA, "reports")}
# where bare-backup keeps the copies of saved games (its CARD_BACKUPS, DATA_BACKUPS)
SAVES_DIRS = {"card": os.path.join(GAMES, "backups"), "data": os.path.join(DATA, "backups")}


def reports():
    out = []
    for where, d in REPORT_DIRS.items():
        try:
            with os.scandir(d()) as it:
                for e in it:
                    if e.name.endswith(".txt") and safe_name(e.name) and e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        out.append({"where": where, "name": e.name, "size": st.st_size, "time": int(st.st_mtime)})
        except OSError:
            pass
    return sorted(out, key=lambda r: -r["time"])


def update_dirs():
    return [os.path.join(GAMES, "updates"), GAMES, os.path.join(DATA, "updates")]


def update_ini(path):
    """the update.ini an update file starts with (its first tar member)"""
    try:
        with open(path, "rb") as f:
            hdr = f.read(512)
            if len(hdr) < 512 or hdr[:100].rstrip(b"\0") != b"update.ini":
                return None
            n = int(hdr[124:136].rstrip(b"\0 ") or b"0", 8)
            if n > 4096:
                return None
            return f.read(n).decode("utf-8", "replace")
    except (OSError, ValueError):
        return None


def update_files():
    mine = kv(read(RELEASE) or "").get("FIRMWARE", "")
    out = []
    for d in update_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if not n.endswith(".upd") or n.startswith(".") or not os.path.isfile(p):
                continue
            ini = kv(update_ini(p) or "")
            out.append({"path": p, "name": n, "size": os.path.getsize(p), "version": ini.get("VERSION"),
                        "firmware": ini.get("FIRMWARE"), "fits": bool(ini) and ini.get("FIRMWARE") == mine,
                        "removable": d == os.path.join(GAMES, "updates") or d == os.path.join(DATA, "updates")})
    return sorted(out, key=lambda u: u["version"] or "", reverse=True)


def update_file_ok(path):
    """path is an update file of the places the update screen looks in"""
    return (isinstance(path, str) and path.endswith(".upd") and safe_name(os.path.basename(path)) and
            os.path.dirname(path) in update_dirs() and os.path.isfile(path))


def update_state():
    st = ab_state()
    out = {"ab": st, "versions": {}}
    # not while system-update writes the other slot: ab-state would mount it
    busy = Jobs.running("update") or os.path.exists(UPDATE_LOCK)
    for s in ("a", "b"):
        if s != st.get("running") and busy:
            out["versions"][s] = None
            continue
        rc, v, _ = run([AB_STATE, "version", s], timeout=30)
        out["versions"][s] = (v.strip() or None) if rc == 0 else None	# None: no system there
    out["busy"] = busy
    return out


# ---- HTTP -------------------------------------------------------------------

# ---- bare_app: games.json, state.json, its FIFO (stages 4 and 5) ----------------

def hook(name, default):
    """a place a test names; in a test a place it does not name is none
    (never the device's own)"""
    v = E(name)
    if v is not None:
        return v
    return None if TEST else default


RUN = hook("BARE_WEB_RUN", "/run/bare_app")
CONF = hook("BARE_WEB_CONF", "/etc/bare_app.conf")
CTL = hook("BARE_WEB_CTL", "/tmp/bare_app.ctl")
WINE = hook("BARE_WEB_WINE", "/usr/bin/bare_app_wine")
SHOT = E("BARE_WEB_SHOT")	# else what bare_app's environment says (shot_path())
SYS_INPUT = hook("BARE_WEB_SYS_INPUT", "/sys/class/input")
DEV_INPUT = hook("BARE_WEB_DEV_INPUT", "/dev/input")
ERRORS = hook("BARE_WEB_ERRORS", "/usr/share/bare_app/errors.ini")	# bare_app's rules of a log
NATIVE_DIRS = (hook("BARE_WEB_NATIVE_DIRS", "/games /usr/share/bare_app/games") or "").split()
# bare_app's stream (stream.c): its port, always on 127.0.0.1 (it answers
# GET /live.ts from there only)
STREAM_PORT = hook("BARE_WEB_STREAM", "8554")
STREAM_WAIT = 4.0	# s: a stream "stream on" has just asked for starts in the view's thread
STREAM_QUIET = 10	# s without a byte from bare_app (or room at the browser): it is over
RECIPES = os.path.join(GAMES, "recipes")
SCHEMA = os.path.join(STATIC, "schema.json")
# static files the browser keeps and asks again by their ETag (static())
REVALIDATED = ("mpegts.js",)
STATE_STALE = 3		# s: state.json older than this is no game running
NO_BARE_APP = "bare_app не запущен: дождитесь главного экрана приставки и повторите."
NO_CTL = "bare_app не принимает команды (он не запущен?)."
# the buttons a [keys] names (gp_names.c) and the FIFO presses
BUTTONS = ("up", "down", "left", "right", "a", "b", "x", "y", "l1", "r1", "l2", "r2",
           "select", "start", "f1", "f2", "f3", "f4", "f5", "f6")
DIRS = ("up", "down", "left", "right")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def games_json():
    """games.json of the bare_app that runs, None if it does not"""
    if not RUN:
        return None
    try:
        with open(os.path.join(RUN, "games.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    pid = st.get("pid") if isinstance(st, dict) else None
    if not isinstance(pid, int) or pid <= 0 or not alive(pid):
        return None
    if not TEST and (read("/proc/%d/comm" % pid) or "").strip() != "bare_app":
        return None
    return st


def game_entry(folder, st=None):
    """bare_app's entry of the game in folder (games.json); without bare_app
    the card's game of that directory (no key then)"""
    st = st if st is not None else games_json()
    for g in (st or {}).get("games") or []:
        if isinstance(g, dict) and g.get("folder") == folder:
            return g
    if st is None and card_mounted():
        d = os.path.join(GAMES, folder)
        if os.path.isfile(os.path.join(d, "wine.ini")):
            return {"folder": folder, "kind": "wine", "dir": d, "name": ini_name(os.path.join(d, "wine.ini")) or folder}
        if os.path.isfile(os.path.join(d, "game.ini")):
            return {"folder": folder, "kind": "native", "dir": d, "name": ini_name(os.path.join(d, "game.ini")) or folder}
    return None


def ctl(line):
    """a command to bare_app's FIFO; False if nobody reads it"""
    if not CTL:
        return False
    try:
        fd = os.open(CTL, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        os.write(fd, (line + "\n").encode())
    except OSError:
        return False
    finally:
        os.close(fd)
    log.info("ctl: %s", line)
    return True


def ctl_ready():
    """bare_app reads its FIFO (nothing written)"""
    if not CTL:
        return False
    try:
        os.close(os.open(CTL, os.O_WRONLY | os.O_NONBLOCK))
    except OSError:
        return False
    return True


def game_state():
    """state.json (bare_app, ctl_state.c) while it is renewed; else no game"""
    p = os.path.join(RUN, "state.json") if RUN else None
    try:
        st = os.stat(p)
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, TypeError, ValueError):
        return {"running": None, "stale": True}
    if not isinstance(s, dict) or time.time() - st.st_mtime > STATE_STALE:
        return {"running": None, "stale": True}
    s["stale"] = False
    return s


def running_game(st=None):
    """the folder of the game running now, None: none"""
    s = game_state()
    if s.get("running"):
        return s["running"]
    st = st if st is not None else games_json()
    r = (st or {}).get("running")
    return r.get("folder") if isinstance(r, dict) else None


def conf_values():
    """bare_app.conf's name=value lines"""
    out = {}
    for line in (read(CONF, 1 << 20) or "").splitlines() if CONF else []:
        k, eq, v = line.partition("=")
        if eq and k.strip() and not line.lstrip().startswith("#"):
            out[k.strip()] = v.strip()
    return out


REMAP_OTHER = ("lx", "ly", "rx", "ry", "lsens", "rsens", "gyro", "gyrosens")


def remap_pairs(text):
    """controls.<key> of bare_app.conf (core/remap.h) as (name, value) pairs"""
    out = []
    for p in (text or "").split(","):
        k, eq, v = p.partition("=")
        if eq and k.strip():
            out.append((k.strip(), v.strip()))
    return out


# ---- the games' ini and the recipes' layers (ini_layer.h) -----------------------

LISTS = ("reg", "modes", "saves", "needs")	# INI_LAYER_LISTS
KEY_RE = re.compile(r"^[A-Za-z0-9_.+\-]{1,63}$")
SECTION_RE = re.compile(r"^[A-Za-z0-9_.\-]{0,63}$")
LAYER_MAX = 64 << 10


class IniError(Exception):
    pass


def ini_parse(text, strict=False):
    """(section, key, value) of ini text as bare_app's ini.c reads it; strict:
    a line that is not one of a layer (ini_layer_check()) raises IniError"""
    out = []
    sec = ""
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if strict and (any(ord(c) < 32 and c != "\t" for c in raw) or len(raw.encode()) > LAYER_LINE_MAX):
            raise IniError("строка %d: управляющие символы или длиннее 1000 байт" % n)
        if not line or line[0] in ";#":
            continue
        if line[0] == "[":
            e = line.find("]")
            if strict and (e < 0 or line[e + 1:].strip()):
                raise IniError("строка %d: секция без «]»" % n)
            sec = (line[1:e] if e > 0 else line[1:]).strip()[:63]
            continue
        k, eq, v = line.partition("=")
        if not eq:
            if strict:
                raise IniError("строка %d: нет «=»" % n)
            continue
        v = v.strip()
        m = re.search(r"\s[;#]", v)
        if m:
            v = v[:m.start()].rstrip()
        if k.strip():
            out.append((sec, k.strip(), v))
    return out


def is_list(sec, key):
    return sec == "" and key.lower() in LISTS


def ini_merge(base, layer):
    """ini_layer.c merge(): the layer's entries over base's"""
    out = list(base)
    begun = set()

    def same(e, s, k):
        return e[0].lower() == s.lower() and e[1].lower() == k.lower()
    for s, k, v in layer:
        if is_list(s, k):
            if k.lower() not in begun:
                begun.add(k.lower())
                out = [e for e in out if not same(e, s, k)]
            if v:
                out.append((s, k, v))
            continue
        idx = [i for i, e in enumerate(out) if same(e, s, k)]
        if v and idx:
            out[idx[0]] = (out[idx[0]][0], out[idx[0]][1], v)
            drop = set(idx[1:])
        else:
            drop = set(idx)
        out = [e for i, e in enumerate(out) if i not in drop]
        if v and not idx:
            out.append((s, k, v))
    return out


def ini_sections(entries):
    """{section: {key: value}} (lower case; a list key: [values]; else the
    last value, as the readers take it)"""
    out = {}
    for s, k, v in entries:
        s, k = s.lower(), k.lower()
        d = out.setdefault(s, {})
        if is_list(s, k):
            if v:
                d.setdefault(k, []).append(v)
            else:
                d.setdefault(k, [])
        else:
            d[k] = v
    return out


def sections_entries(sections):
    """{section: {key: value}} back to entries (a list: a line each)"""
    out = []
    for s, keys in sections.items():
        for k, v in keys.items():
            if isinstance(v, list):
                out += [(s, k, x) for x in v] or [(s, k, "")]
            else:
                out.append((s, k, v))
    return out


def layer_text(entries, folder, base_path):
    lines = ["; the player's changes of %s's recipe, only what differs from %s" % (folder, base_path),
             "; (bare-web %s; ini_layer.h: a key replaces the game's, \"key =\" drops it)"
             % time.strftime("%Y-%m-%d %H:%M")]
    top = [e for e in entries if not e[0]]
    lines += ["%s = %s" % (k, v) if v else "%s =" % k for _, k, v in top]
    done = []
    for s, _, _ in entries:
        if s and s not in done:
            done.append(s)
    for s in done:
        lines += ["", "[%s]" % s]
        lines += ["%s = %s" % (k, v) if v else "%s =" % k for es, k, v in entries if es == s]
    return "\n".join(lines) + "\n"


def layer_diff(desired, base):
    """what of desired ({section: {key: value}}, the layer's values) differs
    from base: a value other than the game's, a list other than its (all of
    it), "" where the game has the key (dropped); the same as the game's: no
    line"""
    out = []
    for s, keys in desired.items():
        for k, v in keys.items():
            have = base.get(s, {}).get(k)
            if is_list(s, k):
                want = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
                have = have or []
                if want == have:
                    continue
                out += [(s, k, x) for x in want] if want else [(s, k, "")]
            else:
                v = str(v).strip()
                if v == "":
                    if have:
                        out.append((s, k, ""))
                elif v != have:
                    out.append((s, k, v))
    return out


# ---- the schema (/usr/share/bare-web/schema.json) and bare_app_wine's tables -----

_SCHEMA = None
_WINE = {"actions": None, "defaults": None}
_WINE_LOCK = threading.Lock()


def schema():
    global _SCHEMA
    if _SCHEMA is None:
        try:
            with open(SCHEMA, encoding="utf-8") as f:
                _SCHEMA = json.load(f)
        except (OSError, ValueError) as e:
            log.warning("%s: %s", SCHEMA, e)
            _SCHEMA = {"wine": [], "game": [], "controls": [], "env_presets": [], "lists": list(LISTS)}
    return _SCHEMA


def schema_keys(kind):
    return {(e["section"], e["key"]): e for e in schema().get("game" if kind == "native" else "wine", [])}


def wine_tables():
    """bare_app_wine --actions and --defaults, read once"""
    with _WINE_LOCK:
        if _WINE["actions"] is None and WINE:
            rc, out, err = run([WINE, "--actions"], timeout=10)
            acts = []
            for line in out.splitlines() if rc == 0 else []:
                f = line.split("\t")
                if len(f) >= 2:
                    acts.append({"group": f[0], "name": f[1], "takes": f[2].split(",") if len(f) > 2 else None})
            if rc:
                log.warning("%s --actions: %s", WINE, (err or "exit %d" % rc).strip())
            _WINE["actions"] = acts
            rc, out, err = run([WINE, "--defaults"], timeout=10)
            _WINE["defaults"] = ini_sections(ini_parse(out)) if rc == 0 else {}
        return _WINE["actions"] or [], _WINE["defaults"] or {}


def defaults_of(kind):
    """the values a key has where the ini says nothing: bare_app_wine's for
    a Windows game, the schema's for bare_app's own keys"""
    out = {}
    for (s, k), e in schema_keys(kind).items():
        if "default" in e:
            out.setdefault(s, {})[k] = [e["default"]] if e.get("repeat") else e["default"]
    if kind == "wine":
        for s, keys in wine_tables()[1].items():
            out.setdefault(s, {}).update(keys)
    return out


MODE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def value_problem(kind, s, k, v):
    """why value v of [s] k is not one the readers take (None: it is), and
    a warning (an unknown key)"""
    if any(ord(c) < 32 for c in v) or len(v.encode()) > 900:
        return "%s: управляющие символы или слишком длинно" % k, None
    if v[:1] in (";", "#") or re.search(r"\s[;#]", v):
        return "%s: «;» или «#» после пробела читается как комментарий" % k, None
    e = schema_keys(kind).get((s, k))
    if e is None:
        return None, "%s%s: ключа нет в схеме, записан как текст" % ("[%s] " % s if s else "", k)
    if v == "":
        return None, None
    t = e["type"]
    if t == "enum" and v not in e["values"]:
        return "%s: одно из %s" % (k, ", ".join(e["values"])), None
    if t in ("int", "float"):
        if v in e.get("also", []):
            return None, None
        try:
            n = int(v) if t == "int" else float(v)
        except ValueError:
            return "%s: нужно %s" % (k, "целое число" if t == "int" else "число"), None
        if n < e.get("min", n) or n > e.get("max", n):
            return "%s: от %s до %s" % (k, e["min"], e["max"]), None
    if t == "bool" and v.lower() not in ("yes", "no", "true", "false", "1", "0"):
        return "%s: yes или no" % k, None
    if t == "text" and e.get("pattern") and not re.match(e["pattern"], v):
        return "%s: не в том виде (пример: %s)" % (k, e.get("example", "")), None
    if t == "text" and k == "mode":
        m = MODE_RE.match(v)
        if not (320 <= int(m.group(1)) <= 4096 and 200 <= int(m.group(2)) <= 4096):
            return "mode: от 320x200 до 4096x4096", None
    if t == "list":
        if e.get("item_pattern") and not re.match(e["item_pattern"], v):
            return "%s: не в том виде: %s" % (k, v), None
        if e.get("item") == "reg":
            key, eq, _ = v.partition("=")
            if not eq or "\\" not in key or key.endswith("\\") or key.startswith("\\"):
                return "reg: нужно KEY\\NAME=DATA: %s" % v, None
    if t in ("keys", "stick") and kind == "wine":
        acts = wine_tables()[0]
        if not acts:
            return None, None	# no table: bare_app_wine says it in the log
        if t == "stick":
            ok = [a["name"] for a in acts if a["group"] == "stick" and k in (a["takes"] or [])]
            if v not in ok:
                return "%s: одно из %s" % (k, ", ".join(ok)), None
            return None, None
        single = {a["name"] for a in acts if a["group"] in ("mouse", "pad", "special")}
        keys = {a["name"] for a in acts if a["group"] == "key"}
        if v in single:
            return None, None
        parts = action_keys(v)
        if parts is None or not 0 < len(parts) <= 4 or not all(p.lower() in keys for p in parts):
            return "%s: не клавиша и не действие: %s" % (k, v), None
    return None, None


def action_keys(v):
    """the keys of an action joined by "+" as bare_app_wine's parse_action()
    splits them (kp+ is a key), None if it would not"""
    out, i = [], 0
    while i < len(v):
        j = v.find("+", i)
        j = len(v) if j < 0 else j
        if j - i == 2 and v[i:j] == "kp" and j < len(v):
            j += 1
        if j < len(v) and v[j] != "+":
            return None
        if j > i:
            out.append(v[i:j])
        i = j + 1
    return out


def layer_check(kind, desired):
    """the desired layer's problems (400) and warnings"""
    errors, warnings = [], []
    if not isinstance(desired, dict):
        return ["нет секций"], []
    for s, keys in desired.items():
        if not isinstance(s, str) or not SECTION_RE.match(s) or not isinstance(keys, dict):
            errors.append("секция не подходит: %r" % (s,))
            continue
        for k, v in keys.items():
            if not isinstance(k, str) or not KEY_RE.match(k):
                errors.append("ключ не подходит: %r" % (k,))
                continue
            vals = v if isinstance(v, list) else [v]
            if isinstance(v, list) and not is_list(s, k):
                errors.append("%s: одно значение, не список" % k)
                continue
            for x in vals:
                if not isinstance(x, (str, int, float)) or isinstance(x, bool):
                    errors.append("%s: значение не текст" % k)
                    continue
                e, w = value_problem(kind, s, k, str(x).strip())
                if e:
                    errors.append(e)
                if w and w not in warnings:
                    warnings.append(w)
    return errors, warnings


def lower_sections(d):
    out = {}
    for s, keys in (d or {}).items():
        if isinstance(s, str) and isinstance(keys, dict):
            t = out.setdefault(s.strip().lower(), {})
            for k, v in keys.items():
                t[k.strip().lower() if isinstance(k, str) else k] = v
        else:
            out[s] = keys
    return out


class Recipe:
    """a game's ini (its recipe), the layer of the player's changes, the
    effective ini bare_app merged"""

    def __init__(self, g):
        self.folder = g["folder"]
        self.g = g
        kind = g.get("kind")
        self.kind = kind if kind in ("wine", "native") else "built-in"
        self.ini = {"wine": "wine.ini", "native": "game.ini"}.get(self.kind)
        self.base_path = None
        if self.kind == "wine" and g.get("dir"):
            self.base_path = os.path.join(g["dir"], "wine.ini")
        elif self.kind == "native":
            cands = [os.path.join(g["dir"], "game.ini")] if g.get("dir") else []
            for d in NATIVE_DIRS:
                cands += [os.path.join(d, self.folder + ".ini"), os.path.join(d, self.folder, "game.ini")]
            self.base_path = next((c for c in cands if os.path.isfile(c)), None)
        self.layer_dir = os.path.join(RECIPES, self.folder)
        self.layer_path = os.path.join(self.layer_dir, self.ini) if self.ini else None
        name = self.folder + (".ini" if self.kind == "wine" else ".game.ini")
        self.eff_path = os.path.join(RUN, "ini", name) if RUN and self.ini else None

    def editable(self):
        return bool(self.ini and self.base_path and os.path.isfile(self.base_path))

    def base_entries(self):
        return ini_parse(read(self.base_path, 1 << 20) or "") if self.base_path else []

    def base_too_long(self):
        """the game's ini has a line longer than bare_app's readers take
        (ini_layer.c base_fits(): more than 1000 bytes before its newline):
        bare_app does not use the layer then; the line's number, else 0"""
        try:
            with open(self.base_path, "rb") as f:
                for n, line in enumerate(f, 1):
                    if len(line.rstrip(b"\n")) > LAYER_LINE_MAX:
                        return n
        except (OSError, TypeError):
            pass
        return 0

    def layer_raw(self):
        if not self.layer_path or os.path.islink(self.layer_path):
            return None
        return read(self.layer_path, LAYER_MAX + 1)

    def effective(self):
        """the effective ini: bare_app's file when it is of this layer, else
        merged here by the same rules; without a layer the game's"""
        base = self.base_entries()
        raw = self.layer_raw()
        if raw is None or self.base_too_long():
            return base, "base"	# bare_app: the layer broken, the game's as it is
        try:
            lm = os.stat(self.layer_path).st_mtime_ns
            em = os.stat(self.eff_path).st_mtime_ns if self.eff_path else -1
        except OSError:
            em, lm = -1, 0
        if em >= lm:
            return ini_parse(read(self.eff_path, 1 << 20) or ""), "bare_app"
        try:
            return ini_merge(base, ini_parse(raw, strict=True)), "server"
        except IniError:
            return base, "base"

    def describe(self, st):
        out = {"folder": self.folder, "name": self.g.get("name") or self.folder, "kind": self.kind,
               "ini": self.ini, "editable": self.editable(), "base_path": self.base_path,
               "layer_path": self.layer_path, "key": self.g.get("key"),
               "layer_state": self.g.get("layer"), "layer_error": self.g.get("layer_error"),
               "running": running_game(st) == self.folder}
        if not out["editable"]:
            return out
        raw = self.layer_raw()
        layer, err = None, None
        if raw is not None:
            try:
                layer = ini_sections(ini_parse(raw, strict=True))
            except IniError as e:
                err = str(e)
            long_line = self.base_too_long()
            if long_line and not err:
                err = ("строка %d ini игры длиннее %d байт: приставка правки не применяет"
                       % (long_line, LAYER_LINE_MAX))
        eff, src = self.effective()
        out.update(base=ini_sections(self.base_entries()), layer=layer, layer_text=raw,
                   layer_problem=err, effective=ini_sections(eff), effective_source=src,
                   defaults=defaults_of(self.kind))
        key = self.g.get("key")
        conf = conf_values() if key else {}
        ctrl = conf.get("controls." + key) if key else None
        out["player_controls"] = {"key": "controls." + key if key else None, "value": ctrl,
                                  "pairs": [{"from": a, "to": b} for a, b in remap_pairs(ctrl)]}
        out["player_options"] = {"key": "options." + key if key else None,
                                 "value": conf.get("options." + key) if key else None}
        return out


LAYER_LINE_MAX = 1000	# bytes of a line bare_app's ini readers take (ini_layer.c LINE_MAX_LEN)
RECIPE_LOCK = threading.Lock()	# one change of a layer at a time (also game-install heal writable)


class NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


NO_LOCK = NoLock()


class Refused(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.status = status


def recipe_of(folder, st=None):
    if not isinstance(folder, str) or not safe_name(folder):
        raise Refused(400, "Имя игры не подходит: %s" % folder)
    g = game_entry(folder, st)
    if not g:
        raise Refused(404, "Такой игры нет: %s" % folder)
    r = Recipe(g)
    if not r.editable():
        raise Refused(400, "У этой игры нет рецепта (wine.ini или game.ini), который можно править.")
    return r


# ---- healing a game without a recipe (stage 8) ----------------------------------

HEAL_RULES = {"wine-missing-dll": "dll", "card-read-only": "writable"}	# errors.ini's sections


def error_rules():
    """errors.ini's healable sections: {name: {match: [..], require: [..], exclude: [..]}}"""
    out, sec = {}, None
    for raw in (read(ERRORS, 1 << 20) or "").splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("["):
            sec = line[1:line.find("]")].strip() if "]" in line else None
            if sec in HEAL_RULES:
                out[sec] = {"match": [], "require": [], "exclude": []}
            continue
        k, eq, v = line.partition("=")
        k = k.strip()
        if eq and sec in out and k in ("match", "require", "exclude"):
            v = re.split(r"\s[;#]", v.strip(), 1)[0]	# as it is: ini.c has no escapes
            out[sec][k].append(v)
    return out


def find_piece(lines, piece, excl=()):
    """game_errors.c find_piece(): the first line with piece (its "*" any
    text, captured) and none of excl: (line, capture), None"""
    head, star, tail = piece.partition("*")
    for line in lines:
        i = line.find(head)
        if i < 0:
            continue
        j = line.find(tail, i + len(head)) if star else len(line)
        if j < 0 or any(x in line for x in excl):
            continue
        return line, line[i + len(head):j].strip() if star else ""
    return None


def heal_suggestions(folder):
    """what game-install heal can do for the game's last launch (1.log), by the
    same rules as its error screen (errors.ini)"""
    try:
        with open(os.path.join(LOGS, folder, "1.log"), "rb") as f:
            lines = f.read(4 << 20).decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for name, r in error_rules().items():
        hit = None
        for m in r["match"]:
            hit = find_piece(lines, m, r["exclude"])
            if hit:
                break
        if not hit or not all(find_piece(lines, q) for q in r["require"]):
            continue
        line, cap = hit
        if HEAL_RULES[name] == "dll":
            arg = os.path.basename(cap.replace("\\", "/"))
            if re.match(r"^[A-Za-z0-9_.+-]+\.dll$", arg, re.I):
                out.append({"rule": name, "kind": "dll", "arg": arg, "line": line,
                            "text": "Положить библиотеку %s из папки redist в папку игры" % arg})
        else:
            # the path of the game's folder in that line: on the card or its copy
            m = re.search(r"(?:/games|/data/wine/games)/%s/([^\s:'\"]+)" % re.escape(folder), line)
            if m:
                arg = m.group(1).rstrip(".,)")
                out.append({"rule": name, "kind": "writable", "arg": arg, "line": line,
                            "text": "Разрешить игре запись в %s (writable в правках рецепта)" % arg})
    return out


HEAL_WORDS = {
    "need": "Библиотеки %s нет ни в папке redist на карте, ни в системе. Положите её (32-битную) или "
            "установщик DirectX (directx_Jun2010_redist.exe) в папку redist и повторите.",
    "exists": "Файл уже есть в папке игры: %s. Дело не в нём — сохраните отчёт.",
    "gone": "Игры %s нет на карте (или это не игра Windows).",
    "card": "Карту игр не удалось открыть для записи.",
    "busy": "Сейчас идёт установка или удаление игры: дождитесь конца и повторите.",
    "error": "Не вышло: %s",
}

def merge_text(base_text, layer):
    """the game's ini text with the layer's entries (ini_merge()'s rules, its
    result as ini_parse() reads it) and the game's comments kept: a key the
    layer has its value in the base's first line of it (the others dropped),
    a list where its first line was, a key the base has not at the end of its
    section (a section the base has not at the end)"""
    def low(sk):
        return (sk[0].lower(), sk[1].lower())
    lists, scalars, order = {}, {}, []
    for sec, k, v in layer:
        key = low((sec, k))
        if is_list(sec, k):
            lists.setdefault(key, [])
            if v:
                lists[key].append((k, v))
        else:
            scalars[key] = (k, v)
        if key not in order:
            order.append(key)
    out, done = [], set()
    sec, sec_end = "", {}
    for raw in base_text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            e = line.find("]")
            sec = (line[1:e] if e > 0 else line[1:]).strip()[:63]
            out.append(raw)
            sec_end[sec.lower()] = len(out)
            continue
        k, eq, _ = line.partition("=")
        if not line or line[0] in ";#" or not eq or not k.strip():
            out.append(raw)
            sec_end[sec.lower()] = len(out)
            continue
        key = low((sec, k.strip()))
        if key in lists:
            if key not in done:
                out += ["%s = %s" % (lk, lv) for lk, lv in lists[key]]
            done.add(key)
        elif key in scalars:
            if key not in done and scalars[key][1]:
                out.append("%s = %s" % (k.strip(), scalars[key][1]))
            done.add(key)
        else:
            out.append(raw)
        sec_end[sec.lower()] = len(out)
    adds = {}
    for key in order:
        if key in done:
            continue
        lines = (["%s = %s" % kv_ for kv_ in lists[key]] if key in lists else
                 ["%s = %s" % scalars[key]] if scalars[key][1] else [])
        if lines:
            adds.setdefault(key[0], []).extend(lines)
    new_secs = []
    for sname, lines in sorted(adds.items(), key=lambda a: -sec_end.get(a[0], -1)):
        if sname in sec_end:
            at = sec_end[sname]
            out[at:at] = lines
        else:
            new_secs.append((sname, lines))
    if "" in dict(new_secs):	# a top key, the base has no line at the top: before its first section
        at = next((i for i, l in enumerate(out) if l.strip().startswith("[")), len(out))
        out[at:at] = dict(new_secs).pop("") + [""]
        new_secs = [x for x in new_secs if x[0]]
    for sname, lines in new_secs:
        out += ["", "[%s]" % sname] + lines
    return "\n".join(out) + "\n"


def unit_label():
    _, label, _ = run([UNIT, "label"], timeout=5)
    return label.strip() or (kv(read(RELEASE) or "").get("FIRMWARE") or "?")


def recipe_info(d):
    """game-install recipe DIR: (lines by kind {kind: [fields...]})"""
    rc, out, _ = run([GAME_INSTALL, "recipe", d], timeout=60)
    info = {}
    if rc != 0:
        return info
    for line in out.splitlines():
        f = line.split("\t")
        if f and f[0] in ("recipe", "detect", "gog", "primary", "need"):
            info.setdefault(f[0], []).append(f[1:])
    return info


README_TEMPLATE = """# {name}

{name}, {edition}, {engine} on the GO Ultra (manifest `[{folder}]`,
{ini} in `overlay/`). Made on the device {unit} on {date} (bare-web's
export: the recipe of the device with the player's changes).

TODO, fill in before the review:
- the edition (the year, the publisher, the version; GOG id {gog});
- what was checked: the start, the menus, a level or a scene, saving and
  loading, the controls, the frame rate;
- what is not done or known wrong.
"""


def export_zip(r, st):
    """the zip of POST /api/recipe/FOLDER/export: (bytes, its name)"""
    g, folder = r.g, r.folder
    d = g.get("dir") or os.path.join(GAMES, folder)
    base_text = read(r.base_path, 1 << 20) or ""
    raw = r.layer_raw()
    layer = None
    if raw is not None:
        try:
            layer = ini_parse(raw, strict=True)
        except IniError:
            layer = None	# not taken by bare_app either: the game's ini as it is
    text = merge_text(base_text, layer) if layer else base_text
    info = recipe_info(d)
    gog = [x for x in info.get("gog", []) if x and x[0]]
    known = (info.get("recipe") or [["-"]])[0][0]
    unit, date = unit_label(), time.strftime("%Y-%m-%d")
    if gog:
        edition = "GOG %s" % ", ".join("%s (%s)" % (x[0], x[1]) if len(x) > 1 and x[1] else x[0] for x in gog)
    else:
        edition = "edition not known"
    origin = edition + ("; the firmware's recipe [%s]" % known if known != "-" else "")
    head = "; made on the device %s %s, from %s%s\n" % (unit, date, origin,
                                                       ", with the player's changes" if layer else "")
    eff = ini_sections(ini_parse(text))
    name = (eff.get("") or {}).get("name") or g.get("name") or folder
    # the main program: the recipe's detect, else the ini's exe (relative), else GOG's primary one
    exe = (eff.get("") or {}).get("exe", "").replace("\\", "/")
    if info.get("detect"):
        detect = info["detect"][0][0]
    elif exe and ":" not in exe and not exe.startswith("/"):
        detect = exe
    else:
        detect = (info.get("primary") or [[""]])[0][0]
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    lower = {n.lower() for n in names}
    excl = (["goggame-*"] if any(n.startswith("goggame-") for n in lower) else []) + \
        [x for x in ("__redist", "tmp", "commonappdata") if x in lower]
    cover_rel = (eff.get("") or {}).get("cover") or "cover.png"
    cover = None
    cp = os.path.normpath(os.path.join(d, cover_rel))
    if not os.path.isabs(cover_rel) and ".." not in cover_rel.replace("\\", "/").split("/") and \
            os.path.isfile(cp) and not os.path.islink(cp) and os.path.getsize(cp) <= 8 << 20:
        with open(cp, "rb") as f:
            cover = f.read()
    sec = ["[%s]" % folder]
    if detect:
        sec.append("detect = %s" % detect)
    else:
        sec.append("; detect = MAIN.exe (fill in: the game's program, relative to its folder)")
    if gog:
        sec.append("gog = %s" % " ".join(x[0] for x in gog))
    sec.append("; %s, %s: exported from the device %s %s (bare-web); fill in source, check"
               % (name, edition, unit, date))
    sec.append("source = lab/games/%s" % name)
    sec += ["exclude = %s" % x for x in excl]
    sec.append("overlay = games/%s/overlay" % folder)
    if cover:
        sec.append("cover = games/%s/cover.png" % folder)
    needs = [x[0] for x in info.get("need", []) if x]
    try:	# a Windows or game.ini game's log: its folder's; as it is (bytes)
        with open(os.path.join(LOGS, folder, "1.log"), "rb") as f:
            log = f.read(4 << 20)
    except OSError:
        log = None
    buf = io.BytesIO()
    pre = "games/%s/" % folder
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(pre + "overlay/" + r.ini, head + text)
        if cover:
            z.writestr(pre + "cover.png", cover)
        z.writestr(pre + "README.md", README_TEMPLATE.format(
            name=name, edition=edition, engine="under Wine" if r.kind == "wine" else "its own engine",
            folder=folder, ini=r.ini, unit=unit, date=date, gog=" ".join(x[0] for x in gog) or "none"))
        z.writestr("manifest.section", "\n".join(sec) + "\n")
        z.writestr("needs.txt", "".join(n + "\n" for n in needs))
        if log is not None:
            z.writestr("logs/1.log", log)
    return buf.getvalue(), "recipe-%s-%s-%s.zip" % (folder, unit, date)


def games_json_stamp():
    try:
        return os.stat(os.path.join(RUN, "games.json")).st_mtime_ns
    except (OSError, TypeError):
        return None


def wait_effective(r, before, timeout=2.0):
    """after "reload": until bare_app has written (or removed) the effective
    ini of the layer as it is now, and games.json again (its state of the
    layer; before: its time before the reload)"""
    if not r.eff_path:
        return
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            lm = os.stat(r.layer_path).st_mtime_ns
        except OSError:
            lm = None
        try:
            em = os.stat(r.eff_path).st_mtime_ns
        except OSError:
            em = None
        if ((lm is None and em is None) or (lm is not None and em is not None and em >= lm)) and \
                games_json_stamp() != before:
            return
        time.sleep(0.05)


def put_layer(r, entries):
    """the layer's file: entries (only what differs) written, none: the file
    removed; then bare_app reads the game's ini again. Returns whether
    bare_app was told"""
    why = card_problem()
    if why:
        raise Refused(503, why)
    if os.path.islink(r.layer_dir) or os.path.islink(RECIPES) or \
            (os.path.lexists(r.layer_path) and not os.path.isfile(r.layer_path)) or os.path.islink(r.layer_path):
        raise Refused(409, "Папка правок %s — ссылка или не файл: не трогаю." % r.layer_dir)
    text = layer_text(entries, r.folder, r.base_path) if entries else None
    if text and len(text.encode()) > LAYER_MAX:
        raise Refused(413, "Правок слишком много (больше 64 КБ).")
    try:
        with CardWriting():
            if text:
                os.makedirs(r.layer_dir, exist_ok=True)
                tmp = os.path.join(r.layer_dir, ".%s.web" % r.ini)
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, r.layer_path)
            else:
                if os.path.lexists(r.layer_path):
                    os.remove(r.layer_path)
                for d in (r.layer_dir, RECIPES):	# only if empty: never anything else
                    try:
                        os.rmdir(d)
                    except OSError:
                        break
    except (CardError, OSError) as e:
        raise Refused(500, "Правки не записаны: %s" % e)
    log.info("layer %s: %s", r.folder, "%d lines" % len(entries) if text else "removed")
    before = games_json_stamp()
    told = ctl("reload " + r.folder)
    if told:
        wait_effective(r, before)
    return told


def adopt_controls(r, st):
    """the player's own buttons (controls.<key>) written into the layer's
    [keys] and [labels]: device button A that is B for the game does what B
    does (its action and its label); then bare_app drops them from the
    player's settings (import-settings). What a [keys] cannot say (an axis
    inverted, a stick's sensitivity, the gyro, the D-pad's directions while
    it is not arrows) stays the player's."""
    key = r.g.get("key")
    if not key or not st:
        raise Refused(503, NO_BARE_APP)
    if r.kind != "wine":
        raise Refused(400, "Перенос кнопок в рецепт есть только у игр Windows.")
    if running_game(st) == r.folder:
        raise Refused(409, "Игра идёт: перестановка кнопок игрока сейчас действует. Выйдите из игры.")
    conf = conf_values()
    ctrl = conf.get("controls." + key)
    if not ctrl:
        raise Refused(409, "У игрока нет своей перестановки кнопок этой игры.")
    if not RUN or not ctl_ready():
        raise Refused(503, NO_CTL)
    eff = ini_sections(r.effective()[0])
    keys = dict(defaults_of("wine").get("keys", {}))
    keys.update(eff.get("keys", {}))
    arrows = keys.get("dpad", "arrows") not in ("mouse", "scroll", "pad")
    raw = r.layer_raw()
    try:
        layer = ini_sections(ini_parse(raw, strict=True)) if raw is not None else {}
    except IniError:
        raise Refused(409, "Правки этой игры не читаются: сначала сбросьте их.")
    keep, moved = [], []
    want = {"keys": {}, "labels": {}, "labels.ru": {}}
    for a, b in remap_pairs(ctrl):
        if a in REMAP_OTHER or a not in BUTTONS or (b != "-" and b not in BUTTONS) or \
                (not arrows and (a in DIRS or b in DIRS)):
            keep.append((a, b))
            continue
        want["keys"][a] = "none" if b == "-" else keys.get(b, "none")
        for s in ("labels", "labels.ru"):
            want[s][a] = "" if b == "-" else eff.get(s, {}).get(b, "")
        moved.append((a, b))
    if not moved:
        raise Refused(409, "В перестановке игрока нет кнопок, которые можно перенести в [keys].")
    for s, kv in want.items():
        layer.setdefault(s, {}).update(kv)
    base = ini_sections(r.base_entries())
    entries = layer_diff(layer, base)
    rest = ",".join("%s=%s" % p for p in keep)
    imp = os.path.join(RUN, "import-web-%s.ini" % r.folder)
    lines = ["; bare-web: the player's buttons of %s moved into its recipe" % r.folder, "game=" + key]
    if rest:
        lines.append("controls.%s=%s" % (key, rest))
    if conf.get("options." + key):
        lines.append("options.%s=%s" % (key, conf["options." + key]))
    with RECIPE_LOCK:
        for p in (imp, imp + ".taken", imp + ".bad"):	# of an earlier one: not this one's answer
            gone(p)
        put_layer(r, entries)
        try:
            with open(imp + ".tmp", "w") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(imp + ".tmp", imp)
        except OSError as e:
            restore_layer(r, raw)
            raise Refused(500, "Файл для bare_app не записан: %s" % e)
        if not ctl("import-settings " + imp):
            gone(imp)
            raise Refused(503, NO_CTL if restore_layer(r, raw) else NO_CTL + " " + NOT_BACK)
        done = settings_taken(imp, key, keep)
        if not done:
            raise Refused(503, NOT_APPLIED if restore_layer(r, raw) else NOT_APPLIED_KEPT)
    log.info("adopt %s: %s moved, %s kept", r.folder, moved, keep)
    return {"moved": [{"from": a, "to": b} for a, b in moved], "kept": [{"from": a, "to": b} for a, b in keep],
            "settings_done": True}


IMPORT_WAIT = 15.0	# s: bare_app takes an import-settings file (view_ctl.c, ctl_settings.c)
NOT_APPLIED = "Приставка не применила настройки, ничего не изменено."
NOT_BACK = "Правки рецепта вернуть не удалось: сбросьте их в Мастерской."
NOT_APPLIED_KEPT = "Приставка не применила настройки; " + NOT_BACK


def gone(path):
    """True: path is no more (removed now or before)"""
    try:
        os.remove(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def wait_for(cond, seconds):
    end = time.monotonic() + seconds
    while not cond():
        if time.monotonic() >= end:
            return False
        time.sleep(0.1)
    return True


def settings_taken(imp, key, keep):
    """bare_app's answer to "import-settings imp": it renames imp to
    imp.taken, removes that once the settings are in, renames it imp.bad if
    they cannot be. True: the settings are in. False: they are not (imp
    taken back by removing it before bare_app took it, or .bad, or bare_app
    took it and did not finish)"""
    if not wait_for(lambda: not os.path.exists(imp), IMPORT_WAIT):
        try:
            os.remove(imp)
            log.warning("import-settings %s: not taken in %.0f s, taken back", imp, IMPORT_WAIT)
            return False
        except FileNotFoundError:
            pass	# taken just now
        except OSError as e:
            log.warning("import-settings %s: not taken, not removed: %s", imp, e)
            return False
    if not wait_for(lambda: not os.path.exists(imp + ".taken"), IMPORT_WAIT):
        log.warning("import-settings %s: taken, not done", imp)
        return False
    if os.path.exists(imp + ".bad"):
        gone(imp + ".bad")
        log.warning("import-settings %s: bare_app could not take the settings in", imp)
        return False
    # in: bare_app writes its settings file a second later
    if not wait_for(lambda: set(remap_pairs(conf_values().get("controls." + key))) == set(keep), 4):
        log.warning("import-settings %s: in, the settings file not yet written", imp)
    return True


def restore_layer(r, raw):
    """the layer as it was (raw None: none); False: it could not be"""
    try:
        if raw is None:
            put_layer(r, [])
        else:
            put_layer(r, ini_parse(raw))
    except Refused as e:
        log.warning("layer %s not put back: %s", r.folder, e)
        return False
    return True


# ---- the screen, the buttons, the sticks (the check of a game) -------------------

SHOT_LOCK = threading.Lock()
SHOT_WAIT = 2.0


def shot_path(pid):
    """where bare_app writes its screenshot: $BARE_APP_SHOT of its own
    environment, else its default (view.c snapshot())"""
    if SHOT:
        return SHOT
    if TEST:
        return None
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            for v in f.read().split(b"\0"):
                if v.startswith(b"BARE_APP_SHOT=") and len(v) > 14:
                    return v[14:].decode()
    except OSError:
        pass
    return "/tmp/bare_app.ppm"


def ppm_png(data, width):
    """bare_app's PPM (P6, 8 bits) as PNG bytes, by zlib alone: Pillow would
    keep ~8 MB more in this server for good. width: at most that wide, taken
    down by a whole step (every 2nd pixel and row of 854 for 480)"""
    m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
    if not m:
        raise ValueError("not a PPM of 8 bits")
    w, h = int(m.group(1)), int(m.group(2))
    px = memoryview(data)[m.end():]
    if len(px) < w * h * 3:
        raise ValueError("a PPM cut short")
    step = max(1, -(-w // width)) if width else 1
    ow, oh = -(-w // step), -(-h // step)
    rows = bytearray()
    for y in range(0, h, step):
        row = px[y * w * 3:(y + 1) * w * 3]
        rows.append(0)	# filter: none
        if step == 1:
            rows += row
        else:
            out = bytearray(ow * 3)
            for c in range(3):
                out[c::3] = row[c::3][::step]
            rows += out

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(rows), 1)) + chunk(b"IEND", b""))


def take_shot(width):
    """the screen now (bare_app's layers, SIGUSR1) as PNG bytes; width: at
    most that wide"""
    st = games_json()
    if not st:
        raise Refused(503, NO_BARE_APP)
    path = shot_path(st["pid"])
    if not path:
        raise Refused(503, "Снимок экрана не настроен.")
    with SHOT_LOCK:
        try:
            os.remove(path)	# what comes now is the new one (written whole, renamed)
        except OSError:
            pass
        os.kill(st["pid"], signal.SIGUSR1)
        end = time.monotonic() + SHOT_WAIT
        data = None
        while time.monotonic() < end:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                break
            except OSError:
                time.sleep(0.03)
        if data is None:
            raise Refused(504, "bare_app не дал снимок экрана за %d с." % SHOT_WAIT)
        try:
            os.remove(path)	# 1,2 MB of /run otherwise
        except OSError:
            pass
    try:
        return ppm_png(data, width)
    except ValueError as e:
        raise Refused(500, "Снимок не читается: %s" % e)


PRESSED = {}	# button: the press's number (released on its own after PRESS_MAX)
PRESS_LOCK = threading.Lock()
PRESS_MAX = 10.0
PRESS_SEQ = [0]


def pad_button(name, down):
    if name not in BUTTONS:
        raise Refused(400, "Нет такой кнопки: %s" % name)
    if not ctl(("press " if down else "release ") + name):
        raise Refused(503, NO_CTL)
    with PRESS_LOCK:
        if not down:
            PRESSED.pop(name, None)
            return
        PRESS_SEQ[0] += 1
        seq = PRESSED[name] = PRESS_SEQ[0]

    def later():
        with PRESS_LOCK:
            if PRESSED.get(name) != seq:
                return
            PRESSED.pop(name, None)
        ctl("release " + name)	# the page let go of it without saying so
    t = threading.Timer(PRESS_MAX, later)
    t.daemon = True
    t.start()


def release_all():
    with PRESS_LOCK:
        names = list(PRESSED)
        PRESSED.clear()
    for n in names:
        ctl("release " + n)


EVENT = struct.Struct("qqHHi")	# struct input_event (64-bit time)
EV_SYN, EV_ABS = 0, 3


def _ioc_read(nr, size):
    return (2 << 30) | (size << 16) | (ord("E") << 8) | nr


def stick_device(which):
    """the evdev node of the left or right stick (adc-joystick-left, -right)"""
    want = "adc-joystick-" + ("left" if which == "stick" else "right")
    if not SYS_INPUT or not DEV_INPUT:
        return None
    try:
        names = sorted(os.listdir(SYS_INPUT))
    except OSError:
        return None
    for e in names:
        if e.startswith("event") and (read(os.path.join(SYS_INPUT, e, "device", "name")) or "").strip() == want:
            return os.path.join(DEV_INPUT, e)
    return None


def stick_hold(which, x, y, ms):
    """the stick held at x, y (-1..1, up and left negative) for ms, as
    scripts/ogu-hold.c does: the values written every 2 ms (the polled
    stick reports its real position every 10 ms)"""
    import fcntl
    dev = stick_device(which)
    if not dev:
        raise Refused(503, "Стика %s нет." % which)
    try:
        fd = os.open(dev, os.O_WRONLY)
    except OSError as e:
        raise Refused(503, "Стик не открывается: %s" % e)
    try:
        bits = bytearray(8)
        fcntl.ioctl(fd, _ioc_read(0x20 + EV_ABS, len(bits)), bits)
        codes = [c for c in range(64) if bits[c // 8] >> (c % 8) & 1][:2]
        if len(codes) < 2:
            raise Refused(503, "У стика нет двух осей.")
        axes = []
        for c, v in zip(codes, (x, y)):
            info = bytearray(24)
            fcntl.ioctl(fd, _ioc_read(0x40 + c, 24), info)
            _, lo, hi = struct.unpack("iii", bytes(info[:12]))
            axes.append((c, int((lo + hi) / 2 + max(-1.0, min(1.0, v)) * (hi - lo) / 2), (lo + hi) // 2))
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            os.write(fd, b"".join(EVENT.pack(0, 0, EV_ABS, c, v) for c, v, _ in axes) +
                     EVENT.pack(0, 0, EV_SYN, 0, 0))
            time.sleep(0.002)
        os.write(fd, b"".join(EVENT.pack(0, 0, EV_ABS, c, mid) for c, _, mid in axes) +
                 EVENT.pack(0, 0, EV_SYN, 0, 0))
    except OSError as e:
        raise Refused(503, "Стик не принял движение: %s" % e)
    finally:
        os.close(fd)


def allowed_net():
    n = E("BARE_WEB_NET")
    if n is None:
        rc, out, _ = run([UNIT, "net"], timeout=5)
        n = out.strip() if rc == 0 and out.strip() else "192.168.7"
    return n


HOSTS = {"at": 0.0, "set": frozenset()}	# the device's own addresses, a while
HOSTS_LOCK = threading.Lock()
HOSTS_AGE = 5.0		# s: Wi-Fi may get its address later
ADDR_RE = re.compile(r"\binet (\d{1,3}(?:\.\d{1,3}){3})/")


def own_hosts():
    """the names a request of a page of this device has in its Host: the
    addresses of the device's interfaces (ip -o -4 addr: usb0's <net>.2,
    wlan0's if any, 127.0.0.1) and <net>.2"""
    now = time.monotonic()
    with HOSTS_LOCK:
        if now - HOSTS["at"] < HOSTS_AGE and HOSTS["set"]:
            return HOSTS["set"]
        rc, out, _ = run([IP, "-o", "-4", "addr", "show"], timeout=5)
        hosts = {"127.0.0.1", "%s.2" % NET}
        if rc == 0:
            hosts.update(ADDR_RE.findall(out))
        HOSTS["at"], HOSTS["set"] = now, frozenset(hosts)
        return HOSTS["set"]


def host_port(text, port):
    """("address", port) of a Host header or of an Origin's host; None if it
    is no address of the form a.b.c.d[:port]"""
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?", text or "")
    if not m:
        return None
    return m.group(1), int(m.group(2)) if m.group(2) else port


# the PIN of the addresses other than the USB computer's (Wi-Fi): bare_app
# writes it, this reads it at every check
PIN_FILE = os.path.join(DATA, "bare-web.pin")
PIN_RE = re.compile(r"\d{6}")
PIN_TRIES = 5		# wrong PINs in a row, then...
PIN_PAUSE = 60.0	# ...s none taken
SESSION_AGE = 86400	# s a session lasts
SESSION_COOKIE = "bare_web_session"
SESSIONS_MAX = 64	# the oldest dropped beyond
SESSIONS = {}		# token: (until (monotonic), the PIN it was given for)
# the wrong PINs of each client address: one in the same network cannot keep the
# PIN closed for everyone; at most PIN_ADDRS of them kept, the one longest
# untouched dropped beyond
PIN_ADDRS = 64
PIN_STATE = {}		# address: {"wrong": in a row, "until": no PIN before (monotonic), "seen": last try}
PIN_LOCK = threading.Lock()


def current_pin():
    """the PIN in its file, None: none (no file, not six digits, a link)"""
    try:
        fd = os.open(PIN_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        text = os.read(fd, 64).decode("ascii", "replace").strip()
    except OSError:
        return None
    finally:
        os.close(fd)
    return text if PIN_RE.fullmatch(text) else None


def same_text(a, b):
    """a == b in the same time whatever differs"""
    if len(a) != len(b):
        return False
    d = 0
    for x, y in zip(a.encode(), b.encode()):
        d |= x ^ y
    return d == 0


# a stream (text/event-stream) asks again every so many seconds whether its
# request is still let in: a new PIN ends the streams of the old one's sessions
SSE_RECHECK = 5


def session_ok(cookie_header):
    """the request's session cookie is one this gave, not over, for the PIN
    there is now"""
    token = None
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == SESSION_COOKIE:
            token = v
    if not token:
        return False
    pin = current_pin()
    now = time.monotonic()
    with PIN_LOCK:
        s = SESSIONS.get(token)
        if not s:
            return False
        if now >= s[0] or pin is None or not same_text(pin, s[1]):
            del SESSIONS[token]
            return False
    return True


def pin_of(addr, now):
    """the count of wrong PINs of a client address (PIN_LOCK held): made if
    there is none, the longest untouched one dropped beyond PIN_ADDRS"""
    a = PIN_STATE.get(addr)
    if a is None:
        while len(PIN_STATE) >= PIN_ADDRS:
            del PIN_STATE[min(PIN_STATE, key=lambda k: PIN_STATE[k]["seen"])]
        a = PIN_STATE[addr] = {"wrong": 0, "until": 0.0, "seen": now}
    a["seen"] = now
    return a


def pin_try(given, addr):
    """(status, answer, token or None) of a PIN given from the client address addr"""
    pin = current_pin()
    now = time.monotonic()
    with PIN_LOCK:
        st = pin_of(addr, now)
        if now < st["until"]:
            wait = int(st["until"] - now + 0.999)
            return 429, {"error": "Слишком много неверных PIN. Подождите %d с." % wait, "wait": wait}, None
        if pin is None:
            return 503, {"error": "PIN ещё не задан: откройте на приставке Настройки → Система → "
                                  "«Приставка в браузере»."}, None
        if not isinstance(given, str) or not same_text(pin, given.strip()):
            st["wrong"] += 1
            if st["wrong"] >= PIN_TRIES:
                st["wrong"] = 0
                st["until"] = now + PIN_PAUSE
                wait = int(PIN_PAUSE)
                return 429, {"error": "Неверный PIN. Слишком много попыток: подождите %d с." % wait,
                             "wait": wait}, None
            left = PIN_TRIES - st["wrong"]
            return 403, {"error": "Неверный PIN. Осталось попыток: %d." % left, "left": left}, None
        st["wrong"] = 0
        for t in [t for t, s in SESSIONS.items() if now >= s[0]]:
            del SESSIONS[t]
        while len(SESSIONS) >= SESSIONS_MAX:
            del SESSIONS[min(SESSIONS, key=lambda t: SESSIONS[t][0])]
        token = os.urandom(24).hex()
        SESSIONS[token] = (now + SESSION_AGE, pin)
    log.info("PIN: a session given")
    return 200, {"ok": True}, token


PIN_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Приставка: PIN</title>
<style>
body{font-family:system-ui,sans-serif;background:#16181d;color:#e8e8e8;display:flex;
justify-content:center;margin:0;padding-top:12vh}
main{max-width:26em;padding:1.5em}
h1{font-size:1.4em}
input{font-size:2em;width:7ch;letter-spacing:.2em;text-align:center;padding:.2em}
button{font-size:1.2em;margin-left:.5em;padding:.4em 1em}
#msg{min-height:1.5em;color:#f0a050}
p{line-height:1.4}
</style></head><body><main>
<h1>Приставка в браузере по Wi-Fi</h1>
<p>Введите PIN из шести цифр. Он на экране приставки:
Настройки → Система → «Приставка в браузере».</p>
<form id="f"><input id="pin" inputmode="numeric" autocomplete="off" maxlength="6"
pattern="[0-9]{6}" autofocus><button>Войти</button></form>
<p id="msg"></p>
<p>По кабелю USB PIN не нужен.</p>
</main><script>
document.getElementById("f").onsubmit = async e => {
  e.preventDefault();
  const msg = document.getElementById("msg");
  msg.textContent = "";
  try {
    const r = await fetch("/api/pin", {method: "POST", headers: {"Content-Type": "application/json",
      "X-Requested-With": "bare-web"}, body: JSON.stringify({pin: document.getElementById("pin").value})});
    let j = null;
    try { j = await r.json(); } catch (x) {}
    if (r.ok) { location.reload(); return; }
    msg.textContent = (j && j.error) || ("Ошибка " + r.status);
  } catch (x) {
    msg.textContent = "Приставка не отвечает.";
  }
};
</script></body></html>
"""


# ---- a game deleted from the card (POST /api/game/FOLDER/delete) ---------------

class Busy(Exception):
    pass


def lock_now(path):
    """the flock of another program's lock file taken (its fd), Busy if that
    program holds it"""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Busy(path) from None
    return fd


def mounts_in(top):
    """the mount points at or under top (realpath)"""
    out = []
    for line in (read(MOUNTS, 1 << 20) or "").splitlines():
        f = line.split()
        if len(f) < 2:
            continue
        m = f[1].replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")
        if m == top or m.startswith(top + "/"):
            out.append(m)
    return out


def walk_up(top, dev):
    """(path, is_dir) of everything under top and top itself, a directory after
    what is in it; no link followed (a link is an entry of its own), a
    directory of another file system (dev differs) OSError EXDEV"""
    stack = [[top, None]]
    while stack:
        d = stack[-1]
        if d[1] is None:
            with os.scandir(d[0]) as it:
                d[1] = list(it)
        if d[1]:
            e = d[1].pop()
            if e.is_dir(follow_symlinks=False):
                if e.stat(follow_symlinks=False).st_dev != dev:
                    raise OSError(errno.EXDEV, "другая файловая система", e.path)
                stack.append([e.path, None])
            else:
                yield e.path, False
        else:
            stack.pop()
            yield d[0], True


def game_folder(folder):
    """the game's folder on the card to delete: (its path, its name), or
    Refused: only a folder of its own right under the card (no link, the
    realpath's parent the card's), with its wine.ini or game.ini, not a
    built-in game's"""
    if not safe_name(folder):
        raise Refused(400, "Имя игры не подходит: %s" % folder)
    if folder in [b[1] for b in BUILT_IN] or folder in [b[0] for b in BUILT_IN]:
        raise Refused(400, "Встроенные игры с сайта не удаляются.")
    top = os.path.join(GAMES, folder)
    try:
        st = os.lstat(top)
    except OSError:
        raise Refused(404, "Такой игры нет: %s" % folder) from None
    if not stat.S_ISDIR(st.st_mode):
        raise Refused(400, "/games/%s — ссылка или файл, а не папка игры: не удаляю." % folder)
    card = os.path.realpath(GAMES)
    if os.path.dirname(os.path.realpath(top)) != card:
        raise Refused(400, "/games/%s не на карте игр: не удаляю." % folder)
    for ini in ("wine.ini", "game.ini"):
        try:
            if stat.S_ISREG(os.lstat(os.path.join(top, ini)).st_mode):
                return top, ini_name(os.path.join(top, ini)) or folder
        except OSError:
            pass
    raise Refused(404, "В /games/%s нет игры (wine.ini или game.ini)." % folder)


DELETE_STEP = 0.5	# s between the delete's progress lines


def deleting_path(folder):
    """the mark of a game being deleted, for bare_app (it does not start that
    game while the mark's pid lives): <run>/deleting/FOLDER, None without a run
    directory"""
    return os.path.join(RUN, "deleting", folder) if RUN else None


def deleting_mark(folder):
    p = deleting_path(folder)
    if not p:
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".new", "w") as f:
        f.write("%d\n" % os.getpid())
    os.replace(p + ".new", p)


def deleting_unmark(folder):
    p = deleting_path(folder)
    try:
        if p:
            os.remove(p)
    except FileNotFoundError:
        pass


def delete_work(folder, top, name, lock_fd):
    def work(job):
        try:
            dev = os.lstat(top).st_dev
            job.emit("step", n=1, m=2, text="считаю файлы")
            try:
                total = sum(1 for _ in walk_up(top, dev))
            except OSError as e:
                job.emit("fail", code="error", arg=str(e),
                         text="Игра не удалена: %s (%s)." % (e.strerror or e, e.filename or top))
                return
            job.emit("step", n=2, m=2, text="удаляю %d файлов и папок" % total)
            done, last, bad = 0, time.monotonic(), None
            with CardWriting():
                for path, is_dir in walk_up(top, dev):
                    try:
                        (os.rmdir if is_dir else os.unlink)(path)
                    except OSError as e:
                        bad = e
                        break
                    done += 1
                    if time.monotonic() - last >= DELETE_STEP:
                        last = time.monotonic()
                        job.emit("progress", percent=min(99, done * 100 // max(total, 1)))
            if bad:
                log.warning("delete %s: %s", top, bad)
                job.emit("fail", code="error", arg=str(bad),
                         text="Игра удалена не до конца: %s (%s)." % (bad.strerror or bad, bad.filename or top))
                return
            log.info("delete %s: %d entries removed", top, done)
            job.emit("done", folder=folder, title=name,
                     text="Игра «%s» удалена с карты. Сохранения остались в памяти приставки, правки "
                          "Мастерской — в /games/recipes." % name)
        except CardError as e:
            job.emit("fail", code="card", arg=str(e), text="Игра не удалена: %s" % e)
        finally:
            deleting_unmark(folder)
            os.close(lock_fd)
            with SIZES_LOCK:
                SIZES.pop(folder, None)
            if games_json():
                ctl("reload " + folder)
    return work


NET = None
UPLOADS = set()	# (place, name) being uploaded: one at a time each
UPLOADS_LOCK = threading.Lock()
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
         ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "bare-web"
    timeout = 120	# a computer that went away mid-upload: the request ends
    pin_only = False	# gate(): no session of the PIN, only its page and POST /api/pin

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/api/status", "/api/job", "/api/state", "/api/shot.png")):
            log.info("%s %s", self.client_address[0], fmt % args)

    # ---- answers
    def send(self, code, body, ctype="application/json; charset=utf-8", headers=(), cache="no-store"):
        if isinstance(body, str):
            body = body.encode()
        if getattr(self, "unread", False):
            self.close_connection = True
            headers = tuple(headers) + (("Connection", "close"),)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False))

    def fail(self, status, text, **more):
        more.update(error=text)
        self.json(more, status)

    def file(self, path, ctype, download=None):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.fail(404, "Файла нет: %s" % os.path.basename(path))
        h = []
        if download:
            q = urllib.parse.quote(download)
            h.append(("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s" %
                      (download.encode("ascii", "replace").decode().replace('"', "_"), q)))
        self.send(200, body, ctype, h)

    def ctype(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    def body_json(self):
        """the body as a JSON object; None if it is not one, or not sent as
        application/json (a form of another site cannot send that)"""
        if self.body and self.ctype() != "application/json":
            return None
        try:
            v = json.loads(self.body or b"{}")
        except ValueError:
            return None
        return v if isinstance(v, dict) else None

    # ---- the request
    def still_in(self):
        """a stream's request still let in (the USB computer, or its session
        holds: not for a PIN that is no more)"""
        return self.allowed() or session_ok(self.headers.get("Cookie"))

    def allowed(self):
        ip = self.client_address[0]
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        return ip == "127.0.0.1" or ip.startswith(NET + ".")

    def gate(self):
        """(code, text) why this request is not answered, None: it is.
        Only the USB computer (and the device itself); Host one of the
        device's addresses (a name of another site that resolves here, DNS
        rebinding, is not); Origin, when a browser sends one, this page's;
        a request that changes anything without Origin only from this
        page's script (X-Requested-With: bare-web) or as JSON: a form or
        an image of another site can send neither. A body of chunks
        (Transfer-Encoding) is not read here: refused, the connection closed
        (what follows it would be read as the next request)"""
        if self.headers.get_all("Transfer-Encoding"):
            self.unread = True	# Connection: close
            if self.headers.get("Content-Length") is None:
                return 411, "Нужен Content-Length: тело частями (chunked) не принимается."
            return 400, "Transfer-Encoding вместе с Content-Length: отказано."
        port = self.server.server_address[1]
        hosts = self.headers.get_all("Host") or []
        h = host_port(hosts[0], 80) if len(hosts) == 1 else None
        if not h or h[0] not in own_hosts() or h[1] != port:
            return 421, "Откройте страницу по адресу приставки (http://%s.2)." % NET
        origin = self.headers.get("Origin")
        if origin is not None:
            o = host_port(origin[7:], 80) if origin.startswith("http://") else None
            if o != h:
                return 403, "Запрос со страницы другого сайта: отказано."
        elif self.command not in ("GET", "HEAD"):
            if self.headers.get("X-Requested-With") != "bare-web" and self.ctype() != "application/json":
                return 403, "Запрос не со страницы приставки: отказано."
        # an address other than the USB computer's and the device's: the PIN
        if self.allowed() or session_ok(self.headers.get("Cookie")):
            return None
        path = urllib.parse.urlsplit(self.path).path
        if (self.command in ("GET", "HEAD") and path != "/api" and not path.startswith("/api/")) or \
                (self.command == "POST" and path == "/api/pin"):
            self.pin_only = True
            return None
        return 401, "Нужен PIN: откройте http://%s/ и введите PIN с экрана приставки." % hosts[0]

    def parts(self):
        u = urllib.parse.urlsplit(self.path)
        segs = [urllib.parse.unquote(s) for s in u.path.split("/")[1:]]
        return segs, urllib.parse.parse_qs(u.query)

    def route(self):
        m = self.command
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        # a body not read (a PUT's until its handler reads it): the answer
        # closes the connection, what is left of it is no next request
        self.unread = n != 0
        self.pin_only = False
        no = self.gate()
        if no:
            self.close_connection = True
            return self.fail(*no)
        segs, q = self.parts()
        # a body other than an upload's read whole first
        self.body = b""
        if m != "PUT":
            if not 0 <= n <= 1 << 16:
                return self.fail(413, "?")
            self.body = self.rfile.read(n)
            self.unread = False
        if self.pin_only:	# no session of the PIN: its page, or the PIN given
            if m == "POST":
                return self.api_post_pin(segs[1:], q)
            return self.send(401, PIN_PAGE, "text/html; charset=utf-8")
        if not segs or segs[0] != "api":
            if m in ("GET", "HEAD"):
                return self.static(segs)
            return self.fail(405, "?")
        name = "_".join([m.lower()] + [s.replace(".", "_") for s in segs[1:3]
                                       if re.fullmatch(r"[a-z]+(\.png|\.ts)?", s or "")])
        for n in (name, "_".join(name.split("_")[:2])):
            h = getattr(self, "api_" + n, None)
            if h:
                return h(segs[1:], q)
        return self.fail(404, "Нет такого запроса: %s %s" % (m, self.path))

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_DELETE(self):
        self.route()

    def do_PUT(self):
        self.route()

    def handle_expect_100(self):
        # an upload that will be refused is refused before its body comes
        self.unread = True
        no = self.gate()
        if no:
            self.fail(*no)
            return False
        if self.command == "PUT":
            segs, _ = self.parts()
            if segs[:2] == ["api", "recipe"]:
                why = None	# small: read whole (api_put_recipe)
            elif segs[:3] == ["api", "saves", "upload"]:
                why = self.saves_upload_problem(segs[3:])
            else:
                why = self.upload_problem(segs[2:] if segs[:2] == ["api", "upload"] else None)
            if why:
                self.close_connection = True
                self.fail(*why)
                return False
        return super().handle_expect_100()

    def static(self, segs):
        name = "/".join(segs) or "index.html"
        if not all(safe_name(s) for s in segs if s) or name.endswith("/"):
            return self.fail(404, "?")
        p = os.path.join(STATIC, name)
        if not os.path.isfile(p):
            p = os.path.join(STATIC, "index.html") if "." not in name else p
        if name in REVALIDATED:
            return self.revalidated(p, TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))
        self.file(p, TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))

    def revalidated(self, path, ctype):
        """a big file that seldom changes (mpegts.js, 273 KB on every check of a
        game): kept by the browser, asked again each time (no-cache) by its
        ETag, the md5 of the file (a new one after an update), 304 if the same"""
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.fail(404, "Файла нет: %s" % os.path.basename(path))
        tag = '"%s"' % hashlib.md5(body).hexdigest()
        asked = [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]
        if tag in asked or "*" in asked:
            return self.send(304, b"", ctype, (("ETag", tag),), cache="no-cache")
        self.send(200, body, ctype, (("ETag", tag),), cache="no-cache")

    # ---- the PIN (an address other than the USB computer's)
    def api_post_pin(self, segs, q):
        d = self.body_json()
        if d is None:
            return self.fail(400, "Нужен JSON {pin}.")
        code, answer, token = pin_try(d.get("pin"), self.client_address[0])
        h = ()
        if token:
            h = (("Set-Cookie", "%s=%s; Max-Age=%d; Path=/; HttpOnly; SameSite=Strict" %
                  (SESSION_COOKIE, token, SESSION_AGE)),)
        self.send(code, json.dumps(answer, ensure_ascii=False), headers=h)

    # ---- status
    def api_get_status(self, segs, q):
        self.json(status())

    # ---- uploads
    def upload_problem(self, rest):
        """(code, text) why an upload to rest ([PLACE, NAME]) is refused, None"""
        if not rest or len(rest) != 2 or rest[0] not in PLACES:
            return 404, "Загружать можно только в install, redist и updates."
        if not card_name_ok(rest[1]):
            return 400, NAME_BAD % rest[1]
        why = card_problem()
        if why:
            return 503, why
        try:
            n = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            return 411, "Нужен размер файла (Content-Length)."
        room = df(GAMES)
        if room and (room["free_mb"] << 20) < n + ROOM_LEFT:
            return 507, "На карте игр не хватает места: нужно %d МБ, свободно %d МБ." % (
                ((n + ROOM_LEFT) >> 20) + 1, room["free_mb"])
        return None

    def api_put_upload(self, segs, q):
        why = self.upload_problem(segs[1:])
        if why:
            self.close_connection = True	# its body is not read
            return self.fail(*why)
        place, name = segs[1], segs[2]
        n = int(self.headers["Content-Length"])
        with UPLOADS_LOCK:
            busy = (place, name) in UPLOADS
            UPLOADS.add((place, name))
        if busy:
            self.close_connection = True
            return self.fail(409, "Файл %s уже загружается." % name)
        try:
            self.upload(place, name, n)
        finally:
            with UPLOADS_LOCK:
                UPLOADS.discard((place, name))

    def upload(self, place, name, n):
        d = os.path.join(GAMES, place)
        dest = os.path.join(d, name)
        part = dest + ".part"
        got = 0
        renamed = False
        t0 = time.time()
        try:
            with CardWriting():
                os.makedirs(d, exist_ok=True)
                if os.path.isdir(dest):
                    self.close_connection = True
                    return self.fail(409, "На карте уже есть папка %s." % name)
                buf = bytearray(CHUNK)
                mv = memoryview(buf)
                with open(part, "wb") as f:
                    try:
                        while got < n:
                            k = self.rfile.readinto(mv[:min(CHUNK, n - got)])
                            if not k:
                                break
                            f.write(mv[:k])
                            got += k
                        if got == n:
                            self.unread = False
                            f.flush()
                            os.fsync(f.fileno())
                            # renamed while still open: the card stays writable
                            # for it (a remount to read-only fails while a file
                            # is open for writing)
                            os.replace(part, dest)
                            renamed = True
                    finally:
                        if not renamed:
                            try:
                                os.remove(part)	# never a whole file's name for a part
                            except OSError:
                                pass
        except CardError as e:
            self.close_connection = True
            return self.fail(503, str(e))
        except OSError as e:
            self.close_connection = True
            log.warning("upload %s: %s after %d of %d bytes", dest, e, got, n)
            if got == n:
                return self.fail(500, "Не удалось записать %s: %s" % (name, e.strerror or e))
            return self.fail(400, "Файл %s пришёл не целиком." % name) if not isinstance(
                e, (TimeoutError, ConnectionError)) else None
        if got != n:
            self.close_connection = True
            log.warning("upload %s: %d of %d bytes, dropped", dest, got, n)
            return self.fail(400, "Файл %s пришёл не целиком (%d из %d байт)." % (name, got, n))
        s = max(time.time() - t0, 0.001)
        log.info("upload %s: %d bytes in %.1f s (%.1f MB/s)", dest, n, s, n / s / 1e6)
        self.json({"ok": True, "path": dest, "size": n, "seconds": round(s, 2)})

    def api_get_files(self, segs, q):
        if len(segs) != 2 or segs[1] not in PLACES:
            return self.fail(404, "?")
        self.json({"files": files(segs[1]), "problem": card_problem()})

    def api_delete_files(self, segs, q):
        if len(segs) != 3 or segs[1] not in PLACES or not safe_name(segs[2]):
            return self.fail(404, "?")
        place, name = segs[1], segs[2]
        # install entries go with game-install remove (with their .bin parts)
        if not (name.endswith(".part") or (place == "updates" and name.endswith(".upd"))):
            return self.fail(400, "Так удаляются только файлы обновлений и недогруженные файлы (.part).")
        why = card_problem()
        if why:
            return self.fail(503, why)
        p = os.path.join(GAMES, place, name)
        if not os.path.isfile(p) or os.path.islink(p):
            return self.fail(404, "Файла нет: %s" % name)
        try:
            with CardWriting():
                os.remove(p)
        except (CardError, OSError) as e:
            return self.fail(500, "Не удалось удалить %s: %s" % (name, e))
        self.json({"ok": True})

    # ---- installing
    def api_get_install(self, segs, q):
        if segs[1:] != ["scan"]:
            return self.fail(404, "?")
        why = card_problem()
        if why:
            return self.json({"ok": False, "error": why, "entries": [], "problem": why})
        r = scan()
        r["redist"] = [f["name"] for f in files("redist")]
        self.json(r)

    def entry_ok(self, path):
        install = os.path.join(GAMES, "install")
        return (isinstance(path, str) and os.path.dirname(path) == install and
                safe_name(os.path.basename(path)) and os.path.lexists(path))

    def api_post_install(self, segs, q):
        what = segs[1:] if len(segs) > 1 else []
        b = self.body_json()
        if b is None or what not in (["run"], ["remove"]):
            return self.fail(400, "?")
        path = b.get("path")
        why = card_problem()
        if why:
            return self.fail(503, why)
        if not self.entry_ok(path):
            return self.fail(404, install_text("gone", "", what == ["remove"]))
        if what == ["remove"]:
            if Jobs.running("install"):
                return self.fail(409, install_text("busy", "", True), code="busy")
            rc, out, err = run([GAME_INSTALL, "remove", path], timeout=600)
            log.info("game-install remove %s: %s %s", path, out.strip(), err.strip())
            for line in out.splitlines():
                w = line.split(" ", 2)
                if w[0] == "fail":
                    code, arg = (w[1] if len(w) > 1 else "error"), (w[2] if len(w) > 2 else "")
                    return self.fail(409 if code == "busy" else 500, install_text(code, arg, True), code=code)
            if rc:
                msg = err.strip().splitlines()[-1] if err.strip() else "код выхода %d" % rc
                return self.fail(500, install_text("error", msg, True), code="error")
            return self.json({"ok": True, "text": "«%s» удалено из папки install." % os.path.basename(path)})
        argv = [GAME_INSTALL, "install", path]
        if b.get("replace"):
            argv.append("--replace")
        exe = b.get("exe")
        if exe:
            if not isinstance(exe, str) or exe.startswith("/") or ".." in exe.split("/"):
                return self.fail(400, "Программа не подходит: %s" % exe)
            argv += ["--exe", exe]
            title = b.get("title")
            if isinstance(title, str) and title.strip():
                argv += ["--title", title.strip()]
        title = b.get("title") or os.path.basename(path)
        job = Jobs.start("install", title, self.after_install(install_work(argv)))
        if not job:
            return self.fail(409, "Уже идёт другое задание (установка или обновление), дождитесь его.",
                             code="busy")
        log.info("job %d: %s", job.id, " ".join(argv))
        self.json({"ok": True, "job": job.id})

    @staticmethod
    def after_install(work):
        def w(job):
            try:
                work(job)
            finally:
                forget_sizes()
        return w

    # ---- games and logs
    def api_get_games(self, segs, q):
        self.json({"games": games(), "problem": None if card_mounted() else NO_CARD})

    def api_get_logs(self, segs, q):
        if len(segs) == 3 and safe_name(segs[1]) and segs[2] == "live":
            return self.log_live(segs[1])
        if len(segs) != 3 or not safe_name(segs[1]) or segs[2] not in ("1", "2", "3"):
            return self.fail(404, "?")
        p = os.path.join(LOGS, segs[1], segs[2] + ".log")
        dl = "%s-%s.log" % (segs[1], segs[2]) if q.get("download") else None
        self.file(p, "text/plain; charset=utf-8", dl)

    # ---- reports
    def api_post_report(self, segs, q):
        """{game}: bare-report [GAME]; where it wrote the report (the page
        then downloads it: GET /api/reports/WHERE/NAME?download=1)"""
        b = self.body_json()
        if b is None or len(segs) != 1:
            return self.fail(400, "?")
        game = b.get("game") or ""
        if not isinstance(game, str) or (game and not safe_name(game)):
            return self.fail(400, "Имя игры не подходит: %s" % game)
        rc, out, err = run([BARE_REPORT] + ([game] if game else []), timeout=120)
        path = out.strip().splitlines()[-1] if out.strip() else ""
        if rc or not path or not os.path.isfile(path):
            return self.fail(500, "Отчёт не получился: %s" % (err.strip() or "код выхода %d" % rc))
        where = next((w for w, d in REPORT_DIRS.items() if os.path.dirname(path) == d()), None)
        if not where or not self.report_path(["", where, os.path.basename(path)]):
            return self.fail(500, "Отчёт записан не туда: %s" % path)
        log.info("report %s", path)
        self.json({"ok": True, "where": where, "name": os.path.basename(path)})

    def api_get_reports(self, segs, q):
        if len(segs) == 1:
            return self.json({"reports": reports()})
        p = self.report_path(segs)
        if not p:
            return self.fail(404, "?")
        self.file(p, "text/plain; charset=utf-8", segs[2] if q.get("download") else None)

    def report_path(self, segs):
        if len(segs) != 3 or segs[1] not in REPORT_DIRS or not safe_name(segs[2]) or not segs[2].endswith(".txt"):
            return None
        return os.path.join(REPORT_DIRS[segs[1]](), segs[2])

    def api_delete_reports(self, segs, q):
        p = self.report_path(segs)
        if not p or not os.path.isfile(p) or os.path.islink(p):
            return self.fail(404, "Такого отчёта нет.")
        try:
            if segs[1] == "card":
                why = card_problem()
                if why:
                    return self.fail(503, why)
                with CardWriting():
                    os.remove(p)
            else:
                os.remove(p)
        except (CardError, OSError) as e:
            return self.fail(500, "Не удалось удалить отчёт: %s" % e)
        self.json({"ok": True})

    # ---- saved games (bare-backup)
    def stream(self, path, ctype, download):
        """a file as it is read: a copy may be large"""
        try:
            f = open(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb")
        except OSError:
            return self.fail(404, "Файла нет: %s" % os.path.basename(path))
        with f:
            n = os.fstat(f.fileno()).st_size
            q = urllib.parse.quote(download)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(n))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s" %
                             (download.encode("ascii", "replace").decode().replace('"', "_"), q))
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                for b in iter(lambda: f.read(CHUNK), b""):
                    self.wfile.write(b)
            except (ConnectionError, TimeoutError):
                self.close_connection = True

    def backup_err(self, rc, err, what):
        text = err.strip().splitlines()[-1] if err.strip() else "код выхода %d" % rc
        text = text[len("bare-backup: "):] if text.startswith("bare-backup: ") else text
        code = 409 if rc in (3, 4) else 400 if rc == 2 else 500
        return self.fail(code, "%s: %s" % (what, text))

    def copy_path(self, where, name):
        """a copy of saved games there: a file of its own (not a link, nor
        in a directory that is one)"""
        if not isinstance(where, str) or where not in SAVES_DIRS or not isinstance(name, str) or \
                not safe_name(name) or not SAVES_NAME.match(name):
            return None
        d = SAVES_DIRS[where]
        p = os.path.join(d, name)
        if os.path.islink(d) or os.path.islink(p) or not os.path.isfile(p):
            return None
        return p

    def api_get_saves(self, segs, q):
        if len(segs) == 1:
            rc, out, err = run([BARE_BACKUP, "list"], timeout=120)
            if rc:
                return self.backup_err(rc, err, "Список сохранений")
            try:
                return self.json(json.loads(out))
            except ValueError:
                return self.fail(500, "bare-backup list: не JSON")
        if segs[1] == "copy" and len(segs) == 4:
            p = self.copy_path(segs[2], segs[3])
            if not p:
                return self.fail(404, "Такой копии нет.")
            return self.stream(p, "application/zip", segs[3])
        return self.fail(404, "?")

    def api_delete_saves(self, segs, q):
        if len(segs) != 4 or segs[1] != "copy":
            return self.fail(404, "?")
        p = self.copy_path(segs[2], segs[3])
        if not p:
            return self.fail(404, "Такой копии нет.")
        try:
            if segs[2] == "card":
                why = card_problem()
                if why:
                    return self.fail(503, why)
                with CardWriting():
                    os.remove(p)
            else:
                os.remove(p)
        except (CardError, OSError) as e:
            return self.fail(500, "Не удалось удалить копию: %s" % e)
        log.info("saves: %s deleted", p)
        self.json({"ok": True})

    def saves_upload_problem(self, rest):
        if not rest or len(rest) != 1 or not SAVES_NAME.match(rest[0]):
            return 400, "Это не копия сохранений: имя должно быть saves-….zip."
        if not card_name_ok(rest[0]):
            return 400, NAME_BAD % rest[0]
        try:
            n = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            return 411, "Нужен размер файла (Content-Length)."
        if n > SAVES_MAX:
            return 413, "Файл слишком большой для копии сохранений."
        room = df(DATA)
        if room and (room["free_mb"] << 20) < n + ROOM_LEFT:
            return 507, "В памяти приставки не хватает места: свободно %d МБ." % room["free_mb"]
        return None

    def api_put_saves(self, segs, q):
        if segs[1:2] != ["upload"]:
            self.close_connection = True
            return self.fail(404, "?")
        why = self.saves_upload_problem(segs[2:])
        if why:
            self.close_connection = True
            return self.fail(*why)
        name, n = segs[2], int(self.headers["Content-Length"])
        d = SAVES_DIRS["data"]
        dest = os.path.join(d, name)
        part = os.path.join(d, "." + name + ".part")
        got = 0
        with UPLOADS_LOCK:
            busy = ("saves", name) in UPLOADS
            UPLOADS.add(("saves", name))
        if busy:
            self.close_connection = True
            return self.fail(409, "Файл %s уже загружается." % name)
        try:
            os.makedirs(d, exist_ok=True)
            with open(part, "wb") as f:
                while got < n:
                    b = self.rfile.read(min(CHUNK, n - got))
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
                f.flush()
                os.fsync(f.fileno())
            if got != n:
                raise OSError("%d of %d bytes" % (got, n))
            self.unread = False
            os.replace(part, dest)
        except (OSError, ValueError) as e:
            self.close_connection = True
            try:
                os.remove(part)
            except OSError:
                pass
            log.warning("saves upload %s: %s", name, e)
            return self.fail(400, "Копия %s пришла не целиком." % name)
        finally:
            with UPLOADS_LOCK:
                UPLOADS.discard(("saves", name))
        log.info("saves upload %s: %d bytes", dest, n)
        self.json({"ok": True, "where": "data", "name": name, "size": n})

    def api_post_saves(self, segs, q):
        b = self.body_json()
        if b is None or len(segs) != 2 or segs[1] not in ("info", "restore", "backup"):
            return self.fail(400, "?")
        if segs[1] == "backup":
            # {game: FOLDER|"all"}: the copy made; the page then downloads it
            # (GET /api/saves/copy/WHERE/NAME)
            what = b.get("game")
            if not isinstance(what, str) or (what != "all" and not safe_name(what)):
                return self.fail(400, "Имя игры не подходит: %s" % what)
            rc, out, err = run([BARE_BACKUP, "backup", what], timeout=900)
            path = out.strip().splitlines()[-1] if out.strip() else ""
            if rc or not path or not os.path.isfile(path):
                return self.backup_err(rc, err, "Копия не получилась")
            where = next((w for w, d in SAVES_DIRS.items() if os.path.dirname(path) == d), None)
            name = os.path.basename(path)
            if not where or not self.copy_path(where, name):
                return self.fail(500, "Копия записана не туда: %s" % path)
            log.info("saves %s: %s", what, path)
            return self.json({"ok": True, "where": where, "name": name, "size": os.path.getsize(path)})
        p = self.copy_path(b.get("where"), b.get("name") or "")
        if not p:
            return self.fail(404, "Такой копии нет.")
        if segs[1] == "info":
            rc, out, err = run([BARE_BACKUP, "info", p], timeout=60)
            if rc:
                return self.backup_err(rc, err, "Копия не читается")
            try:
                info = json.loads(out)
            except ValueError:
                return self.fail(500, "bare-backup info: не JSON")
            return self.json(info)
        game = b.get("game") or ""
        if game and not safe_name(game):
            return self.fail(400, "Имя игры не подходит: %s" % game)
        rc, out, err = run([BARE_BACKUP, "restore", p] + (["--game", game] if game else []), timeout=900)
        if rc:
            return self.backup_err(rc, err, "Не восстановлено")
        log.info("saves restored from %s%s", p, " (%s)" % game if game else "")
        try:
            r = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r = {}
        r["ok"] = True
        r["warnings"] = [l[len("bare-backup: "):] for l in err.splitlines() if l.startswith("bare-backup: ")]
        self.json(r)

    # ---- updates
    def api_get_update(self, segs, q):
        what = segs[1:]
        if what == ["files"]:
            return self.json({"files": update_files(), "problem": card_problem()})
        if what == ["state"]:
            return self.json(update_state())
        if what == ["info"]:
            f = (q.get("file") or [""])[0]
            if not update_file_ok(f):
                return self.fail(404, "Такого файла обновления нет.")
            rc, out, err = run([SYSTEM_UPDATE, "--info", f], timeout=300)
            if rc:
                return self.fail(400, (err.strip() or "?").replace("system-update: ", ""))
            return self.json({"ok": True, "info": kv(out), "text": out})
        self.fail(404, "?")

    def api_post_update(self, segs, q):
        what = segs[1:]
        if what == ["run"]:
            b = self.body_json() or {}
            f = b.get("file")
            if not update_file_ok(f):
                return self.fail(404, "Такого файла обновления нет.")
            job = Jobs.start("update", os.path.basename(f), update_work(f))
            if not job:
                return self.fail(409, "Уже идёт другое задание (установка или обновление), дождитесь его.",
                                 code="busy")
            log.info("job %d: system-update %s", job.id, f)
            return self.json({"ok": True, "job": job.id})
        if what == ["switch"]:
            if Jobs.running():
                return self.fail(409, "Идёт задание: дождитесь его окончания.", code="busy")
            st = ab_state()
            run_slot = st.get("running")
            if run_slot not in ("a", "b"):
                return self.fail(400, "Система работает не из слота A/B.")
            other = "b" if run_slot == "a" else "a"
            rc, v, _ = run([AB_STATE, "version", other], timeout=30)
            if rc or not v.strip():
                return self.fail(400, "Запасной системы нет.")
            rc, _, err = run([AB_STATE, "try", other], timeout=30)
            if rc:
                return self.fail(500, "Не удалось выбрать запасную систему: %s" % err.strip())
            log.info("the other slot (%s, %s) from the next start: restarting", other, v.strip())
            self.json({"ok": True, "text": "Приставка перезагружается с запасной системой (%s)." % v.strip()})
            return self.reboot_later()
        self.fail(404, "?")

    def api_post_reboot(self, segs, q):
        if Jobs.running():
            return self.fail(409, "Идёт задание: дождитесь его окончания.", code="busy")
        self.json({"ok": True, "text": "Приставка перезагружается."})
        self.reboot_later()

    def reboot_later(self):
        def body():
            time.sleep(1)	# the answer reaches the computer first
            log.info("reboot")
            run([REBOOT], timeout=30)
        threading.Thread(target=body, daemon=True).start()

    # ---- jobs
    def api_get_job(self, segs, q):
        if len(segs) == 1:
            j = Jobs.current
            return self.json({"job": j.summary() if j else None})
        j = Jobs.current
        if len(segs) != 3 or segs[2] != "events" or not j or str(j.id) != segs[1]:
            return self.fail(404, "Такого задания нет.")
        self.events(j)

    def events(self, job):
        try:
            i = int(self.headers.get("Last-Event-ID", "-1")) + 1
        except ValueError:
            i = 0
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        check = time.monotonic() + SSE_RECHECK
        quiet = 0.0
        try:
            while True:
                if time.monotonic() >= check:
                    if not self.still_in():
                        return	# a new PIN: this session is over
                    check = time.monotonic() + SSE_RECHECK
                t0 = time.monotonic()
                with job.cond:
                    if i >= len(job.events) and not job.ended:
                        job.cond.wait(min(15, SSE_RECHECK))
                    new = job.events[i:]
                    ended = job.ended
                if new:
                    out = "".join("id: %d\ndata: %s\n\n" % (i + k, json.dumps(e, ensure_ascii=False))
                                  for k, e in enumerate(new))
                    i += len(new)
                    self.wfile.write(out.encode())
                    quiet = 0.0
                elif not ended:
                    quiet += time.monotonic() - t0
                    if quiet >= 15:	# as before: a word every 15 s at least
                        self.wfile.write(b": still running\n\n")
                        quiet = 0.0
                self.wfile.flush()
                if ended and i >= len(job.events):
                    return
        except OSError:
            return	# the page went away


    # ---- the workshop: a game's recipe and the layer of changes (stage 4)
    def api_get_schema(self, segs, q):
        acts, defs = wine_tables()
        s = dict(schema())
        s["actions"] = acts
        s["wine_defaults"] = defs
        s["start_select"] = (kv(read(RELEASE) or "").get("FIRMWARE") or "") != "ogu"
        self.json(s)

    def refused(self, e):
        return self.fail(e.status, str(e))

    def api_get_recipe(self, segs, q):
        if len(segs) != 2:
            return self.fail(404, "?")
        st = games_json()
        try:
            if not safe_name(segs[1]):
                raise Refused(400, "Имя игры не подходит: %s" % segs[1])
            g = game_entry(segs[1], st)
            if not g:
                raise Refused(404, "Такой игры нет: %s" % segs[1])
        except Refused as e:
            return self.refused(e)
        out = Recipe(g).describe(st)
        out["bare_app"] = st is not None
        self.json(out)

    def read_put_body(self):
        try:
            n = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            n = -1
        if not 0 <= n <= LAYER_MAX:
            self.close_connection = True
            raise Refused(413 if n > 0 else 411, "Нужно тело запроса до 64 КБ.")
        body = self.rfile.read(n)
        self.unread = len(body) != n
        return body

    def api_put_recipe(self, segs, q):
        try:
            body = self.read_put_body()
            if len(segs) != 3 or segs[2] != "layer":
                raise Refused(404, "?")
            r = recipe_of(segs[1])
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype == "application/json":
                try:
                    b = json.loads(body or b"{}")
                except ValueError:
                    raise Refused(400, "Тело — не JSON.")
                if not isinstance(b, dict) or not isinstance(b.get("sections"), dict):
                    raise Refused(400, "Нужно {\"sections\": {...}}.")
                desired = lower_sections(b["sections"])
            else:
                try:
                    desired = ini_sections(ini_parse(body.decode("utf-8"), strict=True))
                except (UnicodeDecodeError, IniError) as e:
                    raise Refused(400, "Текст правок не читается: %s" % e)
            errors, warnings = layer_check(r.kind, desired)
            if errors:
                return self.fail(400, "Правки не подходят: " + "; ".join(errors), errors=errors, warnings=warnings)
            entries = layer_diff(desired, ini_sections(r.base_entries()))
            with RECIPE_LOCK:
                told = put_layer(r, entries)
        except Refused as e:
            return self.refused(e)
        st = games_json()
        out = recipe_of(segs[1], st).describe(st)
        out.update(ok=True, warnings=warnings, reloaded=told, lines=len(entries))
        self.json(out)

    def api_delete_recipe(self, segs, q):
        try:
            if len(segs) != 3 or segs[2] != "layer":
                raise Refused(404, "?")
            r = recipe_of(segs[1])
            with RECIPE_LOCK:
                told = put_layer(r, [])
        except Refused as e:
            return self.refused(e)
        st = games_json()
        out = recipe_of(segs[1], st).describe(st)
        out.update(ok=True, reloaded=told)
        self.json(out)

    def api_post_recipe(self, segs, q):
        if len(segs) == 3 and segs[2] == "export":
            try:
                r = recipe_of(segs[1])
                data, name = export_zip(r, games_json())
            except Refused as e:
                return self.refused(e)
            return self.send(200, data, "application/zip",
                             (("Content-Disposition", "attachment; filename*=UTF-8''%s"
                               % urllib.parse.quote(name)),))
        try:
            if len(segs) != 3 or segs[2] != "adopt-controls":
                raise Refused(404, "?")
            st = games_json()
            r = recipe_of(segs[1], st)
            res = adopt_controls(r, st)
        except Refused as e:
            return self.refused(e)
        st = games_json()
        out = recipe_of(segs[1], st).describe(st)
        out.update(ok=True, **res)
        self.json(out)

    # ---- healing a game without a recipe (stage 8)
    def heal_game(self, segs):
        if len(segs) != 2:
            raise Refused(404, "?")
        if not safe_name(segs[1]):
            raise Refused(400, "Имя игры не подходит: %s" % segs[1])
        g = game_entry(segs[1])
        if not g:
            raise Refused(404, "Такой игры нет: %s" % segs[1])
        if g.get("kind") != "wine":
            raise Refused(400, "Исправлять так можно только игры Windows.")
        return g

    def api_get_heal(self, segs, q):
        try:
            g = self.heal_game(segs)
        except Refused as e:
            return self.refused(e)
        self.json({"folder": g["folder"], "suggestions": heal_suggestions(g["folder"])})

    def api_post_heal(self, segs, q):
        try:
            g = self.heal_game(segs)
            b = self.body_json() or {}
            kind, arg = b.get("kind"), b.get("arg")
            if kind not in ("dll", "writable") or not isinstance(arg, str) or not arg or len(arg) > 255 or \
                    any(ord(c) < 32 for c in arg):
                raise Refused(400, "Нужно {kind: dll|writable, arg}.")
            if running_game() == g["folder"]:
                raise Refused(409, "Игра идёт: сначала выйдите из неё.")
        except Refused as e:
            return self.refused(e)
        # writable: game-install writes the layer, one change of it at a time
        # with the workshop's (RECIPE_LOCK)
        with RECIPE_LOCK if kind == "writable" else NO_LOCK:
            rc, out, err = run([GAME_INSTALL, "heal", g["folder"], kind, arg], timeout=600)
        last = ([l for l in out.splitlines() if l.startswith(("done ", "fail "))] or ["fail error " + err.strip()])[-1]
        f = last.split(" ", 2) + ["", ""]
        if f[0] == "done":
            reloaded = ctl("reload " + g["folder"]) if kind == "writable" else None
            text = ("Библиотека положена в папку игры: %s." % f[2] if kind == "dll" else
                    "Игре разрешена запись: writable = %s (в правках рецепта). Действует со следующего запуска." % f[2])
            return self.json({"ok": True, "line": last, "text": text, "reloaded": reloaded})
        words = HEAL_WORDS.get(f[1], HEAL_WORDS["error"])
        return self.fail(409 if f[1] == "busy" else 400, words % f[2] if "%s" in words else words, line=last)

    # ---- the check of a game (stage 5)
    def api_get_state(self, segs, q):
        self.json(game_state())

    def api_post_game(self, segs, q):
        if len(segs) == 3 and segs[2] == "delete":
            return self.delete_game(segs[1])
        if len(segs) != 3 or segs[2] not in ("launch", "quit", "options"):
            return self.fail(404, "?")
        st = games_json()
        if not st:
            return self.fail(503, NO_BARE_APP)
        folder = segs[1]
        if not safe_name(folder) or not game_entry(folder, st):
            return self.fail(404, "Такой игры нет: %s" % folder)
        now = running_game(st)
        if segs[2] == "launch":
            if now and now != folder:
                return self.fail(409, "Идёт другая игра (%s): сначала выйдите из неё." % now)
            if now == folder:
                return self.json({"ok": True, "already": True})
            line = "launch " + folder
        elif segs[2] == "options":
            if now:
                return self.fail(409, "Идёт игра: её опции открываются, когда она закрыта.")
            line = "options " + folder
        else:
            line = "quit-game"
            release_all()
        if not ctl(line):
            return self.fail(503, NO_CTL)
        self.json({"ok": True})

    def delete_game(self, folder):
        why = card_problem()
        if why:
            return self.fail(503, why)
        try:
            top, name = game_folder(folder)
            inside = mounts_in(os.path.realpath(top))
            if inside:
                raise Refused(409, "В папке игры смонтирован другой диск (%s): не удаляю." % inside[0])
        except Refused as e:
            return self.refused(e)
        try:
            lock_fd = lock_now(INSTALL_LOCK)
        except Busy:
            return self.fail(409, "Приставка сейчас ставит, удаляет или исправляет игру: дождитесь, пока это "
                                  "закончится.", code="busy")
        except OSError as e:
            return self.fail(500, "Замок установки не открывается: %s" % e)
        try:
            os.close(lock_now(BACKUP_LOCK))	# only that no copy is made or restored now
        except Busy:
            os.close(lock_fd)
            return self.fail(409, "Сейчас делается или восстанавливается копия сохранений: дождитесь, пока это "
                                  "закончится.", code="busy")
        except OSError as e:
            os.close(lock_fd)
            return self.fail(500, "Замок копий не открывается: %s" % e)
        # the mark first, then whether it runs: bare_app does not start it after
        # the mark, a start before it is seen running
        try:
            deleting_mark(folder)
        except OSError as e:
            os.close(lock_fd)
            return self.fail(500, "Метка удаления не пишется: %s" % e)
        if running_game() == folder:
            deleting_unmark(folder)
            os.close(lock_fd)
            return self.fail(409, "Игра «%s» идёт: сначала выйдите из неё." % name)
        job = Jobs.start("delete", name, delete_work(folder, top, name, lock_fd))
        if not job:
            deleting_unmark(folder)
            os.close(lock_fd)
            return self.fail(409, "Уже идёт другое задание (установка, обновление или удаление), дождитесь его.",
                             code="busy")
        log.info("job %d: delete %s", job.id, top)
        self.json({"ok": True, "job": job.id})

    def api_get_shot_png(self, segs, q):
        try:
            w = int((q.get("w") or ["0"])[0])
        except ValueError:
            w = 0
        try:
            png = take_shot(max(0, min(w, 1920)))
        except Refused as e:
            return self.refused(e)
        self.send(200, png, "image/png")

    def api_post_pad(self, segs, q):
        b = self.body_json()
        if b is None or not isinstance(b.get("button"), str):
            return self.fail(400, "Нужно {button, down}.")
        try:
            pad_button(b["button"], bool(b.get("down")))
        except Refused as e:
            return self.refused(e)
        self.json({"ok": True})

    def api_post_stick(self, segs, q):
        b = self.body_json()
        try:
            if b is None or b.get("stick") not in ("stick", "rstick"):
                raise Refused(400, "Нужно {stick: stick|rstick, x, y, ms}.")
            x, y = float(b.get("x", 0)), float(b.get("y", 0))
            ms = int(b.get("ms", 300))
            if not (-1 <= x <= 1 and -1 <= y <= 1 and 20 <= ms <= 2000):
                raise Refused(400, "x, y от -1 до 1, ms от 20 до 2000.")
            stick_hold(b["stick"], x, y, ms)
        except (TypeError, ValueError):
            return self.fail(400, "x, y, ms — числа.")
        except Refused as e:
            return self.refused(e)
        self.json({"ok": True})

    def api_post_stream(self, segs, q):
        b = self.body_json()
        if b is None or not isinstance(b.get("on"), bool):
            return self.fail(400, "Нужно {on: true|false}.")
        if not ctl("stream on" if b["on"] else "stream off"):
            return self.fail(503, NO_CTL)
        self.json({"ok": True})

    def stream_dial(self):
        """the socket of bare_app's /live.ts, its head read: (sock, the
        bytes after the head) or (None, why)"""
        end = time.monotonic() + STREAM_WAIT
        while True:
            try:
                sock = socket.create_connection(("127.0.0.1", int(STREAM_PORT)), timeout=STREAM_QUIET)
                break
            except OSError:
                if time.monotonic() >= end:
                    return None, "Поток приставки не запущен (bare_app не открыл порт %s)." % STREAM_PORT
                time.sleep(0.2)
        try:
            sock.sendall(b"GET /live.ts HTTP/1.1\r\nHost: 127.0.0.1\r\nUser-Agent: bare-web\r\n\r\n")
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 4096:
                data = sock.recv(4096)
                if not data:
                    break
                head += data
        except OSError as e:
            sock.close()
            return None, "Поток приставки не ответил: %s" % e
        head, _, rest = head.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if not _ or not status.startswith(b"HTTP/1.1 200"):
            sock.close()
            return None, "Поток приставки отказал: %s" % status.decode("latin-1")[:80]
        return sock, rest

    def api_get_stream_ts(self, segs, q):
        """bare_app's stream passed on as it comes (each chunk as it is
        read: no buffer of its own); a browser that takes nothing for
        STREAM_QUIET s, bare_app gone, a new PIN: it ends"""
        if not STREAM_PORT:
            return self.fail(503, "Потока нет.")
        sock, rest = self.stream_dial()
        if not sock:
            return self.fail(503, rest)
        self.close_connection = True
        try:
            self.connection.settimeout(STREAM_QUIET)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command == "HEAD":
                return
            if rest:
                self.wfile.write(rest)
            check = time.monotonic() + SSE_RECHECK
            while True:
                data = sock.recv(1 << 16)
                if not data:
                    return	# bare_app's end
                self.wfile.write(data)
                if time.monotonic() >= check:
                    if not self.still_in():
                        return	# a new PIN: this session is over
                    check = time.monotonic() + SSE_RECHECK
        except OSError:
            return	# the page went away, or bare_app's side is quiet
        finally:
            sock.close()

    def log_live(self, game):
        """the launch log 1.log as it grows (text/event-stream): its last
        lines first, then each new one; the file begun anew (the next start)
        is read from its start"""
        p = os.path.join(LOGS, game, "1.log")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        ino, pos, rest, quiet = None, 0, b"", 0
        end = time.monotonic() + 3600
        check = time.monotonic() + SSE_RECHECK
        try:
            while time.monotonic() < end:
                if time.monotonic() >= check:
                    if not self.still_in():
                        return	# a new PIN: this session is over
                    check = time.monotonic() + SSE_RECHECK
                try:
                    st = os.stat(p)
                except OSError:
                    st = None
                out = []
                if st and (st.st_ino != ino or st.st_size < pos):
                    if ino is not None:
                        out.append({"reset": True})
                    first = ino is None
                    ino, pos, rest = st.st_ino, 0, b""
                    if first and st.st_size > 16384:
                        pos = st.st_size - 16384	# the end of what is there
                if st and st.st_size > pos:
                    with open(p, "rb") as f:
                        f.seek(pos)
                        data = f.read(min(st.st_size - pos, 1 << 20))
                    pos += len(data)
                    lines = (rest + data).split(b"\n")
                    rest = lines.pop()
                    out += [{"line": l.decode("utf-8", "replace")} for l in lines]
                if out:
                    self.wfile.write("".join("data: %s\n\n" % json.dumps(e, ensure_ascii=False)
                                             for e in out).encode())
                    self.wfile.flush()
                    quiet = 0
                else:
                    quiet += 1
                    if quiet >= 30:
                        self.wfile.write(b": quiet\n\n")
                        self.wfile.flush()
                        quiet = 0
                time.sleep(0.5)
        except OSError:
            return	# the page went away


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


def make_server(bind, port):
    global NET
    NET = allowed_net()
    # bare_app_wine's tables once, at the start
    threading.Thread(target=wine_tables, daemon=True).start()
    return Server((bind, port), Handler)


def setup_log():
    log.path = LOG


def main():
    setup_log()
    port = int(E("BARE_WEB_PORT", "80"))
    try:
        srv = make_server(E("BARE_WEB_BIND", "0.0.0.0"), port)
    except OSError as e:
        log.error("cannot listen on port %d: %s", port, e)
        sys.exit("bare-web: port %d: %s" % (port, e))
    log.info("listening on port %d (the network %s.*)", srv.server_address[1], NET)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
