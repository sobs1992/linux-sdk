#!/usr/bin/env python3
"""
ea-vp6-shrink.py: Electronic Arts' VP6 movies (.vp6) of a directory made
again at a smaller size, in place, for a decoder that cannot keep up with
the originals: Need for Speed: Most Wanted's 1920x1088 movies played at
~13 fps on the GO Ultra (the game's VP6 decoder is x86 code under Box64),
at 848x480 they play at the game's 30 with the big cores at 1 GHz.

  scripts/ea-vp6-shrink.py [--size 848x480] [--crop W:H:X:Y] [--quant 52]
                           [--jobs 4] [--cache DIR] DIR

Each movie: FFmpeg decodes it (cropped first by --crop, FFmpeg's crop
filter: the movies' 1920x1088 frames are 1920x1080 between 4 black rows),
scales it (lanczos) and scripts/vp6enc.c (built here with the host's cc)
writes the same movie with its video re-encoded: every frame a key frame
at quantiser --quant (VP6's index, higher = finer), the audio chunks as
they were. The result is checked by decoding it again with FFmpeg (no
error, as many frames). Movies already at --size are left alone.

--cache (default lab/images/cache/ea-vp6): the results by the original's
name, size and first and last MiB and the settings, so a games image built
again does not encode for minutes again.

Needs ffmpeg/ffprobe (with the EA demuxer and VP6 decoder) and cc.
"""
import argparse
import concurrent.futures
import hashlib
import os
import shutil
import struct
import subprocess
import sys

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENC_SRC = os.path.join(SDK, "scripts", "vp6enc.c")


def die(msg):
    sys.exit("ea-vp6-shrink: " + msg)


def log(msg):
    print("ea-vp6-shrink: " + msg, flush=True)


def mvhd_size(path):
    """(width, height) of an EA VP6 movie's MVhd, or None"""
    with open(path, "rb") as f:
        h = f.read(32)
    if len(h) < 32 or h[:4] != b"MVhd":
        return None
    return struct.unpack("<HH", h[12:16])


def build_encoder(cache):
    with open(ENC_SRC, "rb") as f:
        tag = hashlib.sha1(f.read()).hexdigest()[:12]
    exe = os.path.join(cache, "vp6enc-" + tag)
    if not os.path.exists(exe):
        os.makedirs(cache, exist_ok=True)
        cc = os.environ.get("HOSTCC", "cc")
        r = subprocess.run([cc, "-O2", "-o", exe + ".tmp", ENC_SRC, "-lm"])
        if r.returncode:
            die("building %s failed" % ENC_SRC)
        os.replace(exe + ".tmp", exe)
    return exe, tag


def key(path, args, enc_tag):
    h = hashlib.sha1()
    st = os.stat(path)
    h.update(("%s %d %s %s %d %s" % (os.path.basename(path), st.st_size, args.size, args.crop,
                                     args.quant, enc_tag)).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if st.st_size > 2 << 20:
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:20]


def other_chunks(path):
    """a digest of every chunk but the video's, in order (the audio)"""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size = struct.unpack("<I", hdr[4:])[0]
            if size < 8:
                raise RuntimeError("%s: bad chunk" % path)
            data = f.read(size - 8)
            if hdr[:4] not in (b"MVhd", b"MV0K", b"MV0F"):
                h.update(hdr + data)
    return h.hexdigest()


def frames(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def shrink(path, args, exe, enc_tag):
    name = os.path.basename(path)
    w, h = args.w, args.h
    if mvhd_size(path) == (w, h):
        return "%s: already %dx%d" % (name, w, h)
    if not mvhd_size(path):
        return "%s: not an EA VP6 movie (no MVhd), left alone" % name
    cached = os.path.join(args.cache, key(path, args, enc_tag) + ".vp6")
    if not os.path.exists(cached):
        tmp = cached + ".tmp"
        vf = ("crop=%s," % args.crop if args.crop else "") + "scale=%d:%d:flags=lanczos" % (w, h)
        dec = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-fps_mode",
                                "passthrough", "-vf", vf, "-pix_fmt", "yuv420p", "-f", "rawvideo",
                                "-"], stdout=subprocess.PIPE)
        enc = subprocess.run([exe, path, tmp, str(w), str(h), str(args.quant)], stdin=dec.stdout,
                             capture_output=True, text=True)
        dec.stdout.close()
        if dec.wait() or enc.returncode:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise RuntimeError("%s: encoding failed: %s" % (name, enc.stderr.strip()))
        # the video decoded again: not one error, as many frames as the
        # original gave; the audio's chunks as they were, byte for byte (only
        # the video is decoded: some originals' audio has errors of its own,
        # bounty_tutorial's "invalid number of samples in packet")
        chk = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", tmp, "-map", "0:v",
                              "-f", "null", "-"], capture_output=True, text=True)
        n_new, n_old = frames(tmp), frames(path)
        if chk.returncode or chk.stderr.strip() or n_new != n_old or n_new <= 0:
            raise RuntimeError("%s: the result does not decode cleanly (%d frames of %d) %s"
                               % (name, n_new, n_old, chk.stderr.strip()[:300]))
        if other_chunks(tmp) != other_chunks(path):
            raise RuntimeError("%s: the audio chunks differ from the original's" % name)
        os.replace(tmp, cached)
        note = enc.stderr.strip().splitlines()[-1].replace("vp6enc: ", "")
    else:
        note = "from the cache"
    old = os.path.getsize(path)
    tmp = path + ".shrink"
    shutil.copyfile(cached, tmp)
    os.replace(tmp, path)
    return "%s: %d -> %d MB (%s)" % (name, old >> 20, os.path.getsize(path) >> 20, note)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir")
    ap.add_argument("--size", default="848x480")
    ap.add_argument("--crop", default="")
    ap.add_argument("--quant", type=int, default=52)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--cache", default=os.path.join(SDK, "lab", "images", "cache", "ea-vp6"))
    args = ap.parse_args()
    try:
        args.w, args.h = (int(x) for x in args.size.lower().split("x"))
    except ValueError:
        die("--size WxH")
    if args.w % 16 or args.h % 16:
        die("--size: VP6 needs multiples of 16")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die("needs %s" % tool)
    movies = sorted(os.path.join(args.dir, n) for n in os.listdir(args.dir)
                    if n.lower().endswith(".vp6"))
    if not movies:
        die("%s: no .vp6" % args.dir)
    os.makedirs(args.cache, exist_ok=True)
    exe, tag = build_encoder(args.cache)
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for fut in concurrent.futures.as_completed([pool.submit(shrink, m, args, exe, tag)
                                                    for m in movies]):
            try:
                log(fut.result())
            except RuntimeError as e:
                log(str(e))
                failed += 1
    if failed:
        die("%d of %d movies failed (left as they were)" % (failed, len(movies)))


if __name__ == "__main__":
    main()
