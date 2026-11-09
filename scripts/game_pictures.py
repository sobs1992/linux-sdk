#!/usr/bin/env python3
"""
game_pictures.py: pictures from inside a game's archives, for the covers of
scripts/games-image.py ("cover = ARCHIVE:ENTRY" in games/games.manifest).

  scripts/game_pictures.py ARCHIVE --list          # the entries
  scripts/game_pictures.py ARCHIVE ENTRY OUT.png   # one picture

  .lod  Heroes of Might and Magic III (H3bitmap.lod): its .pcx pictures,
        8-bit with a palette or 24-bit. HotA.lod is encrypted: not readable.
  .wad  Doom (doom1.wad, doom.wad...): a picture lump (TITLEPIC, a patch)
        in the PLAYPAL colours, stretched to Doom's 1.2-high pixels.
  .exe  A Windows program (or .dll): entry "icon", its biggest icon picture
        (PNG or 32-bit), with its transparency (RGBA).

Only the directory and the one entry are read, and every size taken from
a file is checked first: a damaged or encrypted archive is an error, never
a huge allocation.
"""
import os
import struct
import sys
import zlib

MAX_ENTRY = 32 << 20	# bytes of one entry, packed or not
MAX_PIXELS = 8 << 20


class PictureError(Exception):
    pass


def _check(cond, what):
    if not cond:
        raise PictureError(what)


def _lod_dir(f, fsize, path):
    head = f.read(92)
    _check(len(head) == 92 and head[:4] == b"LOD\0", "%s: not a LOD archive" % path)
    n = struct.unpack_from("<I", head, 8)[0]
    _check(n <= 100000 and 92 + 32 * n <= fsize, "%s: bad directory" % path)
    table = f.read(32 * n)
    for i in range(n):
        name, off, size, _typ, csize = struct.unpack_from("<16sIIII", table, 32 * i)
        yield name.split(b"\0")[0].decode("latin1"), off, size, csize


def _lod_entry(path, want):
    fsize = os.path.getsize(path)
    with open(path, "rb") as f:
        for name, off, size, csize in _lod_dir(f, fsize, path):
            if name.lower() != want.lower():
                continue
            packed = csize or size
            _check(size <= MAX_ENTRY and packed <= MAX_ENTRY and off + packed <= fsize,
                   "%s: %s: bad size (encrypted archive?)" % (path, name))
            f.seek(off)
            raw = f.read(packed)
            if not csize:
                return raw
            z = zlib.decompressobj()
            data = z.decompress(raw, size + 1)
            _check(len(data) == size, "%s: %s: does not unpack" % (path, name))
            return data
    raise PictureError("%s: no %s" % (path, want))


def _h3pcx(data, what):
    from PIL import Image
    _check(len(data) >= 12, what + ": not a picture")
    size, w, h = struct.unpack_from("<III", data, 0)
    _check(0 < w * h <= MAX_PIXELS and len(data) >= 12 + size, what + ": not a picture")
    if size == w * h:
        _check(len(data) >= 12 + size + 768, what + ": no palette")
        im = Image.frombytes("P", (w, h), data[12:12 + size])
        im.putpalette(data[12 + size:12 + size + 768])
        return im.convert("RGB")
    _check(size == w * h * 3, what + ": not a picture")
    return Image.frombytes("RGB", (w, h), data[12:12 + size], "raw", "BGR")


def _wad_lumps(path, names):
    fsize = os.path.getsize(path)
    found = {}
    with open(path, "rb") as f:
        head = f.read(12)
        _check(len(head) == 12 and head[:4] in (b"IWAD", b"PWAD"), "%s: not a WAD" % path)
        n, dirofs = struct.unpack_from("<II", head, 4)
        _check(n <= 200000 and dirofs + 16 * n <= fsize, "%s: bad directory" % path)
        f.seek(dirofs)
        table = f.read(16 * n)
        for i in range(n):
            off, size, name = struct.unpack_from("<II8s", table, 16 * i)
            name = name.rstrip(b"\0").decode("latin1").upper()
            if names is None:
                found[name] = size
            elif name in names and name not in found:
                _check(size <= MAX_ENTRY and off + size <= fsize, "%s: %s: bad size" % (path, name))
                f.seek(off)
                found[name] = f.read(size)
    return found


