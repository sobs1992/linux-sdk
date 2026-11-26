#!/usr/bin/env python3
"""Neighbours from Hell's prepare.sh run twice gives the first run's files
(games/neighbours: relayout.py, dllpatch.py).

  python3 scripts/test-neighbours-prepare.py

Mini data made here (two zip "bnd" files with pictures and dialogs, a DLL
with the places dllpatch.py changes); with NFH_SRC1 / NFH_SRC2 set to a
directory of the game as GOG has it (bin/, data/), a copy of it in a
temporary directory is prepared twice as well (prepare.sh itself, Pillow
needed). The sources are only read: a source given through a symbolic link
is refused."""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NFH = os.path.join(SDK, "games", "neighbours")

SPEC = """
SHIFTS = {'dialogs/menu.xml': -120}
CUTS = {'gui/a.tga': [(0, 40), (520, 600)], 'gui/b.tga': [(259, 319)], 'gui/t.tga': [(180, 300)]}
SCALES = {'gui/c.tga': 480}
EDITS = [
    ('dialogs/a.xml', 'name="v" offset="10/570"', 'name="v" offset="10/495"'),
    ('dialogs/a.xml', 'size="20/180"', 'size="20/140"'),
    # chained: the edit before made its old text
    ('dialogs/a.xml', 'offset="10/495"', 'offset="10/490"'),
]
"""


def tga(w, h):
    head = bytes([0, 0, 2]) + bytes(9) + struct.pack("<HHBB", w, h, 16, 0x20)
    return head + bytes((y * 7 + x) & 0xff for y in range(h) for x in range(w * 2))


def mini_game(d):
    os.makedirs(os.path.join(d, "data"))
    with zipfile.ZipFile(os.path.join(d, "data", "gfxdata.bnd"), "w") as z:
        z.writestr("gui/a.tga", tga(4, 600), zipfile.ZIP_DEFLATED)
        z.writestr("gui/b.tga", tga(4, 319))
        z.writestr("gui/t.tga", tga(4, 473))	# its height says nothing either way
        z.writestr("gui/c.tga", tga(4, 600), zipfile.ZIP_DEFLATED)
        z.writestr("gui/other.tga", tga(4, 10))
    with zipfile.ZipFile(os.path.join(d, "data", "gamedata.bnd"), "w") as z:
        z.writestr("dialogs/a.xml", '<dialog gfx="gui/a.tga">\n<text name="v" offset="10/570" size="20/180"/>'
                   '\n<button offset="5/530"/>\n</dialog>\n', zipfile.ZIP_DEFLATED)
        z.writestr("dialogs/c.xml", '<dialog gfx="gui\\c.tga">\n<button offset="5/300"/>\n</dialog>\n')
        z.writestr("dialogs/menu.xml", '<dialog offset="0/0">\n<x offset="1/2"/>\n</dialog>\n')


def files_md5(d):
    out = {}
    for top, _, names in os.walk(d):
        for n in names:
            p = os.path.join(top, n)
            out[os.path.relpath(p, d)] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return out


# dllpatch.py's places of the first game (GFXEngine.dll): VA, imm32 offset, old value
SITES1 = [(0x1000d8a7, 1, 600), (0x10011ce2, 4, 600), (0x1001622a, 3, 600),
          (0x1001ca74, 3, 529), (0x1002bf87, 4, 530), (0x1002c0b2, 4, 473)]


