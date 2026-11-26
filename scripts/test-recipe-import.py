#!/usr/bin/env python3
"""
Tests of scripts/recipe-import.py on the PC: every SDK it writes into is a
temporary directory made here (games/ with a small games.manifest), the zips
are made here too. Nothing of the SDK's own games/ is touched.

  python3 scripts/test-recipe-import.py [-v]
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "recipe-import.py"
MANIFEST = "; a test manifest\n\n[image]\nfw = ogu\n\n[old]\ndetect = old.exe\nsource = lab/games/Old\n"
SECTION = ("[newgame]\ndetect = New.exe\ngog = 42\n; New Game, GOG 42: exported from the device ogu 2026-11-26\n"
           "source = lab/games/New Game\nexclude = goggame-*\noverlay = games/newgame/overlay\n"
           "cover = games/newgame/cover.png\n")


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


GOOD = {
    "games/newgame/overlay/wine.ini": "; made on the device ogu 2026-11-26, from GOG 42\nname = New Game\n",
    "games/newgame/cover.png": b"\x89PNG",
    "games/newgame/README.md": "# New Game\n\nTODO\n",
    "manifest.section": SECTION,
    "needs.txt": "lab/redist/fonts/x.ttf\n",
    "logs/1.log": "launch\n",
}


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="recipe-import-test-")
        self.sdk = Path(self.tmp.name) / "sdk"
        (self.sdk / "games" / "old" / "overlay").mkdir(parents=True)
        (self.sdk / "games" / "old" / "overlay" / "wine.ini").write_text("name = Old\n")
        self.manifest = self.sdk / "games" / "games.manifest"
        self.manifest.write_bytes(MANIFEST.encode())
        self.zip = Path(self.tmp.name) / "recipe.zip"

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, files, *opts):
        self.zip.write_bytes(make_zip(files))
        return subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.zip), "--sdk", str(self.sdk), *opts],
                              capture_output=True, text=True)

    def snapshot(self):
        top = self.sdk
        return {str(p.relative_to(top)): p.read_bytes() for p in sorted(top.rglob("*")) if p.is_file()}

    def test_import_new(self):
        r = self.run_import(GOOD)
        self.assertEqual(r.returncode, 0, r.stderr)
        g = self.sdk / "games" / "newgame"
        self.assertEqual((g / "overlay" / "wine.ini").read_text(), GOOD["games/newgame/overlay/wine.ini"])
        self.assertEqual((g / "cover.png").read_bytes(), b"\x89PNG")
        self.assertEqual((g / "README.md").read_text(), "# New Game\n\nTODO\n")
        self.assertFalse((g / "logs").exists())
        self.assertFalse((self.sdk / "needs.txt").exists())
        self.assertEqual(self.manifest.read_text(), MANIFEST + "\n" + SECTION)
        for word in ("source = lab/games/New Game", "README.md", "lab/redist/fonts/x.ttf", "logs/1.log"):
            self.assertIn(word, r.stdout)

    def test_again_refused_without_force(self):
        self.assertEqual(self.run_import(GOOD).returncode, 0)
        before = self.snapshot()
        changed = dict(GOOD, **{"games/newgame/README.md": "# other\n"})
        r = self.run_import(changed)
        self.assertEqual(r.returncode, 1)
        self.assertIn("there already", r.stderr)
        self.assertEqual(self.snapshot(), before)
        # --force: the zip's files replace theirs, the section stays once, other files stay
        (self.sdk / "games" / "newgame" / "prepare.sh").write_text("mine\n")
        r = self.run_import(changed, "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.sdk / "games" / "newgame" / "README.md").read_text(), "# other\n")
        self.assertEqual((self.sdk / "games" / "newgame" / "prepare.sh").read_text(), "mine\n")
        self.assertEqual(self.manifest.read_text().count("[newgame]"), 1)
        self.assertIn("not changed", r.stdout)

    def test_section_there_folder_not(self):
        self.manifest.write_bytes((MANIFEST + "\n[NewGame]\ndetect = x.exe\n").encode())
        before = self.manifest.read_bytes()
        r = self.run_import(GOOD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertTrue((self.sdk / "games" / "newgame" / "overlay" / "wine.ini").is_file())

    def test_crlf_manifest(self):
        self.manifest.write_bytes(MANIFEST.replace("\n", "\r\n").encode())
        self.assertEqual(self.run_import(GOOD).returncode, 0)
        data = self.manifest.read_bytes()
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertTrue(data.endswith(b"cover = games/newgame/cover.png\r\n"))

    def test_bad_zips_write_nothing(self):
        before = self.snapshot()
        bad = [
            dict(GOOD, **{"games/newgame/../old/overlay/wine.ini": "x"}),
            dict(GOOD, **{"/etc/x": "x"}),
            dict(GOOD, **{"games/other/overlay/wine.ini": "x"}),
            dict(GOOD, **{"README.md": "x"}),
            dict(GOOD, **{"games/new game/wine.ini": "x"}),
            dict(GOOD, **{"games/newgame\\..\\x": "x"}),
            dict(GOOD, **{"manifest.section": "[other]\ndetect = a.exe\n"}),
            {"manifest.section": SECTION},
            {"games/a/overlay/wine.ini": "x", "games/b/overlay/wine.ini": "y"},
        ]
        for files in bad:
            with self.subTest(names=sorted(files)):
                r = self.run_import(files)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(self.snapshot(), before)
        self.zip.write_bytes(b"not a zip")
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.zip), "--sdk", str(self.sdk)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.snapshot(), before)
        # no SDK there
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.zip), "--sdk", str(Path(self.tmp.name) / "no")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)

    @unittest.skipIf(os.name == "nt", "links")
    def test_no_writing_through_a_link(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.sdk / "games" / "newgame").symlink_to(outside, target_is_directory=True)
        r = self.run_import(GOOD, "--force")
        self.assertEqual(r.returncode, 1)
        self.assertIn("link", r.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        # a link inside a recipe that is there
        (self.sdk / "games" / "newgame").unlink()
        (self.sdk / "games" / "newgame").mkdir()
        (self.sdk / "games" / "newgame" / "overlay").symlink_to(outside, target_is_directory=True)
        r = self.run_import(GOOD, "--force")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
