#!/usr/bin/env python3
"""
games-image.py: a complete disk image with the games, from the firmware's
image and a manifest (games/games.manifest).

  scripts/games-image.py [-m MANIFEST] [--out DIR] [--work DIR] [--only sd|emmc]
                         [--games GAME,GAME...] [--reuse]

The firmware's images (make image: images/<fw>.img and <fw>-emmc.img) hold
only BOOT and the rootfs; /etc/init.d/S05data adds the data partitions on
the first boot. This adds them in the image, filled, where S05data looks
for them (IMAGE_DATA_START_MB, IMAGE_DATA_SIZE_MB of configs/<fw>_defconfig),
so the first boot finds and keeps them:

  p3  ext4 "data" on /data: files of the manifest's "data" lines (fonts
      in the Wine prefix...), saved games and settings later
  p4  FAT32 "GAMES" on /games: a directory per game of the manifest, as
      big as the games plus games_free_mb (or games_size_mb)

The manifest is an ini file: [image] for the whole image, then a [section]
per game (see games/games.manifest for every key). Games are put together
in <work>/games and <work>/data first (on a disk with room: /media/D...),
then made into the partitions with mke2fs -d and mtools: no root, no loop
devices. --reuse keeps what is already in <work> for games not named by
--games (only those are copied again).

Writing an image: make FW=<fw> flash IMAGE_FILE=<image> DEV=/dev/sdX, or for
the eMMC (Vol+ at power-on) make FW=<fw> flash-emmc IMAGE_EMMC_FILE=<image>.
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVER = 240		# px: the home screen's tile on the GO Ultra
MULTI = ("exclude", "file", "data")	# keys that may come more than once


def die(msg):
    sys.exit("games-image: " + msg)


def log(msg):
    print("games-image: " + msg, flush=True)


def sdk_path(p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(SDK, p)


def read_manifest(path):
    """[(section, {key: value or [values]})] in file order"""
    sections, cur = [], None
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        s = re.sub(r"(^|\s)[;#].*$", "", line).strip()
        if not s:
            continue
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            cur = {}
            sections.append((m.group(1).strip(), cur))
            continue
        if "=" not in s or cur is None:
            die("%s:%d: %s?" % (path, n, s))
        k, v = (x.strip() for x in s.split("=", 1))
        if k in MULTI:
            cur.setdefault(k, []).append(v)
        else:
            cur[k] = v
    return sections


def fw_value(fw, name):
    cfg = os.path.join(SDK, "configs", fw + "_defconfig")
    for line in open(cfg):
        m = re.match(r"\s*%s\s*:?=\s*(\S+)" % re.escape(name), line)
        if m:
            return m.group(1)
    return None


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        die("failed: %s" % " ".join(cmd))
    return r


def arrow(spec):
    """"SRC -> DST" or "SRC": (SRC, DST or None)"""
    if "->" in spec:
        a, b = spec.split("->", 1)
        return a.strip(), b.strip()
    return spec.strip(), None


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
    """files of a glob, SDK-relative unless absolute; at least one"""
    found = sorted(glob.glob(sdk_path(spec)))
    if not found:
        die("%s: not found" % spec)
    return found


def load_picture(spec, alpha=False):
    """a picture file, or ARCHIVE:ENTRY of a game (game_pictures.py)"""
    from PIL import Image
    m = re.match(r"^(.+\.(?:lod|wad|exe|dll)):([^/:]+)$", spec, re.I)
    try:
        if m:
            import game_pictures
            im = game_pictures.picture(sdk_path(m.group(1)), m.group(2))
        else:
            im = Image.open(sdk_path(spec))
        return im.convert("RGBA" if alpha else "RGB")
    except Exception as e:
        die("cover %s: %s" % (spec, e))


def make_cover(spec, dst, crop, back_spec=None):
    """spec: a picture file, or ARCHIVE:ENTRY of a game (game_pictures.py);
    crop: center, top, bottom, left, right, "X Y SIZE" in its pixels, or fit
    (all of it, on a blurred, darker copy of itself). With back_spec (a
    picture likewise) the picture, transparent around (an icon), is put
    whole on that one blurred and darker, with a shadow."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        die("covers need Python's PIL (apt install python3-pil)")
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
            die("cover_crop %s: outside the %dx%d picture" % (crop, w, h))
    else:
        s = min(w, h)
        x = {"left": 0, "right": w - s}.get(crop, (w - s) // 2)
        y = {"top": 0, "bottom": h - s}.get(crop, (h - s) // 2)
    im = im.crop((x, y, x + s, y + s)).resize((COVER, COVER), Image.LANCZOS)
    im.save(dst, optimize=True)


def install_game(name, g, games, data):
    gdir = g.get("dir", name)
    dest = os.path.join(games, gdir)
    how = g.get("install", "copy")
    src = g.get("source")
    if src and not os.path.isdir(src):
        die("[%s] source %s: not a directory" % (name, src))
    shutil.rmtree(dest, ignore_errors=True)
    log("[%s] %s %s -> /games/%s" % (name, how, src or "", gdir))
    if how in ("homm3", "halflife"):
        # the SDK's installers put the game into <games>/heroes3, /halflife
        script = os.path.join(SDK, "scripts", how + "-install.sh")
        opts = g.get("options", "").split()
        run([script] + opts + [src, games])
        want = {"homm3": "heroes3", "halflife": "halflife"}[how]
        if gdir != want:
            os.replace(os.path.join(games, want), dest)
    elif how == "copy":
        if not src:
            die("[%s] needs a source" % name)
        excl = [e for x in g.get("exclude", []) for e in x.split()]

        def ignore(d, names):
            rel = os.path.relpath(d, src)
            out = set()
            for n in names:
                p = n if rel == "." else os.path.join(rel, n)
                if any(fnmatch.fnmatch(p, e) or fnmatch.fnmatch(n, e) for e in excl):
                    out.add(n)
            return out
        shutil.copytree(src, dest, ignore=ignore, symlinks=False)
    elif how == "none":
        os.makedirs(dest, exist_ok=True)
    else:
        die("[%s] install = %s? (copy, homm3, halflife, none)" % (name, how))
    for spec in g.get("file", []):
        s, d = arrow(spec)
        for f in sources(s):
            copy_into(f, os.path.join(dest, d) if d else dest + "/")
    if g.get("overlay"):
        o = sdk_path(g["overlay"])
        if not os.path.isdir(o):
            die("[%s] overlay %s: not a directory" % (name, o))
        shutil.copytree(o, dest, dirs_exist_ok=True)
    if g.get("cover"):
        make_cover(g["cover"], os.path.join(dest, "cover.png"), g.get("cover_crop", "center"),
                   g.get("cover_back"))
    if g.get("run"):
        env = dict(os.environ, GAME_DIR=dest, SOURCE=src or "", SDK_DIR=SDK, DATA_DIR=data)
        run([sdk_path(g["run"])], env=env, cwd=SDK)
    for spec in g.get("data", []):
        s, d = arrow(spec)
        if not d:
            die("[%s] data = %s: needs \"-> path on /data\"" % (name, spec))
        for f in sources(s):
            copy_into(f, os.path.join(data, d.lstrip("/")))


def du_bytes(top, cluster):
    """bytes on a FAT with this cluster size: files and directories rounded up"""
    total = 0
    for d, dirs, files in os.walk(top):
        total += cluster * (1 + (len(dirs) + len(files)) * 64 // cluster)	# LFN entries
        for f in files:
            total += -(-os.path.getsize(os.path.join(d, f)) // cluster) * cluster
    return total


def make_games_fat(games, img, free_mb, size_mb):
    cluster = 32768
    need = du_bytes(games, cluster)
    mb = size_mb or (need * 102 // 100 // 2**20 + 64 + free_mb)
    if need > mb * 2**20:
        die("the games (%d MiB) do not fit into games_size_mb = %d" % (need // 2**20, mb))
    log("GAMES: %d MiB of games, a %d MiB FAT32" % (need // 2**20, mb))
    if os.path.exists(img):
        os.remove(img)
    run(["mkfs.vfat", "-F", "32", "-s", str(cluster // 512), "-n", "GAMES", "-C", img,
         str(mb * 1024)], stdout=subprocess.DEVNULL)
    items = [os.path.join(games, n) for n in sorted(os.listdir(games))]
    if items:
        env = dict(os.environ, LC_ALL="C.UTF-8", MTOOLS_SKIP_CHECK="1")
        run(["mcopy", "-i", img, "-s", "-p", "-m", "-b", "-Q"] + items + ["::/"], env=env)
    return mb


def make_data_ext4(data, img, size_mb):
    if os.path.exists(img):
        os.remove(img)
    log("data: %s in a %d MiB ext4" % (subprocess.run(["du", "-sh", data], capture_output=True,
                                                    text=True).stdout.split()[0], size_mb))
    run(["fakeroot", "--", "mke2fs", "-q", "-F", "-t", "ext4", "-L", "data", "-d", data,
         "-E", "root_owner=0:0", img, "%dM" % size_mb])


def put(img, part, start_sector):
    run(["dd", "if=" + part, "of=" + img, "bs=4M", "seek=%d" % (start_sector * 512),
         "oflag=seek_bytes", "conv=sparse,notrunc", "status=none"])


def make_image(base, out, data_img, games_img, data_start, data_size, games_mb):
    if not os.path.isfile(base):
        die("%s: no image, build it first (make FW=... image)" % base)
    table = json.loads(subprocess.run(["sfdisk", "-J", base], capture_output=True, text=True,
                                      check=True).stdout)["partitiontable"]
    parts = table.get("partitions", [])
    if len(parts) != 2:
        die("%s: %d partitions, expected BOOT and the rootfs only" % (base, len(parts)))
    if parts[1]["start"] + parts[1]["size"] > data_start:
        die("%s: the rootfs ends past the data partition's start" % base)
    games_start = data_start + data_size
    games_sectors = games_mb * 2048
    log("%s -> %s" % (os.path.basename(base), out))
    run(["cp", "--sparse=always", base, out + ".tmp"])
    os.truncate(out + ".tmp", (games_start + games_sectors) * 512)
    run(["sfdisk", "-q", "--append", out + ".tmp"], text=True,
        input="start=%d, size=%d, type=83\nstart=%d, size=%d, type=c\n" %
        (data_start, data_size, games_start, games_sectors))
    put(out + ".tmp", data_img, data_start)
    put(out + ".tmp", games_img, games_start)
    os.replace(out + ".tmp", out)
    run(["sfdisk", "-l", out])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-m", "--manifest", default=os.path.join(SDK, "games", "games.manifest"))
    ap.add_argument("--out", help="directory for the images (the manifest's out)")
    ap.add_argument("--work", help="directory to put the games together in (the manifest's work)")
    ap.add_argument("--only", choices=("sd", "emmc"), help="one of the two images")
    ap.add_argument("--games", help="only these sections, comma separated (with --reuse: copy them again)")
    ap.add_argument("--reuse", action="store_true", help="keep the games already in <work>")
    a = ap.parse_args()

    sections = read_manifest(a.manifest)
    image = dict(next((s for n, s in sections if n == "image"), {}))
    games_sec = [(n, s) for n, s in sections if n != "image"]
    fw = image.get("fw", "ogu")
    out = os.path.expanduser(a.out or image.get("out") or os.path.join(SDK, "output", fw, "images"))
    work = os.path.expanduser(a.work or image.get("work") or os.path.join(out, "games-work"))
    pick = set(a.games.split(",")) if a.games else None
    if pick and pick - {n for n, _ in games_sec}:
        die("no section %s in %s" % (", ".join(pick - {n for n, _ in games_sec}), a.manifest))

    start_mb = image.get("data_start_mb") or fw_value(fw, "IMAGE_DATA_START_MB")
    size_mb = image.get("data_size_mb") or fw_value(fw, "IMAGE_DATA_SIZE_MB")
    if not start_mb or not size_mb:
        die("%s: no IMAGE_DATA_START_MB / IMAGE_DATA_SIZE_MB (data partitions)" % fw)
    data_start, data_size = int(start_mb) * 2048, int(size_mb) * 2048

    games, data = os.path.join(work, "games"), os.path.join(work, "data")
    if not a.reuse:
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(games, exist_ok=True)
    os.makedirs(data, exist_ok=True)
    for name, g in games_sec:
        if pick and name not in pick:
            continue
        if a.reuse and not pick and os.path.isdir(os.path.join(games, g.get("dir", name))):
            log("[%s] kept from %s" % (name, work))
            continue
        install_game(name, g, games, data)

    games_img, data_img = os.path.join(work, "games.vfat"), os.path.join(work, "data.ext4")
    games_mb = make_games_fat(games, games_img, int(image.get("games_free_mb", 1024)),
                              int(image.get("games_size_mb", 0)))
    make_data_ext4(data, data_img, int(size_mb))
    os.makedirs(out, exist_ok=True)
    name = image.get("name", fw + "-games")
    imgs = []
    if a.only in (None, "sd"):
        base = sdk_path(image.get("base", "output/%s/images/%s.img" % (fw, fw)))
        imgs.append(os.path.join(out, name + ".img"))
        make_image(base, imgs[-1], data_img, games_img, data_start, data_size, games_mb)
    if a.only in (None, "emmc"):
        base = sdk_path(image.get("base_emmc", "output/%s/images/%s-emmc.img" % (fw, fw)))
        if os.path.isfile(base) or a.only == "emmc":
            imgs.append(os.path.join(out, name + "-emmc.img"))
            make_image(base, imgs[-1], data_img, games_img, data_start, data_size, games_mb)
    for f in imgs:
        log("%s: %.1f GiB (%.1f GiB on disk, sparse)" % (f, os.path.getsize(f) / 2**30,
                                                          os.stat(f).st_blocks * 512 / 2**30))
    for f in imgs:
        if f.endswith("-emmc.img"):
            log("eMMC (Vol+ held at power-on): make FW=%s flash-emmc IMAGE_EMMC_FILE='%s'" % (fw, f))
        else:
            log("SD card: make FW=%s flash IMAGE_FILE='%s' DEV=/dev/sdX" % (fw, f))


if __name__ == "__main__":
    main()
