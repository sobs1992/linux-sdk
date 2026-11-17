#!/usr/bin/env python3
"""Install Unreal Tournament 2004 from its DVD for a board running it under
Box64 (APPS_CONFIG += bare-app.UT2004=y): the DVD's Linux installer done
by hand, then the Linux patch 3369.

    ut2004-install.py [--lang int] [--cdkey KEY|FILE] SOURCE GAMES_DIR|[root@]HOST

SOURCE is the DVD: a directory with its files (linux-installer.sh, CD1..CD6)
or a directory holding the DVD's .iso (mounted read-only by udisksctl for the
time of the copy) and the Linux patch (ut2004-lnxpatch3369*.tar.bz2, else
--patch FILE). Done as the DVD's installer (setup.data/setup.xml, a Loki
setup inside linux-installer.sh) does it: the base files, those of one
language (--lang: int English, det German, est Spanish, frt French, itt
Italian), the .uz2 files decompressed, the x86_64 programs of linux-amd64.tar
(not the 32-bit x86 ones). Left out: the game's own x86_64 libSDL-1.2.so.0
and openal.so (Box64 runs the game with the system's SDL 1.2, sdl12-compat,
and OpenAL), the installer's GUI, the sources of SDL and OpenAL.

The game does not start without its CD key ("Your CD key appears to be
invalid" right after the renderer is up): --cdkey writes the key of the
bought copy (XXXXX-XXXXX-XXXXX-XXXXX, or a file holding it) into
System/cdkey, as the DVD's installer does when it asks for it.

Everything goes to ut2004/ of the games partition: GAMES_DIR is where the
card's "GAMES" partition is mounted on this PC; to a HOST it goes over SSH
as a tar stream into /games/ut2004 (remounted writable for the copy, then
read-only again), nothing is staged on this PC (the game is ~5.5 GB).
"""
import argparse
import fnmatch
import glob
import io
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib

LANGS = {"int": "English", "det": "German", "est": "Spanish", "frt": "French", "itt": "Italian"}
# x86_64 libraries of the game that the system's replace (Box64 wraps them)
SKIP = {"System/libSDL-1.2.so.0", "System/openal.so"}


def die(msg):
    sys.exit("ut2004-install: " + msg)


def log(msg):
    print("ut2004-install: " + msg, file=sys.stderr, flush=True)


def uz2_chunks(path):
    """the data of a .uz2 (Unreal's compressed package): chunks of
    <int32 compressed size><int32 size><zlib stream>"""
    with open(path, "rb") as f:
        yield from _uz2_chunks(f)


def _uz2_chunks(f):
    while True:
        head = f.read(8)
        if not head:
            return
        if len(head) != 8:
            die("%s: cut short" % f.name)
        csize = int.from_bytes(head[:4], "little")
        usize = int.from_bytes(head[4:], "little")
        if not 0 < csize <= 1 << 20 or not 0 < usize <= 1 << 20:
            die("%s: not a .uz2 (chunk %d -> %d bytes)" % (f.name, csize, usize))
        data = zlib.decompress(f.read(csize))
        if len(data) != usize:
            die("%s: a chunk of %d bytes, %d expected" % (f.name, len(data), usize))
        yield data


