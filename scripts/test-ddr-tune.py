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
struct bd_info { int x; };
static int fdt_find_or_add_subnode(void *blob, int parent, const char *name)
{
	(void)blob; (void)parent;
	return strcmp(name, "chosen") ? -1 : 7;
}
static int fdt_setprop_string(void *blob, int node, const char *name, const char *v)
{
	(void)blob;
	printf("prop %d %s=%s\n", node, name, v);
	return 0;
}
"""

MAIN = r"""
int main(int argc, char **argv)
{
	FILE *f = fopen(argv[1], "rb");
	size_t n = fread(sector, 1, sizeof sector, f);
	unsigned c, v;

	(void)n;
	fclose(f);
	for (unsigned i = 0; i < 0x20000; i++)
		regs[i] = 5;
	if (argc > 2 && (f = fopen(argv[2], "r"))) {	/* "CSR VALUE" lines: what BL2 trained */
		while (fscanf(f, "%x %x", &c, &v) == 2)
			regs[c & 0x1ffff] = v;
		fclose(f);
	}
	ogu_ddr_tune();
	meson_ft_board_setup(NULL, NULL);
	printf("done %s\n", ogu_tune_done);
	printf("lift %s\n", ogu_tune_lift);
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
    a = text.index("#define OGU_PBD")
    b = text.index("\n}\n", text.index("int meson_ft_board_setup")) + 3
    return text[a:b]


def uboot(m, work, patch):
    c = os.path.join(work, "tune.c")
    exe = os.path.join(work, "tune")
    with open(c, "w") as f:
        f.write(STUBS + uboot_code(patch) + MAIN)
    subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-o", exe, c], check=True)

    fdt_bad = []

    def run(line, trained=None, lift=False):
        s = os.path.join(work, "sector")
        data = ("ddr_tune=%s\n" % line).encode()
        with open(s, "wb") as f:
            f.write(data + b"\0" * (512 - len(data)))
        t = os.path.join(work, "trained")
        with open(t, "w") as f:
            for c, v in (trained or {}).items():
                f.write("%x %x\n" % (c, v))
        out = subprocess.run([exe, s, t], capture_output=True, text=True, check=True).stdout.splitlines()
        done = [l for l in out if l.startswith("done ")][0][5:].split()
        lifted = [l for l in out if l.startswith("lift ")][0][5:].split()
        props = dict(l[len("prop 7 "):].split("=", 1) for l in out if l.startswith("prop 7 "))
        # what the kernel gets in /chosen is what was recorded
        if props.get("ddr-tune", "").split() != done or props.get("ddr-tune-lift", "").split() != lifted:
            fdt_bad.append((line, props, done, lifted))
        regs = dict(l.split("=") for l in out if re.match(r"^[0-9a-f]{5}=", l))
        regs = {k: int(v) for k, v in regs.items()}
        return (done, regs, lifted) if lift else (done, regs)

    done, regs = run(" ".join(c + "+1" for c in ALL44))
    m.cell("uboot all44: 44 CSRs moved", len(ALL44) == 44 and all(regs[c] == 6 for c in ALL44), str(regs))
    m.cell("uboot all44: 44 CSRs recorded for /chosen", len(done) == 44 and
           sorted(d[:5] for d in done) == sorted(ALL44) and all(d.endswith(":0005>0006") for d in done),
           "%d recorded: %s" % (len(done), done[-3:]))
    done, regs = run("11668+10 1118c-2 11668x 13768+3f")
    m.cell("uboot parse: a bad entry ends the line, the ones before it stay",
           regs["11668"] == 0x15 and regs["1118c"] == 3 and regs["13768"] == 5 and len(done) == 2, str(done))
    done, regs = run("11668-9 13768+3f 21668+1")
    m.cell("uboot clamp: within 0..3f; another block refused",
           regs["11668"] == 0 and regs["13768"] == 0x3f and len(done) == 2, str(done))

    # the median: DBYTE0 nibble 0 trained 6 0 2 6
    def nib(vals, db=0, u=0):
        return {0x10068 | db << 12 | (4 * u + i) << 8: v for i, v in enumerate(vals)}
    done, regs, lifted = run("10268@+0", nib([6, 0, 2, 6]), True)
    m.cell("uboot median: 10268@+0 -> the median of 6 0 6 = 6",
           regs["10268"] == 6 and [regs["10068"], regs["10168"], regs["10368"]] == [6, 0, 6] and
           done == ["10268:0002>0006"] and lifted == [], "%s %s" % (done, regs))
    done, regs = run("10268@+0", nib([2, 6, 0, 10]))
    m.cell("uboot median: the middle one of three different neighbours (2 6 10 -> 6)", regs["10268"] == 6,
           str(regs["10268"]))
    done, regs = run("10268@+0", nib([6, 0, 6, 6]))
    m.cell("uboot median: the lane's own value does not count (6 instead of 2: still 6, nothing moved)",
           regs["10268"] == 6 and done == [], str(done))
    done, regs = run("10268@-4", nib([8, 2, 2, 8]))
    m.cell("uboot median: follows the neighbours (8 2 8 -> 8, -4 = 4)", regs["10268"] == 4, str(regs["10268"]))
    done, regs = run("13368@+3", nib([4, 4, 4, 9], db=3, u=0))
    m.cell("uboot median: DBYTE3 lane 3: 4 4 4 -> 4 + 3 = 7", regs["13368"] == 7, str(regs["13368"]))
    done, regs, lifted = run("10068@-4", nib([0, 0, 0, 0]), True)
    m.cell("uboot lift: a lane below 0 lifts its nibble: 0 4 4 4, lift recorded",
           [regs["10068"], regs["10168"], regs["10268"], regs["10368"]] == [0, 4, 4, 4] and
           lifted == ["1008c+4"] and sorted(done) == ["10168:0000>0004", "10268:0000>0004", "10368:0000>0004"],
           "%s %s %s" % ([regs["10068"], regs["10168"], regs["10268"], regs["10368"]], done, lifted))
    done, regs, lifted = run("10068@-4 10168+2", nib([0, 0, 0, 0]), True)
    m.cell("uboot lift: a move in a lifted nibble is lifted too (0+2+4)",
           regs["10168"] == 6 and regs["10068"] == 0 and lifted == ["1008c+4"], str(regs))
    done, regs, lifted = run("10168-4", nib([0, 0, 0, 0]), True)
    m.cell("uboot lift: a move below 0 is clamped as before, no lift", regs["10168"] == 0 and lifted == [], str(regs))
    done, regs = run("11668@+3f", nib([2, 2, 2, 2], db=1, u=1))
    m.cell("uboot median: within 0..3f at the top", regs["11668"] == 0x3f, str(regs["11668"]))
    done, regs = run("10868@+1 1008c@+1 11668@+9", nib([2, 2, 2, 2], db=1, u=1))
    m.cell("uboot median: @ on lane 8 or a strobe refused, the rest taken",
           regs["10868"] == 5 and regs["1008c"] == 5 and regs["11668"] == 11, str(done))
    done, regs = run("11668@+9 11668+1", nib([2, 2, 2, 2], db=1, u=1))
    m.cell("uboot twice: the second entry of a CSR refused", regs["11668"] == 11, str(regs["11668"]))
    done, regs, lifted = run("10068@-4", nib([0, 0, 0, 0]), True)
    m.cell("uboot /chosen: ddr-tune and ddr-tune-lift as recorded, in every run so far", not fdt_bad and lifted,
           str(fdt_bad[:2]))
    done, regs, lifted = run("11668@+9 13468@-6", {**nib([2, 2, 2, 2], db=1, u=1), **nib([0, 2, 2, 2], db=3, u=1)}, True)
    m.cell("uboot two nibbles: 11668 = 11; DBYTE3 u1 lifted 4 (2-6 = -4): 0 6 6 6",
           regs["11668"] == 11 and [regs["13468"], regs["13568"], regs["13668"], regs["13768"]] == [0, 6, 6, 6] and
           lifted == ["1318c+4"], "%s %s" % (regs, lifted))


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
    r = run("set", "11668@+9 13468@-4 1118c-2")
    m.cell("ddr-tune @: median entries and moves pass the check (then: no eMMC on the PC)",
           r.returncode == 1 and "no eMMC" in r.stderr, r.stderr)
    for bad in ("11868@+1", "1118c@-1"):
        r = run("set", bad)
        m.cell("ddr-tune @: %s refused (lanes 0-7 only)" % bad, r.returncode == 1 and "@ takes" in r.stderr, r.stderr)
    r = run("set", "11668@+9 11668-1")
    m.cell("ddr-tune @: a CSR twice in both forms refused", r.returncode == 1 and "11668 twice" in r.stderr, r.stderr)


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
        # root may not create into another user's file in /tmp (protected_regular): of= into TMPDIR refused;
        # SLOW: the image's dd sleeps 30 s after it wrote, SLOW_BEFORE: 2 s before it starts
        "sudo": ('#!/bin/bash\ncase "$*" in *of="$TMPDIR"*) echo "dd: Permission denied" >&2; exit 1 ;; esac\n'
                 'case "$*" in *bs=4M*) [ -z "$SLOW_BEFORE" ] || sleep 2 ;; esac\n'
                 '"$@"; rc=$?\ncase "$*" in *bs=4M*) [ -z "$SLOW" ] || sleep 30 ;; esac\nexit $rc\n'),
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
    for sig in (signal.SIGTERM, signal.SIGHUP):
        # the signal to flash.sh alone, before its dd has written: the trap stops dd first
        dev = disk("dev-alone-%d" % sig)
        p = subprocess.Popen(["bash", os.path.join(d, "flash.sh"), image, dev, "0"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=dict(env, SLOW_BEFORE="1"), start_new_session=True)
        p.stdin.write("yes\n")
        p.stdin.flush()
        time.sleep(1.0)
        p.send_signal(sig)
        out, err = p.communicate(timeout=30)
        time.sleep(3)   # a dd left running would have written by now
        m.cell("flash.sh signal %d to the script alone: dd stopped, the line stays" % sig,
               at(dev, sec) == line.ljust(512, b"\0") and p.returncode != 0, "rc %s: %s" % (p.returncode, err[-300:]))
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
