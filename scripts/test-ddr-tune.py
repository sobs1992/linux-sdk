#!/usr/bin/env python3
"""The DDR tune line's path outside ddr-calibrate: the scenario matrix.

    scripts/test-ddr-tune.py [--patch FILE] [--ddr-tune FILE] [--keep FILE]

- U-Boot patch 0020: ogu_tune_csr_ok() and ogu_ddr_tune() compiled from
  the patch itself (the "+" lines) against stubs for the eMMC and the PHY:
  a line of all 44 CSRs (36 delays, 8 strobes) is applied and all 44
  recorded for /chosen.
- /usr/sbin/ddr-tune set: the line checked before the eMMC is looked for,
  a CSR named twice refused (U-Boot would move it twice).
- scripts/keep-sectors.sh (flash.sh): an image written over the tune
  sector leaves a "ddr_tune=" line there; other content is overwritten.
Runs on the PC, writes only into a temporary directory.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(SDK, "board/ogu/u-boot/patches/0020-board-odroid-go-ultra-ddr-phy-read-delays-tuned-per-device.patch")
DDR_TUNE = os.path.join(SDK, "board/ogu/buildroot/rootfs-overlay/usr/sbin/ddr-tune")
KEEP = os.path.join(SDK, "scripts/keep-sectors.sh")

STUBS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
typedef unsigned long ulong;
typedef unsigned short u16;
#define __iomem
static u16 regs[0x20000];
#define OGU_TUNE_SECTOR 0x7efe
#define OGU_PHY_CSR(csr) (&regs[(csr) & 0x1ffff])
#define readw(a) (*(volatile u16 *)(a))
#define writew(v, a) (*(volatile u16 *)(a) = (v))
#define ALLOC_CACHE_ALIGN_BUFFER(t, n, sz) t n[sz]
#define clamp(v, lo, hi) ((v) < (lo) ? (lo) : (v) > (hi) ? (hi) : (v))
#define dsb()
struct blk_desc { int x; };
struct mmc { int x; };
static char sector[512];
static struct mmc the_mmc;
static struct blk_desc the_bd;
static int ogu_emmc_devnum(void) { return 1; }
static struct mmc *find_mmc_device(int d) { (void)d; return &the_mmc; }
static int mmc_init(struct mmc *m) { (void)m; return 0; }
static struct blk_desc *mmc_get_blk_desc(struct mmc *m) { (void)m; return &the_bd; }
static ulong blk_dread(struct blk_desc *b, ulong start, ulong n, void *buf)
{
	(void)b;
	if (start != OGU_TUNE_SECTOR || n != 1)
		return 0;
	memcpy(buf, sector, 512);
	return 1;
}
static ulong hextoul(const char *p, char **e) { return strtoul(p, e, 16); }
"""

MAIN = r"""
int main(int argc, char **argv)
{
	FILE *f = fopen(argv[1], "rb");
	size_t n = fread(sector, 1, sizeof sector, f);

	(void)argc;
	(void)n;
	fclose(f);
	for (unsigned i = 0; i < 0x20000; i++)
		regs[i] = 5;
	ogu_ddr_tune();
	printf("done %s\n", ogu_tune_done);
	for (int db = 0; db < 4; db++) {
		for (int r = 0; r < 9; r++)
			printf("%05x=%d\n", 0x10000 | db << 12 | r << 8 | 0x68, regs[0x10000 | db << 12 | r << 8 | 0x68]);
		for (int u = 0; u < 2; u++)
			printf("%05x=%d\n", 0x10000 | db << 12 | u << 8 | 0x8c, regs[0x10000 | db << 12 | u << 8 | 0x8c]);
	}
	return 0;
}
"""

ALL44 = ["%05x" % (0x10000 | db << 12 | r << 8 | 0x68) for db in range(4) for r in range(9)] + \
        ["%05x" % (0x10000 | db << 12 | u << 8 | 0x8c) for db in range(4) for u in range(2)]


class Matrix:
    def __init__(self):
        self.bad = 0

    def cell(self, name, ok, detail=""):
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "\n        " + detail))
        self.bad += not ok


def uboot_code(patch):
    lines = [l[1:] for l in open(patch).read().splitlines() if l.startswith("+") and not l.startswith("+++")]
    text = "\n".join(lines)
    a = text.index("static char ogu_tune_done")
    b = text.index("int meson_ft_board_setup")
    return text[a:b]


