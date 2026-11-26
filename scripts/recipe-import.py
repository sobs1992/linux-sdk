#!/usr/bin/env python3
"""
recipe-import: a recipe exported by a device (bare-web, the game's page,
"Экспорт": POST /api/recipe/FOLDER/export) put into the SDK.

  python3 scripts/recipe-import.py RECIPE.zip [--sdk DIR] [--force]

The zip holds games/FOLDER/ (overlay/wine.ini or game.ini, cover.png,
README.md), manifest.section (the games.manifest section), needs.txt (the
files of the PC the device's recipe takes) and logs/1.log (the game's last
launch). This puts games/FOLDER/ into the SDK (DIR, default the SDK this
script is in), not over a recipe that is there unless --force (then the
zip's files replace theirs, others stay), and appends the section to
games/games.manifest when it has no [FOLDER] yet. Then it says what is left
to do by hand (source, README, the needs). Nothing else is changed: no
links, no permissions; runs the same on Windows (pathlib).
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXTRA = ("manifest.section", "needs.txt", "logs/1.log")


# what Windows cannot name a file or a directory: these characters, control
# characters, a name ending in a dot or a space, the devices (also with an
# extension: "nul.txt")
WIN_BAD_CHARS = set('<>:"|?*') | {chr(c) for c in range(32)}
WIN_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {"%s%d" % (d, n) for d in ("COM", "LPT") for n in range(1, 10)}


class Refused(Exception):
    pass


def windows_ok(part):
    """part (one name of a path) can be a file's or a directory's on Windows"""
    return (not any(c in WIN_BAD_CHARS for c in part) and not part.endswith((".", " ")) and
            part.split(".", 1)[0].rstrip(" ").upper() not in WIN_DEVICES)


def plan(z):
    """(folder, {relative path in games/FOLDER: bytes}, {extra name: bytes}) of
    the zip, every name checked first: nothing outside games/FOLDER/ and the
    extras, one folder"""
    folder, files, extra = None, {}, {}
    for info in z.infolist():
        name = info.filename
        if info.is_dir():
            continue
        p = PurePosixPath(name)
        if "\\" in name or p.is_absolute() or ":" in name or any(x in ("", ".", "..") for x in name.split("/")):
            raise Refused("a name in the zip that is no file of a recipe: %r" % name)
        if not all(windows_ok(x) for x in name.split("/")):
            raise Refused("a name in the zip that Windows cannot have: %r" % name)
        if name in EXTRA:
            extra[name] = z.read(info)
            continue
        if len(p.parts) < 3 or p.parts[0] != "games" or not FOLDER_RE.match(p.parts[1]):
            raise Refused("a name in the zip that is no file of a recipe: %r" % name)
        if folder not in (None, p.parts[1]):
            raise Refused("the zip holds two games: %s and %s" % (folder, p.parts[1]))
        folder = p.parts[1]
        files[PurePosixPath(*p.parts[2:])] = z.read(info)
    if not folder:
        raise Refused("no games/FOLDER/ in the zip")
    return folder, files, extra


def has_section(text, folder):
    return re.search(r"^\[%s\]\s*$" % re.escape(folder), text, re.M | re.I) is not None


def no_links(top, rel):
    """top/rel and every directory between them: not a link"""
    p = top
    for part in rel.parts:
        p = p / part
        if p.is_symlink():
            raise Refused("%s is a link: not written through" % p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="put a recipe exported by a device into the SDK")
    ap.add_argument("zip", type=Path)
    ap.add_argument("--sdk", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--force", action="store_true", help="replace the files of a recipe that is there")
    a = ap.parse_args(argv)
    games = a.sdk / "games"
    manifest = games / "games.manifest"
    try:
        if not manifest.is_file():
            raise Refused("%s is not there (--sdk?)" % manifest)
        try:
            with zipfile.ZipFile(a.zip) as z:
                folder, files, extra = plan(z)
        except (OSError, zipfile.BadZipFile) as e:
            raise Refused("%s: %s" % (a.zip, e))
        dest = games / folder
        no_links(games, PurePosixPath(folder))
        if dest.exists() and not a.force:
            raise Refused("%s is there already: not replaced (--force replaces its files)" % dest)
        for rel in files:
            no_links(dest, rel)
        # the manifest: appended only when it has no [FOLDER]
        mtext = manifest.read_bytes()
        section = extra.get("manifest.section", b"")
        add = bool(section.strip()) and not has_section(mtext.decode("utf-8", "replace"), folder)
        if add:
            sec_text = section.decode("utf-8")
            if not has_section(sec_text, folder):
                raise Refused("manifest.section is not a section [%s]" % folder)
    except Refused as e:
        print("recipe-import: %s" % e, file=sys.stderr)
        return 1
    for rel, data in sorted(files.items()):
        p = dest.joinpath(*rel.parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print("wrote %s" % p)
    if add:
        nl = b"\r\n" if b"\r\n" in mtext else b"\n"
        body = section.replace(b"\r\n", b"\n").rstrip(b"\n").replace(b"\n", nl) + nl
        sep = b"" if mtext.endswith(nl + nl) or not mtext else (nl if mtext.endswith(nl) else nl + nl)
        with manifest.open("ab") as f:
            f.write(sep + body)
        print("appended [%s] to %s" % (folder, manifest))
    elif section.strip():
        print("%s has [%s] already: not changed (the device's section, to compare:)" % (manifest, folder))
        print("  " + section.decode("utf-8", "replace").rstrip("\n").replace("\n", "\n  "))
    print("\nleft to do by hand:")
    sec = section.decode("utf-8", "replace")
    m = re.search(r"^source\s*=\s*(.+?)\s*$", sec, re.M)
    if m:
        print("- source = %s in [%s]: the game's copy on this PC (put it there, or change the line)"
              % (m.group(1), folder))
    if re.search(r"^;\s*detect\s*=", sec, re.M):
        print("- detect: the game's program, relative to its folder")
    if "README.md" in {str(r) for r in files}:
        print("- %s: the edition, what was checked (its TODO lines)" % (dest / "README.md"))
    needs = [n for n in extra.get("needs.txt", b"").decode("utf-8", "replace").splitlines() if n.strip()]
    for n in needs:
        print("- needs from a PC: %s (a file or data line of the section, from lab/redist or the installer)" % n)
    if "logs/1.log" in extra:
        print("- the game's last launch on the device: logs/1.log in %s" % a.zip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