def mini_dll(path, values=None):
    """a PE with one section (VA 0x10001000, file offset 0x400) and the old
    values at the places"""
    raw, rva, size = 0x400, 0x1000, 0x30000
    b = bytearray(raw + size)
    pe = 0x80
    struct.pack_into("<I", b, 0x3c, pe)
    b[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", b, pe + 6, 1)	# sections
    struct.pack_into("<H", b, pe + 20, 0xe0)	# optional header's size
    struct.pack_into("<I", b, pe + 24 + 28, 0x10000000)	# image base
    struct.pack_into("<8sIIII", b, pe + 24 + 0xe0, b".text", size, rva, size, raw)
    for (va, imm, old), v in zip(SITES1, values or [s[2] for s in SITES1]):
        struct.pack_into("<I", b, raw + va - 0x10000000 - rva + imm, v)
    open(path, "wb").write(b)


def run(*args, ok=True):
    p = subprocess.run([sys.executable, "-I", "-B"] + list(args), capture_output=True, text=True)
    if ok and p.returncode:
        raise AssertionError(p.stdout + p.stderr)
    return p


class Relayout(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="nfh-test-")
        self.spec = os.path.join(self.t, "layout.py")
        open(self.spec, "w").write(SPEC)
        mini_game(os.path.join(self.t, "g"))

    def tearDown(self):
        shutil.rmtree(self.t)

    def relayout(self, src, out, ok=True):
        return run(os.path.join(NFH, "relayout.py"), self.spec, os.path.join(self.t, src), os.path.join(self.t, out),
                   ok=ok)

    def test_twice_same(self):
        self.relayout("g", "o1")
        z = zipfile.ZipFile(os.path.join(self.t, "o1", "data", "gamedata.bnd"))
        a = z.read("dialogs/a.xml").decode()
        self.assertIn('name="v" offset="10/450" size="20/140"', a)	# the edits, the chain, 40 rows cut above
        self.assertIn('<button offset="5/480"/>', a)	# in a cut: to its start, less the 40 above
        self.assertIn('offset="0/-120"', z.read("dialogs/menu.xml").decode())
        self.assertIn('offset="5/240"', z.read("dialogs/c.xml").decode())	# 300 * 480 / 600
        p = self.relayout("o1", "o2")
        self.assertIn("prepared already", p.stdout)
        a, b = files_md5(os.path.join(self.t, "o1")), files_md5(os.path.join(self.t, "o2"))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2)

    def test_in_part_refused(self):
        self.relayout("g", "o1")
        for keep in ("gamedata.bnd", "gfxdata.bnd"):	# that one prepared, the other as the game has it
            with self.subTest(prepared=keep):
                d = os.path.join(self.t, "half")
                shutil.rmtree(d, ignore_errors=True)
                shutil.copytree(os.path.join(self.t, "g"), d)
                shutil.copy(os.path.join(self.t, "o1", "data", keep), os.path.join(d, "data", keep))
                p = self.relayout("half", "o3", ok=False)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("prepared in part", p.stderr)
        # one dialog edit done by hand, the others not
        d = os.path.join(self.t, "half")
        shutil.rmtree(d)
        shutil.copytree(os.path.join(self.t, "g"), d)
        with zipfile.ZipFile(os.path.join(d, "data", "gamedata.bnd"), "w") as z:
            z.writestr("dialogs/a.xml", '<dialog gfx="gui/a.tga">\n<text name="v" offset="10/570" size="20/140"/>\n'
                       '</dialog>\n')
        p = self.relayout("half", "o3", ok=False)
        self.assertIn("prepared in part", p.stderr)


class DllPatch(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="nfh-test-")
        os.makedirs(os.path.join(self.t, "bin"))

    def tearDown(self):
        shutil.rmtree(self.t)

    def patch(self, src, out, ok=True):
        return run(os.path.join(NFH, "dllpatch.py"), "1", os.path.join(self.t, src), os.path.join(self.t, out),
                   "480", ok=ok)

    def test_twice_same(self):
        mini_dll(os.path.join(self.t, "bin", "GFXEngine.dll"))
        self.patch("bin", "o1")
        self.patch("o1", "o2")
        a, b = files_md5(os.path.join(self.t, "o1")), files_md5(os.path.join(self.t, "o2"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, files_md5(os.path.join(self.t, "bin")))

    def test_other_value_refused(self):
        mini_dll(os.path.join(self.t, "bin", "GFXEngine.dll"), [600, 600, 600, 529, 530, 999])
        p = self.patch("bin", "o1", ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("AssertionError", p.stderr)


class RealGame(unittest.TestCase):
    """prepare.sh twice on a copy of the game (NFH_SRC1, NFH_SRC2)"""

    def game(self, n):
        src = os.environ.get("NFH_SRC%d" % n)
        if not src:
            self.skipTest("NFH_SRC%d not set" % n)
        src = os.path.abspath(src)
        if os.path.realpath(src) != src:
            self.fail("%s: a symbolic link on the way, give the real directory" % src)
        t = tempfile.mkdtemp(prefix="nfh-test-")
        try:
            g = os.path.join(t, "game")
            shutil.copytree(src, g, symlinks=True)
            env = dict(os.environ, GAME_DIR=g, NFH_GAME=str(n))
            runs = []
            for _ in range(2):
                p = subprocess.run(["sh", os.path.join(NFH, "prepare.sh")], env=env, capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                runs.append(files_md5(g))
            self.assertEqual(runs[0], runs[1])
            self.assertNotEqual(runs[0], files_md5(src))
        finally:
            shutil.rmtree(t)

    def test_nfh1(self):
        self.game(1)

    def test_nfh2(self):
        self.game(2)


if __name__ == "__main__":
    unittest.main()
