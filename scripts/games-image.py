#!/usr/bin/env python3
"""
games-image.py: the games of a manifest (games/games.manifest) onto a games
card, or a complete disk image with them, from the firmware's image.

  scripts/games-image.py [-m MANIFEST] [--work DIR] [--games GAME,GAME...] [--reuse]
                         --card DIR [--delete] [--board HOST]
  scripts/games-image.py [-m MANIFEST] [--work DIR] [--games GAME,GAME...] [--reuse]
                         [--out DIR] [--only sd|emmc]

--card: the games into a mounted "GAMES" file system, a directory per game:
the GO Ultra's SD card of games (exFAT), in this PC's card reader or shared
by the board over USB (bare_app's "USB disk", usb-disk). rsync copies only
what changed, so a run after a change to one game is quick. Games already
on the card that the manifest does not name stay; --delete also removes
files from a game's directory that the manifest no longer puts there (and
any put there by hand). Files of the manifest's "data" lines belong on the
board's /data: --board HOST (root@192.168.7.2 over the USB cable) copies
them there over ssh.

Without --card: a disk image, for a firmware with a games partition on its
own disk (IMAGE_DATA_SIZE_MB: the OGA's SD card).

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
per game (see games/games.manifest for every key); what a section says is
done by scripts/gamerecipe.py, which the board's game-install uses too. Games are put together
in <work>/games and <work>/data first (on a disk with room: lab/images),
then made into the partitions with mke2fs -d and mtools: no root, no loop
devices. --reuse keeps what is already in <work> for games not named by
--games (only those are copied again).

Writing an image: make FW=<fw> flash IMAGE_FILE=<image> DEV=/dev/sdX, or for
the eMMC (Vol+ at power-on) make FW=<fw> flash-emmc IMAGE_EMMC_FILE=<image>.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import gamerecipe
from gamerecipe import RecipeError

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
gamerecipe.ROOT = SDK


def die(msg):
    sys.exit("games-image: " + msg)


def log(msg):
    print("games-image: " + msg, flush=True)


def sdk_path(p):
    p = os.path.expanduser(p)
    return p if os.path.isabs(p) else os.path.join(SDK, p)


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


def card_need(games, dirs, card):
    """bytes the card still needs for these game directories: files not
    there yet or of another size (rsync copies those)"""
    need = 0
    for gdir in dirs:
        top = os.path.join(games, gdir)
        for d, _, files in os.walk(top):
            for f in files:
                src = os.path.join(d, f)
                dst = os.path.join(card, os.path.relpath(src, games))
                size = os.path.getsize(src)
                try:
                    if os.path.getsize(dst) == size:
                        continue
                    size -= os.path.getsize(dst)
                except OSError:
                    pass
                need += max(size, 0)
    return need


def fill_card(games, dirs, card, delete):
    """the game directories into the mounted card: only what changed (size
    or time; FAT and exFAT keep times to 2 s and 10 ms), no owners or modes,
    which those file systems do not have"""
    if not os.path.isdir(card):
        die("%s: not a directory (the card, mounted)" % card)
    if not os.path.ismount(card):
        log("%s is not a mount point: copying there all the same" % card)
    need, st = card_need(games, dirs, card), os.statvfs(card)
    free = st.f_bavail * st.f_frsize
    log("card %s: %d MiB to copy, %d MiB free" % (card, need // 2**20, free // 2**20))
    if need > free:
        die("the games do not fit on the card")
    for gdir in dirs:
        log("card: /games/%s" % gdir)
        run(["rsync", "-rt", "--modify-window=1", "--info=stats0"] +
            (["--delete"] if delete else []) +
            [os.path.join(games, gdir) + "/", os.path.join(card, gdir) + "/"])
    run(["sync", "-f", card])


def data_to_board(data, host):
    """the manifest's "data" files onto the board's /data, owned by root"""
    if not os.listdir(data):
        return
    log("data: %s -> %s:/data" % (data, host))
    tar = subprocess.Popen(["tar", "-C", data, "--owner=0", "--group=0", "-cf", "-", "."],
                           stdout=subprocess.PIPE)
    ssh = subprocess.run(["ssh", host, "tar -xf - -C /data && sync"], stdin=tar.stdout)
    tar.stdout.close()
    if tar.wait() or ssh.returncode:
        die("could not copy the data files to %s" % host)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-m", "--manifest", default=os.path.join(SDK, "games", "games.manifest"))
    ap.add_argument("--out", help="directory for the images (the manifest's out)")
    ap.add_argument("--work", help="directory to put the games together in (the manifest's work)")
    ap.add_argument("--card", help="the games onto this mounted games card (no image)")
    ap.add_argument("--delete", action="store_true",
                    help="--card: remove files of a game's directory that the manifest does not put there")
    ap.add_argument("--board", help="--card: the data files onto this board's /data (ssh host)")
    ap.add_argument("--only", choices=("sd", "emmc"), help="one of the two images")
    ap.add_argument("--games", help="only these sections, comma separated (with --reuse: copy them again)")
    ap.add_argument("--reuse", action="store_true", help="keep the games already in <work>")
    a = ap.parse_args()

    try:
        sections = gamerecipe.read_manifest(a.manifest)
    except RecipeError as e:
        die(str(e))
    image = dict(next((s for n, s in sections if n == "image"), {}))
    games_sec = [(n, s) for n, s in sections if n != "image"]
    fw = image.get("fw", "ogu")
    out = (os.path.abspath(os.path.expanduser(a.out)) if a.out else
           sdk_path(image.get("out", os.path.join("output", fw, "images"))))
    work = (os.path.abspath(os.path.expanduser(a.work)) if a.work else
            sdk_path(image.get("work", os.path.join(out, "games-work"))))
    if not os.path.isdir(os.path.join(SDK, "lab")):
        log("lab: no link to the project's data (ln -s /media/D/OdroidLab lab, games/README.md)")
    pick = set(a.games.split(",")) if a.games else None
    if pick and pick - {n for n, _ in games_sec}:
        die("no section %s in %s" % (", ".join(pick - {n for n, _ in games_sec}), a.manifest))

    if not a.card and (a.delete or a.board):
        die("--delete and --board go with --card")
    start_mb = image.get("data_start_mb") or fw_value(fw, "IMAGE_DATA_START_MB")
    size_mb = image.get("data_size_mb") or fw_value(fw, "IMAGE_DATA_SIZE_MB")
    if not a.card and (not start_mb or not size_mb):
        die("%s: no games partition in its image (IMAGE_DATA_START_MB, IMAGE_DATA_SIZE_MB): "
            "its games go onto an SD card, --card DIR (the card mounted)" % fw)

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
        try:
            gamerecipe.install_game(name, g, games, data, log=log)
        except (RecipeError, OSError) as e:
            die(str(e))

    if a.card:
        fill_card(games, [g.get("dir", n) for n, g in games_sec if not pick or n in pick],
                  os.path.abspath(os.path.expanduser(a.card)), a.delete)
        if a.board:
            data_to_board(data, a.board)
        elif os.listdir(data):
            log("files for the board's /data are in %s: --board root@192.168.7.2 copies them" % data)
        return

    data_start, data_size = int(start_mb) * 2048, int(size_mb) * 2048
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