def uboot(m, work, patch):
    c = os.path.join(work, "tune.c")
    exe = os.path.join(work, "tune")
    with open(c, "w") as f:
        f.write(STUBS + uboot_code(patch) + MAIN)
    subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-o", exe, c], check=True)

    def run(line):
        s = os.path.join(work, "sector")
        data = ("ddr_tune=%s\n" % line).encode()
        with open(s, "wb") as f:
            f.write(data + b"\0" * (512 - len(data)))
        out = subprocess.run([exe, s], capture_output=True, text=True, check=True).stdout.splitlines()
        done = [l for l in out if l.startswith("done ")][0][5:].split()
        regs = dict(l.split("=") for l in out if re.match(r"^[0-9a-f]{5}=", l))
        return done, {k: int(v) for k, v in regs.items()}

    done, regs = run(" ".join(c + "+1" for c in ALL44))
    m.cell("uboot all44: 44 CSRs moved", len(ALL44) == 44 and all(regs[c] == 6 for c in ALL44), str(regs))
    m.cell("uboot all44: 44 CSRs recorded for /chosen", len(done) == 44 and
           [d[:5] for d in done] == ALL44 and all(d.endswith(":0005>0006") for d in done),
           "%d recorded: %s" % (len(done), done[-3:]))
    done, regs = run("11668+10 1118c-2 11668x 13768+3f")
    m.cell("uboot parse: a bad entry ends the line, the ones before it stay",
           regs["11668"] == 0x15 and regs["1118c"] == 3 and regs["13768"] == 5 and len(done) == 2, str(done))
    done, regs = run("11668-9 13768+3f 21668+1")
    m.cell("uboot clamp: within 0..3f; another block refused",
           regs["11668"] == 0 and regs["13768"] == 0x3f and len(done) == 2, str(done))


def ddr_tune(m, script):
    def run(*args):
        return subprocess.run(["sh", script] + list(args), capture_output=True, text=True)

    r = run("set", "11668+c 11668+2")
    m.cell("ddr-tune twice: a CSR named twice refused", r.returncode == 1 and "11668 twice" in r.stderr, r.stderr)
    r = run("set", "11668+c 1118C+2 1118c-1")
    m.cell("ddr-tune twice: upper and lower case are one CSR", r.returncode == 1 and "1118c twice" in r.stderr,
           r.stderr)
    r = run("set", " ".join(c + "+1" for c in ALL44))
    m.cell("ddr-tune all44: 44 different CSRs pass the check (then: no eMMC on the PC)",
           r.returncode == 1 and "no eMMC" in r.stderr, r.stderr)
    r = run("set", "11668+40")
    m.cell("ddr-tune steps: more than 3f refused", r.returncode == 1 and "more than 3f" in r.stderr, r.stderr)
    r = run("set", "11690+1")
    m.cell("ddr-tune csr: not a delay register refused", r.returncode == 1 and "not a DBYTE" in r.stderr, r.stderr)