def _doom_patch(data, palette, what):
    from PIL import Image
    _check(len(data) >= 8, what + ": not a picture")
    w, h = struct.unpack_from("<HH", data, 0)
    _check(0 < w <= 4096 and 0 < h <= 4096 and len(data) >= 8 + 4 * w, what + ": not a picture")
    pixels = bytearray(w * h)
    for x, at in enumerate(struct.unpack_from("<%dI" % w, data, 8)):
        while 0 <= at < len(data) - 3 and data[at] != 0xFF:	# posts of the column
            top, length = data[at], data[at + 1]
            _check(at + 3 + length <= len(data), what + ": broken column")
            for j in range(min(length, h - top)):
                pixels[(top + j) * w + x] = data[at + 3 + j]
            at += length + 4
    im = Image.frombytes("P", (w, h), bytes(pixels))
    im.putpalette(palette)
    return im.convert("RGB").resize((w, h * 6 // 5), Image.LANCZOS)


def _pe_icons(path):
    """the icon pictures (RT_ICON resources) of a PE file: their data"""
    with open(path, "rb") as f:
        d = f.read(MAX_ENTRY * 4)
    _check(d[:2] == b"MZ" and len(d) >= 0x40, path + ": not a Windows program")
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    _check(pe + 26 <= len(d) and d[pe:pe + 4] == b"PE\0\0", path + ": not a PE file")
    nsec, optsz = struct.unpack_from("<HH", d, pe + 6)[0], struct.unpack_from("<H", d, pe + 20)[0]
    magic = struct.unpack_from("<H", d, pe + 24)[0]
    dd = pe + 24 + (96 if magic == 0x10B else 112) + 8 * 2	# IMAGE_DIRECTORY_ENTRY_RESOURCE
    _check(dd + 8 <= len(d), path + ": no resources")
    rva = struct.unpack_from("<I", d, dd)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + optsz + 40 * i
        _check(o + 40 <= len(d), path + ": damaged sections")
        vs, va, rs, ra = struct.unpack_from("<IIII", d, o + 8)
        secs.append((va, max(vs, rs), ra))

    def off(r):
        for va, size, ra in secs:
            if va <= r < va + size and ra + r - va < len(d):
                return ra + r - va
        raise PictureError(path + ": damaged resources")

    base = off(rva)

    def entries(o):
        _check(o + 16 <= len(d), path + ": damaged resources")
        n = sum(struct.unpack_from("<HH", d, o + 12))
        _check(n < 4096 and o + 16 + 8 * n <= len(d), path + ": damaged resources")
        return [struct.unpack_from("<II", d, o + 16 + 8 * i) for i in range(n)]

    icons = []
    for kind, p1 in entries(base):
        if kind != 3 or not p1 & 0x80000000:	# RT_ICON
            continue
        for _name, p2 in entries(base + (p1 & 0x7FFFFFFF)):
            for _lang, p3 in entries(base + (p2 & 0x7FFFFFFF)):
                _check(base + p3 + 8 <= len(d), path + ": damaged resources")
                drva, size = struct.unpack_from("<II", d, base + p3)
                o = off(drva)
                _check(size <= MAX_ENTRY and o + size <= len(d), path + ": damaged icon")
                icons.append(d[o:o + size])
    return icons


def _icon(data, what):
    """an RT_ICON picture: PNG, or a 32-bit DIB (bottom-up, twice as high)"""
    import io
    from PIL import Image
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        im = Image.open(io.BytesIO(data))
        _check(im.width * im.height <= MAX_PIXELS, what + ": too big")
        return im.convert("RGBA")
    _check(len(data) >= 40, what + ": damaged icon")
    hsize, w, h2, _planes, bpp = struct.unpack_from("<IiiHH", data, 0)
    h = h2 // 2
    _check(bpp == 32 and 0 < w <= 1024 and 0 < h <= 1024 and hsize + w * h * 4 <= len(data),
           what + ": only 32-bit icons")
    im = Image.frombuffer("RGBA", (w, h), data[hsize:hsize + w * h * 4], "raw", "BGRA", 0, -1)
    return im.copy()


def picture(archive, entry):
    """the picture ENTRY of ARCHIVE (.lod, .wad, .exe) as a PIL image: RGB,
    an icon RGBA"""
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise PictureError("pictures need Python's PIL (apt install python3-pil)")
    ext = os.path.splitext(archive)[1].lower()
    what = "%s:%s" % (archive, entry)
    if ext == ".lod":
        return _h3pcx(_lod_entry(archive, entry), what)
    if ext == ".wad":
        lumps = _wad_lumps(archive, {"PLAYPAL", entry.upper()})
        _check("PLAYPAL" in lumps and len(lumps["PLAYPAL"]) >= 768, archive + ": no PLAYPAL")
        _check(entry.upper() in lumps, "%s: no %s" % (archive, entry))
        return _doom_patch(lumps[entry.upper()], lumps["PLAYPAL"][:768], what)
    if ext in (".exe", ".dll"):
        _check(entry.lower() == "icon", "%s: only \"icon\"" % what)
        icons = []
        for data in _pe_icons(archive):
            try:
                icons.append(_icon(data, what))
            except PictureError:
                pass	# 8-bit and smaller ones
        _check(icons, archive + ": no 32-bit icon")
        return max(icons, key=lambda im: im.width * im.height)
    raise PictureError("%s: .lod, .wad or .exe only" % archive)


def entries(archive):
    """(name, size) of every entry"""
    ext = os.path.splitext(archive)[1].lower()
    if ext == ".lod":
        with open(archive, "rb") as f:
            return [(n, s) for n, _o, s, _c in _lod_dir(f, os.path.getsize(archive), archive)]
    if ext == ".wad":
        return sorted(_wad_lumps(archive, None).items())
    raise PictureError("%s: .lod or .wad only" % archive)


def main():
    args = sys.argv[1:]
    try:
        if len(args) == 2 and args[1] == "--list":
            for name, size in entries(args[0]):
                print("%-16s %d" % (name, size))
        elif len(args) == 3:
            picture(args[0], args[1]).save(args[2])
        else:
            sys.exit(__doc__.strip().split("\n\n")[1])
    except (OSError, PictureError) as e:
        sys.exit("game_pictures: %s" % e)


if __name__ == "__main__":
    main()
