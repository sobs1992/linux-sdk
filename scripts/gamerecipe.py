"""
gamerecipe: what a section of games/games.manifest says, done: a game put
into its directory of /games (copied or moved from its source, files and
the overlay added, its cover made, its "run" step, its /data files). Used by
scripts/games-image.py on the PC and by game-install on the board (the
recipes in the rootfs, /usr/share/game-recipes: board/ogu/buildroot/
post-build.sh), so a game installs the same way on both.

Paths not starting with / are of ROOT (the SDK, or the board's recipes).
On the board (strict=False) what a recipe takes from the PC only (lab/:
Windows DLLs and fonts, a translation's installer) is not there: the
board's elsewhere(spec) finds it by its name (the games card's redist
folder), else that file, data line or cover is left out and said so, the
game installs without it; needs() says that before.

Finding a game: a section's "detect" (paths of its files, relative to the
game's directory, all there: matched without case on the exFAT card) and
"gog" (GOG's product ids, goggame-<id>.info in it): find_game() looks
through a directory a few levels down for the directory of a game.
"""
import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVER = 240		# px: the home screen's tile on the GO Ultra
MULTI = ("exclude", "file", "data", "env")	# keys that may come more than once
FIND_DEPTH = 4		# levels below the directory given that find_game() looks at


class RecipeError(Exception):
    pass


