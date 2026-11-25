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
                                   game.ini) and the built-in ones
  GET  /api/logs/GAME/N            /data/logs/GAME/N.log (N 1..3)
  GET  /api/report?game=GAME       bare-report [GAME], the file it wrote
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
  GET  /api/saves/FOLDER/backup    a copy of the game made (bare-backup backup),
                                   sent; GET /api/saves/all the same of all
  GET|DELETE /api/saves/copy/WHERE/NAME   one of the copies (WHERE card, data)
  PUT  /api/saves/upload/NAME      a copy from the computer into /data/backups
  POST /api/saves/info             {where, name}: its manifest (bare-backup info)
  POST /api/saves/restore          {where, name, game}: bare-backup restore;
                                   409 while the game runs
  GET  /api/job                    the job running or the last one
  GET  /api/job/ID/events          its lines (text/event-stream)

One job at a time (409 otherwise); game-install takes its own lock too
(/run/game-install.lock), so the device's install screen and this one do
not run two installs: "fail busy". The card is read-only: written to with
"mount -o remount,rw" while this server writes (a count of its writers),
read-only again after the last one, unless it was writable before.

Tests (scripts/test-bare-web.py) name other places: BARE_WEB_GAMES (then
the card is that directory as it is: no mount test, no remount),
BARE_WEB_DATA, BARE_WEB_LOGS, BARE_WEB_STATIC, BARE_WEB_LOG (the server's
log), BARE_WEB_POWER (/sys/class/power_supply), BARE_WEB_RELEASE, the
programs BARE_WEB_GAME_INSTALL, BARE_WEB_BARE_REPORT, BARE_WEB_SYSTEM_UPDATE,
BARE_WEB_AB_STATE, BARE_WEB_USB_DISK, BARE_WEB_UNIT, BARE_WEB_REBOOT,
BARE_WEB_UPDATE_LOCK, BARE_WEB_BARE_BACKUP, and BARE_WEB_NET (the network answered), BARE_WEB_PORT,
BARE_WEB_BIND.
"""
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse

E = os.environ.get
TEST = "BARE_WEB_GAMES" in os.environ	# the card: a directory of a test, as it is
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
SAVES_NAME = re.compile(r"^saves-[^/\\]+\.zip$")
SAVES_MAX = 4 << 30	# a copy uploaded: at most this
UPDATE_LOCK = E("BARE_WEB_UPDATE_LOCK", "/run/system-update.lock")	# system-update's own
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
    """with CardWriting(): the card writable inside (remounted rw if it is
    read-only); read-only again when the last writer of this server is done,
    if it was this server that made it writable"""
    lock = threading.Lock()
    users = 0
    ours = False

    def __enter__(self):
        c = CardWriting
        with c.lock:
            if c.users == 0:
                opts = card_opts()
                if opts is not None and "ro" in opts:
                    rc, _, err = run(["mount", "-o", "remount,rw", GAMES])
                    if rc:
                        log.warning("%s cannot be made writable: %s", GAMES, err.strip())
                        raise CardError(INSTALL_FAIL["card"])
                    c.ours = True
                    log.info("%s writable", GAMES)
            c.users += 1
        return self

    def __exit__(self, *exc):
        c = CardWriting
        with c.lock:
            c.users -= 1
            if c.users == 0 and c.ours:
                c.ours = False
                os.sync()
                rc, _, err = run(["mount", "-o", "remount,ro", GAMES])
                if rc:
                    log.warning("%s stays writable: %s", GAMES, err.strip())
                else:
                    log.info("%s read-only again", GAMES)
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
    for g in found.values():
        g["logs"] = logs_of(g["id"])
        g["last"] = g["logs"][0]["time"] if g["logs"] and g["logs"][0]["n"] == 1 else None
    return sorted(found.values(), key=lambda g: (-(g["last"] or 0), g["name"].lower()))


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

def allowed_net():
    n = E("BARE_WEB_NET")
    if n is None:
        rc, out, _ = run([UNIT, "net"], timeout=5)
        n = out.strip() if rc == 0 and out.strip() else "192.168.7"
    return n


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

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/api/status", "/api/job")):
            log.info("%s %s", self.client_address[0], fmt % args)

    # ---- answers
    def send(self, code, body, ctype="application/json; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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

    def body_json(self):
        try:
            v = json.loads(self.body or b"{}")
        except ValueError:
            return None
        return v if isinstance(v, dict) else None

    # ---- the request
    def allowed(self):
        ip = self.client_address[0]
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        return ip == "127.0.0.1" or ip.startswith(NET + ".")

    def parts(self):
        u = urllib.parse.urlsplit(self.path)
        segs = [urllib.parse.unquote(s) for s in u.path.split("/")[1:]]
        return segs, urllib.parse.parse_qs(u.query)

    def route(self):
        if not self.allowed():
            self.close_connection = True
            return self.fail(403, "Доступ только с компьютера на кабеле USB.")
        segs, q = self.parts()
        m = self.command
        # a body other than an upload's read whole first: what is left of
        # one would be the next request of the connection
        self.body = b""
        if m in ("POST", "DELETE"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= 1 << 16:
                self.close_connection = True
                return self.fail(413, "?")
            self.body = self.rfile.read(n)
        if not segs or segs[0] != "api":
            if m in ("GET", "HEAD"):
                return self.static(segs)
            return self.fail(405, "?")
        name = "_".join([m.lower()] + [s for s in segs[1:3] if re.fullmatch(r"[a-z]+", s or "")])
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
        if self.command == "PUT" and self.allowed():
            segs, _ = self.parts()
            if segs[:3] == ["api", "saves", "upload"]:
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
        self.file(p, TYPES.get(os.path.splitext(p)[1], "application/octet-stream"))

    # ---- status
    def api_get_status(self, segs, q):
        self.json(status())

    # ---- uploads
    def upload_problem(self, rest):
        """(code, text) why an upload to rest ([PLACE, NAME]) is refused, None"""
        if not rest or len(rest) != 2 or rest[0] not in PLACES:
            return 404, "Загружать можно только в install, redist и updates."
        if not safe_name(rest[1]):
            return 400, "Имя файла не подходит: %s" % rest[1]
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
        if len(segs) != 3 or not safe_name(segs[1]) or segs[2] not in ("1", "2", "3"):
            return self.fail(404, "?")
        p = os.path.join(LOGS, segs[1], segs[2] + ".log")
        dl = "%s-%s.log" % (segs[1], segs[2]) if q.get("download") else None
        self.file(p, "text/plain; charset=utf-8", dl)

    # ---- reports
    def api_get_report(self, segs, q):
        game = (q.get("game") or [""])[0]
        if game and not safe_name(game):
            return self.fail(400, "Имя игры не подходит: %s" % game)
        rc, out, err = run([BARE_REPORT] + ([game] if game else []), timeout=120)
        path = out.strip().splitlines()[-1] if out.strip() else ""
        if rc or not path or not os.path.isfile(path):
            return self.fail(500, "Отчёт не получился: %s" % (err.strip() or "код выхода %d" % rc))
        log.info("report %s", path)
        self.file(path, "text/plain; charset=utf-8", os.path.basename(path))

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
            f = open(path, "rb")
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
        if not isinstance(where, str) or where not in SAVES_DIRS or not isinstance(name, str) or \
                not safe_name(name) or not SAVES_NAME.match(name):
            return None
        p = os.path.join(SAVES_DIRS[where], name)
        return p if os.path.isfile(p) and not os.path.islink(p) else None

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
        if (segs[1] == "all" and len(segs) == 2) or (len(segs) == 3 and segs[2] == "backup"):
            what = segs[1]
            if what != "all" and not safe_name(what):
                return self.fail(400, "Имя игры не подходит: %s" % what)
            rc, out, err = run([BARE_BACKUP, "backup", what], timeout=900)
            path = out.strip().splitlines()[-1] if out.strip() else ""
            if rc or not path or not os.path.isfile(path):
                return self.backup_err(rc, err, "Копия не получилась")
            log.info("saves %s: %s", what, path)
            return self.stream(path, "application/zip", os.path.basename(path))
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
        if not rest or len(rest) != 1 or not safe_name(rest[0]) or not SAVES_NAME.match(rest[0]):
            return 400, "Это не копия сохранений: имя должно быть saves-….zip."
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
        if b is None or len(segs) != 2 or segs[1] not in ("info", "restore"):
            return self.fail(400, "?")
        p = self.copy_path(b.get("where"), b.get("name") or "")
        if not p:
            return self.fail(404, "Такой копии нет.")
        if segs[1] == "info":
            rc, out, err = run([BARE_BACKUP, "info", p], timeout=60)
            if rc:
                return self.backup_err(rc, err, "Копия не читается")
            return self.json(json.loads(out))
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
        try:
            while True:
                with job.cond:
                    if i >= len(job.events) and not job.ended:
                        job.cond.wait(15)
                    new = job.events[i:]
                    ended = job.ended
                if new:
                    out = "".join("id: %d\ndata: %s\n\n" % (i + k, json.dumps(e, ensure_ascii=False))
                                  for k, e in enumerate(new))
                    i += len(new)
                    self.wfile.write(out.encode())
                elif not ended:
                    self.wfile.write(b": still running\n\n")
                self.wfile.flush()
                if ended and i >= len(job.events):
                    return
        except OSError:
            return	# the page went away


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


def make_server(bind, port):
    global NET
    NET = allowed_net()
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