def keep(m, work, helper):
    sec = 32510
    size = (sec + 100) * 512

    def disk(name, content_at_sec):
        p = os.path.join(work, name)
        with open(p, "wb") as f:
            f.write(b"\x11" * size)
            f.seek(sec * 512)
            f.write(content_at_sec.ljust(512, b"\0"))
        return p

    tmp = os.path.join(work, "tmp")
    os.makedirs(tmp)
    # dd that stops after 16280 KiB (past the sector: a USB disk gone half way)
    limited = os.path.join(work, "limited")
    with open(limited, "w") as f:
        f.write('#!/bin/bash\ncase "$*" in *bs=4M*) ulimit -f 16280 ;; esac\nexec "$@"\n')
    os.chmod(limited, 0o755)
    # dd that cannot write the kept sector back either (the disk gone for good)
    gone = os.path.join(work, "gone")
    with open(gone, "w") as f:
        f.write('#!/bin/bash\ncase "$*" in *bs=4M*) ulimit -f 16280 ;; *seek=*) exit 1 ;; esac\nexec "$@"\n')
    os.chmod(gone, 0o755)
    image = os.path.join(work, "image")
    with open(image, "wb") as f:
        f.write(b"\x22" * size)

    def flash(dev, start, keep_var, img=image, sudo=""):
        # flash.sh's own write (flash_write) under flash.sh's trap
        sh = ('set -euo pipefail; . "$1"; SUDO=$6; DD_STATUS=none; keep_traps; KEEP="$2"; '
              'keep_check; flash_write "$4" "$3" "$5"')
        env = dict(os.environ, TMPDIR=tmp)
        return subprocess.run(["bash", "-c", sh, "x", helper, keep_var, dev, img, str(start), sudo],
                              capture_output=True, text=True, env=env)

    def at(dev, s):
        with open(dev, "rb") as f:
            f.seek(s * 512)
            return f.read(512)

    line = b"ddr_tune=11668+c 13568+7\n"
    d = disk("emmc1", line)
    r = flash(d, 0, "32510:ddr_tune=")
    m.cell("keep emmc: a whole image from sector 0 leaves the tune line", r.returncode == 0 and
           at(d, sec) == line.ljust(512, b"\0") and at(d, sec + 1) == b"\x22" * 512, r.stdout + r.stderr)
    m.cell("keep emmc: flash says what it kept", "Keeping sector 32510" in r.stdout, r.stdout)
    d = disk("emmc2", line)
    r = flash(d, 1, "32510:ddr_tune=")
    m.cell("keep boot area: written from sector 1 over it, the line stays", r.returncode == 0 and
           at(d, sec) == line.ljust(512, b"\0"), r.stdout + r.stderr)
    d = disk("emmc3", b"ab_slot=a\n")
    r = flash(d, 0, "32510:ddr_tune=")
    m.cell("keep other: a sector without the prefix is the image's", r.returncode == 0 and
           at(d, sec) == b"\x22" * 512 and "Keeping" not in r.stdout, r.stdout + r.stderr)
    d = disk("emmc4", line)
    r = flash(d, 0, "")
    m.cell("keep none: KEEP empty: written as before", r.returncode == 0 and at(d, sec) == b"\x22" * 512,
           r.stdout + r.stderr)
    small = os.path.join(work, "small")
    with open(small, "wb") as f:
        f.write(b"\x33" * 512 * 100)
    d = disk("emmc5", line)
    r = flash(d, 0, "32510:ddr_tune=", small)
    m.cell("keep outside: a write that does not reach the sector does not touch it",
           r.returncode == 0 and at(d, sec) == line.ljust(512, b"\0") and "Keeping" not in r.stdout,
           r.stdout + r.stderr)
    d = disk("emmc6", line)
    r = flash(d, 0, "32510")
    m.cell("keep bad: an entry without a prefix stops before writing", r.returncode != 0 and
           at(d, 0) == b"\x11" * 512, r.stdout + r.stderr)
    d = disk("emmc7", line)
    r = flash(d, 0, "32510:ddr_tune=", sudo=limited)
    m.cell("keep stopped: the write stops past the sector: the line is put back, the flash fails",
           r.returncode != 0 and at(d, sec) == line.ljust(512, b"\0") and "kept sectors are back" in r.stderr,
           "rc %d: %s" % (r.returncode, r.stderr[-300:]))
    d = disk("emmc8", line)
    r = flash(d, 0, "32510:ddr_tune=", sudo=gone)
    kept = re.search(r"it is kept in (\S+): (.*)", r.stderr)
    m.cell("keep gone: it cannot be put back: its file stays, the line said in full",
           r.returncode != 0 and kept is not None and os.path.exists(kept.group(1).rstrip(":")) and
           "ddr_tune=11668+c 13568+7" in kept.group(2), r.stderr[-300:])
    if kept:
        os.unlink(kept.group(1).rstrip(":"))
    m.cell("keep clean: no temporary file left", not os.listdir(tmp), str(os.listdir(tmp)))
    fs = open(os.path.join(SDK, "scripts/flash.sh")).read()
    m.cell("flash.sh: its write is flash_write, under keep_traps, KEEP checked before asking",
           "keep_traps" in fs and 'flash_write "$FILE" "$DEV" "$SECTOR"' in fs and
           fs.index("keep_check") < fs.index("read -r -p"), "flash.sh wiring")
    real_flash(m, work, helper, line, sec, size)


