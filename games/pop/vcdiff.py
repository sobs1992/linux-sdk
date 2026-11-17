#!/usr/bin/env python3
"""A VCDIFF (RFC 3284) decoder for xdelta3's deltas without secondary
compression, as the Russian edition of Prince of Persia: The Sands of Time
comes (games/pop/prepare.sh): what "xdelta3 -d -s SOURCE DELTA OUTPUT"
does, without xdelta3 on the PC.

  vcdiff.py SOURCE DELTA OUTPUT   OUTPUT made; each window's target checked
                                  against xdelta's Adler-32 (another version
                                  of SOURCE fails there)
  vcdiff.py --size DELTA          the size of the file the delta makes
"""
import sys
import zlib


def code_table():
    # (type1, size1, mode1, type2, size2, mode2); types: 0 NOOP 1 ADD 2 RUN 3 COPY
    t = [(2, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0)]
    t += [(1, s, 0, 0, 0, 0) for s in range(1, 18)]
    for m in range(9):
        t.append((3, 0, m, 0, 0, 0))
        t += [(3, s, m, 0, 0, 0) for s in range(4, 19)]
    for m in range(6):
        for a in range(1, 5):
            t += [(1, a, 0, 3, c, m) for c in range(4, 7)]
    for m in range(6, 9):
        t += [(1, a, 0, 3, 4, m) for a in range(1, 5)]
    for m in range(9):
        t.append((3, 4, m, 1, 1, 0))
    assert len(t) == 256
    return t


TABLE = code_table()


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def byte(self):
        b = self.d[self.p]
        self.p += 1
        return b

    def int(self):
        v = 0
        while True:
            b = self.byte()
            v = (v << 7) | (b & 0x7F)
            if not b & 0x80:
                return v

    def take(self, n):
        s = self.d[self.p:self.p + n]
        if len(s) != n:
            raise ValueError("truncated")
        self.p += n
        return s


def header(delta):
    r = Reader(delta)
    if r.take(4) != b"\xd6\xc3\xc4\x00":
        raise ValueError("not VCDIFF")
    hdr = r.byte()
    if hdr & 0x01:
        raise ValueError("secondary compression not supported")
    if hdr & 0x02:
        raise ValueError("custom code table not supported")
    if hdr & 0x04:
        r.take(r.int())
    return r


def target_size(delta_path):
    """the sum of the windows' target lengths"""
    delta = open(delta_path, "rb").read()
    r = header(delta)
    total = 0
    while r.p < len(delta):
        wi = r.byte()
        if wi & 0x03:
            r.int()
            r.int()
        n = r.int()
        start = r.p
        total += r.int()
        r.p = start + n
    return total


def decode(src_path, delta_path, out_path):
    delta = open(delta_path, "rb").read()
    r = header(delta)
    src = open(src_path, "rb")
    out = open(out_path, "wb")
    windows = 0
    total = 0
    while r.p < len(delta):
        wi = r.byte()
        if wi & 0x02:
            raise ValueError("VCD_TARGET windows not supported")
        seg = b""
        if wi & 0x01:
            seg_len = r.int()
            seg_pos = r.int()
            src.seek(seg_pos)
            seg = src.read(seg_len)
            if len(seg) != seg_len:
                raise ValueError("source too short (another version of the file?)")
        r.int()  # length of the delta encoding
        tlen = r.int()
        if r.byte():
            raise ValueError("compressed sections not supported")
        dlen, ilen, alen = r.int(), r.int(), r.int()
        cksum = int.from_bytes(r.take(4), "big") if wi & 0x04 else None
        data = Reader(r.take(dlen))
        inst = Reader(r.take(ilen))
        addr = Reader(r.take(alen))
        near = [0] * 4
        same = [0] * (3 * 256)
        nslot = 0
        slen = len(seg)
        tgt = bytearray()
        while inst.p < len(inst.d):
            e = TABLE[inst.byte()]
            for typ, size, mode in ((e[0], e[1], e[2]), (e[3], e[4], e[5])):
                if typ == 0:
                    continue
                if size == 0:
                    size = inst.int()
                if typ == 1:
                    tgt += data.take(size)
                elif typ == 2:
                    tgt += data.take(1) * size
                else:
                    here = slen + len(tgt)
                    if mode == 0:
                        a = addr.int()
                    elif mode == 1:
                        a = here - addr.int()
                    elif mode < 6:
                        a = near[mode - 2] + addr.int()
                    else:
                        a = same[(mode - 6) * 256 + addr.byte()]
                    near[nslot] = a
                    nslot = (nslot + 1) % 4
                    same[a % (3 * 256)] = a
                    if a + size <= slen:
                        tgt += seg[a:a + size]
                    else:
                        if a < slen:
                            n = slen - a
                            tgt += seg[a:]
                            a, size = slen, size - n
                        t = a - slen
                        if t + size <= len(tgt):
                            tgt += tgt[t:t + size]
                        else:
                            for i in range(size):
                                tgt.append(tgt[t + i])
        if len(tgt) != tlen:
            raise ValueError("window %d: %d bytes, %d expected" % (windows, len(tgt), tlen))
        if cksum is not None and zlib.adler32(bytes(tgt)) != cksum:
            raise ValueError("window %d: checksum differs (another version of the source?)" % windows)
        out.write(tgt)
        windows += 1
        total += tlen
    out.close()
    print("%s: %d windows, %d bytes, checksums ok" % (out_path, windows, total))


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--size":
            print(target_size(sys.argv[2]))
        elif len(sys.argv) == 4:
            decode(*sys.argv[1:4])
        else:
            sys.exit(__doc__)
    except (OSError, ValueError, IndexError) as e:
        sys.exit("vcdiff.py: %s: %s" % (sys.argv[-2] if len(sys.argv) > 2 else "", e))