def path(p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def read_manifest(file):
    """[(section, {key: value or [values]})] in file order; ${key} in a
    value is that key of [image], set above it (a path many games share)"""
    sections, cur, image = [], None, {}

    def var(m):
        if m.group(1) not in image:
            raise RecipeError("%s:%d: ${%s}: no %s in [image] above" % (file, n, m.group(1), m.group(1)))
        return image[m.group(1)]
    for n, line in enumerate(open(file, encoding="utf-8"), 1):
        s = re.sub(r"(^|\s)[;#].*$", "", line).strip()
        if not s:
            continue
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            cur = image if m.group(1).strip() == "image" else {}
            sections.append((m.group(1).strip(), cur))
            continue
        if "=" not in s or cur is None:
            raise RecipeError("%s:%d: %s?" % (file, n, s))
        k, v = (x.strip() for x in s.split("=", 1))
        v = re.sub(r"\$\{(\w+)\}", var, v)
        if k in MULTI:
            cur.setdefault(k, []).append(v)
        else:
            cur[k] = v
    return sections


def arrow(spec):
    """"SRC -> DST" or "SRC": (SRC, DST or None)"""
    if "->" in spec:
        a, b = spec.split("->", 1)
        return a.strip(), b.strip()
    return spec.strip(), None


def relocate(spec, orig, source):
    """a path under a section's source orig: under the source given instead
    (a game the board found; its files as the game has them)"""
    if not source or not orig or not spec:
        return spec
    o = orig.rstrip("/")
    if spec == o or spec.startswith(o + "/") or spec.startswith(o + ":"):
        return source + spec[len(o):]
    return spec


def needs(g, source=None, elsewhere=None):
    """what the file, data and env lines of a section (keys g) name that is
    neither there (under source for the game's own files) nor found by
    elsewhere(spec): those specs"""
    out = []
    for key in ("file", "data"):
        for spec in g.get(key, []):
            s, _ = arrow(spec)
            if not sources(relocate(s, g.get("source"), source)) and not (elsewhere and elsewhere(s)):
                out.append(s)
    for spec in g.get("env", []):
        v = spec.partition("=")[2].strip()
        if v.startswith("/") and not os.path.exists(v) and not (elsewhere and elsewhere(v)):
            out.append(v)
    return out


def copy_into(src, dst):
    """a file into a directory (dst ends in /) or to a path"""
    if dst.endswith("/") or os.path.isdir(dst):
        os.makedirs(dst, exist_ok=True)
        dst = os.path.join(dst, os.path.basename(src))
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def sources(spec):
    """files of a glob, ROOT-relative unless absolute; [] none"""
    return sorted(glob.glob(path(spec)))


def load_picture(spec, alpha=False):
    """a picture file, or ARCHIVE:ENTRY of a game (game_pictures.py)"""
    from PIL import Image
    m = re.match(r"^(.+\.(?:lod|wad|exe|dll|bik)):([^/:]+)$", spec, re.I)
    try:
        if m:
            import game_pictures
            im = game_pictures.picture(path(m.group(1)), m.group(2))
        else:
            im = Image.open(path(spec))
        return im.convert("RGBA" if alpha else "RGB")
    except Exception as e:
        raise RecipeError("cover %s: %s" % (spec, e))


def make_cover(spec, dst, crop, back_spec=None):
    """spec: a picture file, or ARCHIVE:ENTRY of a game (game_pictures.py);
    crop: center, top, bottom, left, right, "X Y SIZE" in its pixels, or fit
    (all of it, on a blurred, darker copy of itself). With back_spec (a
    picture likewise) the picture, transparent around (an icon), is put
    whole on that one blurred and darker, with a shadow."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        raise RecipeError("covers need Python's PIL (apt install python3-pil)")
    if back_spec:
        back = load_picture(back_spec)
        w, h = back.size
        s = min(w, h)
        back = back.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        back = back.resize((COVER, COVER), Image.LANCZOS).filter(ImageFilter.GaussianBlur(6))
        back = ImageEnhance.Brightness(back).enhance(0.5).convert("RGBA")
        fg = load_picture(spec, alpha=True)
        k = COVER * 0.8 / max(fg.size)
        fg = fg.resize((round(fg.width * k), round(fg.height * k)), Image.LANCZOS)
        shadow = Image.new("RGBA", fg.size, (0, 0, 0, 0))
        shadow.putalpha(fg.getchannel("A").point(lambda a: a * 7 // 10))
        shadow = shadow.filter(ImageFilter.GaussianBlur(6))
        x, y = (COVER - fg.width) // 2, (COVER - fg.height) // 2
        back.alpha_composite(shadow, (x + 4, y + 6))
        back.alpha_composite(fg, (x, y))
        back.convert("RGB").save(dst, optimize=True)
        return
    im = load_picture(spec)
    w, h = im.size
    if crop == "fit":
        k = COVER / max(w, h)
        s = min(w, h)
        back = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        back = back.resize((COVER, COVER), Image.LANCZOS).filter(ImageFilter.GaussianBlur(12))
        back = ImageEnhance.Brightness(back).enhance(0.45)
        fg = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
        back.paste(fg, ((COVER - fg.width) // 2, (COVER - fg.height) // 2))
        back.save(dst, optimize=True)
        return
    nums = crop.split()
    if len(nums) == 3 and all(n.isdigit() for n in nums):
        x, y, s = map(int, nums)
        if x + s > w or y + s > h:
            raise RecipeError("cover_crop %s: outside the %dx%d picture" % (crop, w, h))
    else:
        s = min(w, h)
        x = {"left": 0, "right": w - s}.get(crop, (w - s) // 2)
        y = {"top": 0, "bottom": h - s}.get(crop, (h - s) // 2)
    im = im.crop((x, y, x + s, y + s)).resize((COVER, COVER), Image.LANCZOS)
    im.save(dst, optimize=True)


def wine_exe(d):
    """the program of d's wine.ini ("exe ="), None"""
    try:
        m = re.search(r"^exe\s*=\s*(.+?)\s*$", open(os.path.join(d, "wine.ini"), encoding="utf-8",
                                                   errors="replace").read(), re.M)
    except OSError:
        return None
    return m and m.group(1).replace("\\", "/")


def icon_cover(d, log=print):
    """cover.png from the biggest icon of the program of d's wine.ini (a
    game whose recipe's cover is not on the board, a game without a
    recipe); nothing if it has none"""
    exe = wine_exe(d)
    if not exe or ":" in exe or not os.path.isfile(os.path.join(d, exe)):
        return False
    try:
        make_cover(os.path.join(d, exe) + ":icon", os.path.join(d, "cover.png"), "fit",
                   os.path.join(d, exe) + ":icon")
        log("cover: the icon of %s" % exe)
        return True
    except (RecipeError, OSError) as e:
        log("no cover: %s" % e)
        return False


def excluded(rel, name, excl):
    """a path of the source (relative, and its last part) the excludes name"""
    return any(fnmatch.fnmatch(rel, e) or fnmatch.fnmatch(name, e) for e in excl)


def _move_tree(src, dest, excl, log):
    """the source directory renamed to dest (the same file system: no
    copy), then what the excludes name deleted from it. Never through a
    link: renamed, the link would move and the deletions reach the
    directory it points to (a PC's copy of the game)."""
    if os.path.realpath(src) != os.path.abspath(src):
        raise RecipeError("%s: a symbolic link on its path: not moved" % src)
    os.rename(src, dest)
    for d, dirs, files in os.walk(dest, topdown=True):
        rel = os.path.relpath(d, dest)
        for n in list(dirs) + files:
            p = n if rel == "." else os.path.join(rel, n)
            if excluded(p, n, excl):
                full = os.path.join(d, n)
                if os.path.isdir(full) and not os.path.islink(full):
                    shutil.rmtree(full)
                    dirs.remove(n)
                else:
                    os.remove(full)


def install_game(name, g, games, data, source=None, move=False, strict=True, log=print, step=None,
                 elsewhere=None):
    """Section name (its keys g) into <games>/<dir>, its data files into
    <data>. source: the game's directory instead of the section's
    "source"; move: rename it into place (same file system), not copy.
    strict: what a line names must be there (else RecipeError); not strict
    (the board): looked for by elsewhere(spec) (a list of files), else left
    out and said. step(name) is told each step as it
    begins: files (copied or moved), extras (file lines, the overlay),
    cover, prepare (run), data. Returns what was left out."""
    step = step or (lambda what: None)
    gdir = g.get("dir", name)
    dest = os.path.join(games, gdir)
    how = g.get("install", "copy")
    src = source or (g.get("source") and path(g["source"]))
    skipped = []
    orig = g.get("source")

    def here(spec):
        return relocate(spec, orig, source)

    def find(spec):
        return sources(here(spec)) or (elsewhere(spec) if elsewhere and not strict else [])

    def missing(what):
        if strict:
            raise RecipeError("[%s] %s: not found" % (name, what))
        skipped.append(what)
        log("[%s] left out: %s" % (name, what))

    if src and not os.path.isdir(src):
        raise RecipeError("[%s] source %s: not a directory" % (name, src))
    orig_src = src
    if os.path.islink(dest):
        os.remove(dest)		# the link, not what it points to
    else:
        shutil.rmtree(dest, ignore_errors=True)
    log("[%s] %s %s -> /games/%s" % (name, "move" if move else how, src or "", gdir))
    step("files")
    if how in ("homm3", "halflife"):
        # the SDK's installers put the game into <games>/heroes3, /halflife
        script = path(os.path.join("scripts", how + "-install.sh"))
        opts = g.get("options", "").split()
        if subprocess.run([script] + opts + [src, games], stdout=sys.stderr).returncode:
            raise RecipeError("[%s] %s failed" % (name, script))
        want = {"homm3": "heroes3", "halflife": "halflife"}[how]
        if gdir != want:
            os.replace(os.path.join(games, want), dest)
    elif how == "copy":
        if not src:
            raise RecipeError("[%s] needs a source" % name)
        excl = [e for x in g.get("exclude", []) for e in x.split()]
        if move:
            _move_tree(src, dest, excl, log)
            source = dest	# its files are there now (file, cover lines)
        else:
            def ignore(d, names):
                rel = os.path.relpath(d, src)
                return {n for n in names if excluded(n if rel == "." else os.path.join(rel, n), n, excl)}
            shutil.copytree(src, dest, ignore=ignore, symlinks=False)
    elif how == "none":
        os.makedirs(dest, exist_ok=True)
    else:
        raise RecipeError("[%s] install = %s? (copy, homm3, halflife, none)" % (name, how))
    step("extras")
    for spec in g.get("file", []):
        s, d = arrow(spec)
        found = find(s)
        if not found:
            missing(s)
        for f in found:
            copy_into(f, os.path.join(dest, d) if d else dest + "/")
    if g.get("overlay"):
        o = path(g["overlay"])
        if not os.path.isdir(o):
            raise RecipeError("[%s] overlay %s: not a directory" % (name, o))
        shutil.copytree(o, dest, dirs_exist_ok=True)
    step("cover")
    if g.get("cover"):
        def in_game(spec):
            """game:PATH, a file of the game as installed"""
            return os.path.join(dest, spec[5:]) if spec and spec.startswith("game:") else spec
        try:
            make_cover(here(in_game(g["cover"])), os.path.join(dest, "cover.png"),
                       g.get("cover_crop", "center"), here(in_game(g.get("cover_back"))))
        except (RecipeError, OSError) as e:
            if strict:
                raise
            missing("cover (%s)" % e)
    if not strict and not os.path.exists(os.path.join(dest, "cover.png")):
        icon_cover(dest, log)
    if g.get("run"):
        step("prepare")
        # SOURCE: where the game was (moved: gone, but what is next to it
        # stays, NFSU's rus/)
        env = dict(os.environ, GAME_DIR=dest, SOURCE=orig_src or "", SDK_DIR=ROOT, DATA_DIR=data)
        for spec in g.get("env", []):
            k, eq, v = spec.partition("=")
            if not eq or not re.fullmatch(r"[A-Za-z_]\w*", k.strip()):
                raise RecipeError("[%s] env = %s: NAME=VALUE?" % (name, spec))
            v = v.strip()
            if not strict and v.startswith("/") and not os.path.exists(v):
                alt = elsewhere(v) if elsewhere else []
                if not alt:
                    missing(v)	# a file of the PC (PoP's translation): the step goes without it
                    continue
                v = alt[0]
            env[k.strip()] = v
        # its words to stderr: stdout is for the board's install screen
        if subprocess.run([path(g["run"])], env=env, cwd=ROOT, stdout=sys.stderr).returncode:
            if strict:
                raise RecipeError("[%s] %s failed" % (name, g["run"]))
            # the board: the game is there, what the step does to it not
            # all (a tool of the PC it needs: The Book of Unwritten Tales'
            # numpy and ImageMagick); said, not undone
            missing("prepare: %s" % g["run"])
    if g.get("data"):
        step("data")
    for spec in g.get("data", []):
        s, d = arrow(spec)
        if not d:
            raise RecipeError("[%s] data = %s: needs \"-> path on /data\"" % (name, spec))
        found = find(s)
        if not found:
            missing(s)
        for f in found:
            copy_into(f, os.path.join(data, d.lstrip("/")))
    return skipped


# ---- finding a game -----------------------------------------------------------

def _gog_ids(d):
    """GOG's product ids of the goggame-<id>.info files in d"""
    try:
        return {m.group(1) for n in os.listdir(d) for m in [re.match(r"goggame-(\d+)\.info$", n, re.I)] if m}
    except OSError:
        return set()


def _has_all(d, files):
    """every path of files under d (any case: the exFAT card ignores it,
    other file systems are looked through)"""
    for f in files:
        p = d
        for part in f.split("/"):
            try:
                names = os.listdir(p)
            except OSError:
                return False
            hit = next((n for n in names if n.lower() == part.lower()), None)
            if hit is None:
                return False
            p = os.path.join(p, hit)
    return True


def detect_files(g):
    """the files of a section's "detect" ("a.exe | Data/b.dat")"""
    return [f.strip() for f in g.get("detect", "").split("|") if f.strip()]


def recipe_of(d, sections):
    """(name, keys) of the section whose game d is, None: by GOG's id, then
    by "detect", the sections with more files first (Neighbours from Hell
    2 has all of 1's and more)"""
    ids = _gog_ids(d)
    for name, g in sections:
        if ids and set(g.get("gog", "").split()) & ids:
            return name, g
    for name, g in sorted(sections, key=lambda s: -len(detect_files(s[1]))):
        files = detect_files(g)
        if files and _has_all(d, files):
            return name, g
    return None


def find_game(top, sections, depth=FIND_DEPTH):
    """(name, keys, directory) of the first game found in top or below it
    (breadth first: the shallowest wins), None"""
    level = [top]
    for _ in range(depth + 1):
        nxt = []
        for d in level:
            hit = recipe_of(d, sections)
            if hit:
                return hit[0], hit[1], d
            try:
                nxt += sorted(os.path.join(d, n) for n in os.listdir(d)
                              if os.path.isdir(os.path.join(d, n)) and not os.path.islink(os.path.join(d, n)))
            except OSError:
                pass
        level = nxt
    return None