def real_flash(m, work, helper, line, sec, size):
    """flash.sh itself on a file: only its block-device check made a file check,
    lsblk, sudo and eject stubbed; SLOW=1: the image's dd sleeps 30 s after it wrote"""
    import shutil
    import signal
    import time
    d = os.path.join(work, "real")
    os.makedirs(os.path.join(d, "bin"))
    os.makedirs(os.path.join(d, "tmp"))
    src = open(os.path.join(SDK, "scripts/flash.sh")).read()
    assert src.count('[ -b "$DEV" ]') == 1
    with open(os.path.join(d, "flash.sh"), "w") as f:
        f.write(src.replace('[ -b "$DEV" ]', '[ -f "$DEV" ]'))
    shutil.copy(helper, os.path.join(d, "keep-sectors.sh"))
    stubs = {
        "lsblk": '#!/bin/bash\ncase "$*" in *TYPE*) echo disk ;; *RM*) echo 1 ;; *MOUNTPOINT*) ;; *) echo stub ;; esac\n',
        "sudo": '#!/bin/bash\n"$@"; rc=$?\ncase "$*" in *bs=4M*) [ -z "$SLOW" ] || sleep 30 ;; esac\nexit $rc\n',
        "eject": "#!/bin/bash\nexit 0\n",
    }
    for n, t in stubs.items():
        with open(os.path.join(d, "bin", n), "w") as f:
            f.write(t)
        os.chmod(os.path.join(d, "bin", n), 0o755)
    image = os.path.join(d, "image")
    with open(image, "wb") as f:
        f.write(b"\x22" * size)

    def disk(name):
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(b"\x11" * size)
            f.seek(sec * 512)
            f.write(line.ljust(512, b"\0"))
        return p

    def at(p, s):
        with open(p, "rb") as f:
            f.seek(s * 512)
            return f.read(512)

    env = dict(os.environ, PATH=os.path.join(d, "bin") + ":" + os.environ["PATH"], KEEP="32510:ddr_tune=",
               TMPDIR=os.path.join(d, "tmp"), EJECT="1")
    dev = disk("dev1")
    r = subprocess.run(["bash", os.path.join(d, "flash.sh"), image, dev, "0"], input="yes\n", env=env,
                       capture_output=True, text=True)
    m.cell("flash.sh whole: the image written, the tune line kept, no warning, no file left",
           r.returncode == 0 and at(dev, sec) == line.ljust(512, b"\0") and at(dev, sec + 1) == b"\x22" * 512 and
           "warning" not in r.stderr and not os.listdir(env["TMPDIR"]), "rc %d %s" % (r.returncode, r.stderr[-300:]))
    dev = disk("dev0")
    with open(dev, "r+b") as f:
        f.seek(sec * 512)
        f.write(b"\0" * 512)
    r = subprocess.run(["bash", os.path.join(d, "flash.sh"), image, dev, "0"], input="yes\n", env=env,
                       capture_output=True, text=True)
    m.cell("flash.sh empty sector: the image's, no warning about its zeros",
           r.returncode == 0 and at(dev, sec) == b"\x22" * 512 and "warning" not in r.stderr,
           "rc %d %s" % (r.returncode, r.stderr[-300:]))
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        dev = disk("dev-%d" % sig)
        p = subprocess.Popen(["bash", os.path.join(d, "flash.sh"), image, dev, "0"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(env, SLOW="1"), start_new_session=True)
        p.stdin.write("yes\n")
        p.stdin.flush()
        end = time.time() + 10
        while time.time() < end and at(dev, sec + 1) != b"\x22" * 512:
            time.sleep(0.1)
        overwritten = at(dev, sec) != line.ljust(512, b"\0")
        os.killpg(p.pid, sig)
        out, err = p.communicate(timeout=30)
        m.cell("flash.sh signal %d to the group past the sector: the line back, failed, file gone" % sig,
               overwritten and at(dev, sec) == line.ljust(512, b"\0") and p.returncode != 0 and
               "kept sectors are back" in err and not os.listdir(env["TMPDIR"]),
               "overwritten %s rc %s: %s" % (overwritten, p.returncode, err[-300:]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", default=PATCH)
    ap.add_argument("--ddr-tune", default=DDR_TUNE)
    ap.add_argument("--keep", default=KEEP)
    a = ap.parse_args()
    m = Matrix()
    with tempfile.TemporaryDirectory(prefix="ddr-tune-test-") as work:
        uboot(m, work, a.patch)
        ddr_tune(m, a.ddr_tune)
        keep(m, work, a.keep)
    print("%d cells failed" % m.bad)
    return 1 if m.bad else 0


if __name__ == "__main__":
    sys.exit(main())