class Out:
    """the game's files: a directory, or a tar stream to the board's ssh"""

    def __init__(self, dest, host):
        self.sizes = {}
        self.dest, self.host, self.proc = dest, host, None
        if host:
            cmd = ("set -e; mountpoint -q /games; mount -o remount,rw /games; "
                   "rm -rf /games/ut2004; mkdir -p /games/ut2004; "
                   "tar -x -f - -C /games/ut2004; sync; mount -o remount,ro /games")
            self.proc = subprocess.Popen(["ssh", host, cmd], stdin=subprocess.PIPE)
            self.tar = tarfile.open(fileobj=self.proc.stdin, mode="w|", format=tarfile.GNU_FORMAT)

    def add(self, rel, src=None, data=None, chunks=None, mode=0o644):
        """rel from the file src, bytes data, or chunks (bytes) of a known
        total size: (size, iterator)"""
        rel = rel.replace("\\", "/")
        if rel in SKIP:
            return
        if self.host:
            ti = tarfile.TarInfo(rel)
            ti.mode, ti.mtime = mode, int(time.time())
            if src is not None:
                ti.size = os.path.getsize(src)
                with open(src, "rb") as f:
                    self.tar.addfile(ti, f)
            elif data is not None:
                ti.size = len(data)
                self.tar.addfile(ti, io.BytesIO(data))
            else:
                size, it = chunks
                ti.size = size
                self.tar.addfile(ti, _ChunkReader(it, size))
            # a later file of the same name replaces it on extraction
            self.sizes[rel] = ti.size
        else:
            path = os.path.join(self.dest, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as o:
                if src is not None:
                    with open(src, "rb") as f:
                        while True:
                            b = f.read(1 << 20)
                            if not b:
                                break
                            o.write(b)
                elif data is not None:
                    o.write(data)
                else:
                    for b in chunks[1]:
                        o.write(b)
            os.chmod(path, mode)
            self.sizes[rel] = os.path.getsize(path)

    def close(self):
        if self.host:
            self.tar.close()
            self.proc.stdin.close()
            if self.proc.wait():
                die("%s: the copy failed" % self.host)


class _ChunkReader(io.RawIOBase):
    def __init__(self, it, size):
        self.it, self.buf, self.left = it, b"", size

    def readable(self):
        return True

    def read(self, n=-1):
        while (n < 0 or len(self.buf) < n):
            try:
                self.buf += next(self.it)
            except StopIteration:
                break
        if n < 0:
            n = len(self.buf)
        out, self.buf = self.buf[:n], self.buf[n:]
        return out


def uz2_size(path):
    """the decompressed size of a .uz2 from its chunk headers"""
    total = 0
    with open(path, "rb") as f:
        while True:
            head = f.read(8)
            if len(head) < 8:
                return total
            csize = int.from_bytes(head[:4], "little")
            total += int.from_bytes(head[4:], "little")
            f.seek(csize, 1)


def installer_payload(dvd):
    """the makeself archive inside the DVD's linux-installer.sh (not run):
    after its first 'offset' lines (head -n N), 'filesizes' bytes of .tar.gz"""
    sh = os.path.join(dvd, "linux-installer.sh")
    with open(sh, "rb") as f:
        head = f.read(64 << 10)
    m = re.search(rb'offset=`head -n (\d+) "\$0"', head)
    s = re.search(rb'filesizes="(\d+)"', head)
    if not m or not s:
        die("%s: not the DVD's makeself installer" % sh)
    lines, size = int(m.group(1)), int(s.group(1))
    with open(sh, "rb") as f:
        for _ in range(lines):
            f.readline()
        blob = f.read(size)
    if len(blob) != size:
        die("%s: cut short" % sh)
    return tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")


def member(tar, name):
    for n in (name, "./" + name):
        try:
            return tar.extractfile(n).read()
        except KeyError:
            pass
    die("the installer has no %s" % name)


def text_of(opt):
    return (opt.text or "").strip()


def dvd_files(dvd, srcpath, line):
    """a line of a <files> list: a file, a directory or a glob, relative to
    the CDn directory; yields (source path, relative name on the disk)"""
    base = os.path.join(dvd, srcpath) if srcpath else dvd
    hits = sorted(glob.glob(os.path.join(base, line)))
    if not hits:
        die("%s: not on the DVD" % posixpath.join(srcpath or "", line))
    for h in hits:
        if os.path.isdir(h):
            for d, _, files in os.walk(h):
                for f in sorted(files):
                    p = os.path.join(d, f)
                    yield p, os.path.relpath(p, base)
        else:
            yield h, os.path.relpath(h, base)


def put_dvd_file(out, src, rel):
    if rel.lower().endswith(".uz2"):
        rel = rel[:-4]
        out.add(rel, chunks=(uz2_size(src), uz2_chunks(src)))
    else:
        out.add(rel, src=src)


def put_tar(out, data):
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            if m.isfile():
                out.add(m.name.lstrip("./") if m.name.startswith("./") else m.name,
                        data=t.extractfile(m).read(), mode=0o755 if m.mode & 0o111 else 0o644)


def do_files(out, payload, dvd, el):
    """one <files> element of setup.xml"""
    arch = el.get("arch")
    if arch and arch != "amd64":
        return
    path = el.get("path")
    srcpath = el.get("srcpath")
    rename = el.get("uz2rename")
    lines = [l.strip() for l in (el.text or "").splitlines() if l.strip()]
    for line in lines:
        if el.get("cdromid"):
            if rename:
                # one file, maybe .uz2, under another name
                src = os.path.join(dvd, line)
                if not os.path.exists(src):
                    src += ".uz2" if os.path.exists(src + ".uz2") else ""
                if not os.path.exists(src):
                    die("%s: not on the DVD" % line)
                if src.lower().endswith(".uz2"):
                    out.add(rename, chunks=(uz2_size(src), uz2_chunks(src)))
                else:
                    out.add(rename, src=src)
                continue
            for src, rel in dvd_files(dvd, srcpath, line):
                put_dvd_file(out, src, rel)
        else:
            data = member(payload, line)
            if line.endswith(".tar"):
                put_tar(out, data)
            else:
                out.add(posixpath.join(path, line) if path else line, data=data)


def install(dvd, patch, lang, out, cdkey):
    payload = installer_payload(dvd)
    xml = member(payload, "setup.data/setup.xml").decode("latin-1")
    xml = re.sub(r"<\?xml[^>]*\?>", "", xml)
    root = ET.fromstring(xml)
    base = [o for o in root.findall("option") if o.get("required") == "true"]
    if len(base) != 1:
        die("setup.xml: no single required option (the base install)")
    base = base[0]
    for el in base.findall("files"):
        log("%s %s" % (el.get("srcpath") or el.get("path") or "", el.get("arch") or ""))
        do_files(out, payload, dvd, el)
    langs = [o for o in base.findall("exclusive/option") if text_of(o).split("\n")[0].strip() == LANGS[lang]]
    if len(langs) != 1:
        die("setup.xml: no language %s (%s)" % (lang, LANGS[lang]))
    log("language: %s" % LANGS[lang])
    for el in langs[0].findall("files"):
        do_files(out, payload, dvd, el)
    # the Linux patch over it (UT2004-Patch/...)
    log("patch: %s" % os.path.basename(patch))
    with tarfile.open(patch, "r:*") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
            out.add(rel, data=t.extractfile(m).read(), mode=0o755 if m.mode & 0o111 else 0o644)
    if cdkey:
        out.add("System/cdkey", data=(cdkey + "\n").encode())
    for p in ("System/ut2004-bin-linux-amd64", "System/Default.ini", "System/DefUser.ini"):
        if p not in out.sizes:
            die("no %s after the install" % p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lang", default="int", choices=sorted(LANGS))
    ap.add_argument("--patch", help="the Linux patch (ut2004-lnxpatch3369*.tar.bz2)")
    ap.add_argument("--cdkey", help="the CD key (XXXXX-XXXXX-XXXXX-XXXXX) or a file holding it")
    ap.add_argument("source")
    ap.add_argument("games")
    a = ap.parse_args()

    cdkey = None
    if a.cdkey:
        cdkey = open(a.cdkey).read().strip() if os.path.isfile(a.cdkey) else a.cdkey.strip()
        if not re.fullmatch(r"[A-Za-z0-9]{5}(-[A-Za-z0-9]{5}){3}", cdkey):
            die("--cdkey: XXXXX-XXXXX-XXXXX-XXXXX expected")
        cdkey = cdkey.upper()
    src = os.path.abspath(a.source)
    patch = a.patch or next(iter(sorted(glob.glob(os.path.join(src, "ut2004-lnxpatch3369*.tar.*")))), None)
    if not patch:
        die("no Linux patch (ut2004-lnxpatch3369*.tar.bz2) in %s: --patch FILE" % src)
    if os.path.isdir(a.games):
        dest, host = os.path.join(a.games, "ut2004"), None
        if os.path.exists(dest):
            subprocess.run(["rm", "-rf", dest], check=True)
    else:
        dest, host = None, a.games if "@" in a.games else "root@" + a.games

    loop = None
    dvd = src
    if not os.path.exists(os.path.join(src, "linux-installer.sh")):
        isos = sorted(glob.glob(os.path.join(src, "*.iso")))
        if len(isos) != 1:
            die("%s: neither the DVD's files nor one .iso" % src)
        r = subprocess.run(["udisksctl", "loop-setup", "-r", "-f", isos[0]],
                           capture_output=True, text=True, check=True)
        loop = re.search(r"(/dev/loop\d+)", r.stdout).group(1)
        time.sleep(1)
        mnt = subprocess.run(["lsblk", "-no", "MOUNTPOINT", loop], capture_output=True,
                             text=True).stdout.strip()
        if not mnt:
            r = subprocess.run(["udisksctl", "mount", "-b", loop], capture_output=True,
                               text=True, check=True)
            mnt = re.search(r" at (\S+)", r.stdout).group(1).rstrip(".")
        dvd = mnt
        log("%s on %s" % (os.path.basename(isos[0]), dvd))
    try:
        out = Out(dest, host)
        install(dvd, patch, a.lang, out, cdkey)
        out.close()
        log("%d files, %d MB -> %s" % (len(out.sizes), sum(out.sizes.values()) >> 20,
                                         dest or host + ":/games/ut2004"))
    finally:
        if loop:
            subprocess.run(["udisksctl", "unmount", "-b", loop], capture_output=True)
            subprocess.run(["udisksctl", "loop-delete", "-b", loop], capture_output=True)


if __name__ == "__main__":
    main()
