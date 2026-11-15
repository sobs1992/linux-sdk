"""TGA helpers for NfH: raw rows, decode for previews (16 bit = RGB565)."""
import struct
from PIL import Image

def parse(b):
    idl, cmt, typ = b[0], b[1], b[2]
    w, h, bpp, desc = struct.unpack('<HHBB', b[12:18])
    assert typ == 2 and cmt == 0, (typ, cmt)
    start = 18 + idl
    rowb = w * bpp // 8
    end = start + rowb * h
    rows = [b[start + i * rowb:start + (i + 1) * rowb] for i in range(h)]
    if not desc & 0x20:
        rows.reverse()			# keep rows top-down here
    return dict(head=bytearray(b[:start]), rows=rows, tail=b[end:], w=w, h=h, bpp=bpp, desc=desc)

def build(t):
    rows = list(t['rows'])
    if not t['desc'] & 0x20:
        rows.reverse()
    head = bytearray(t['head'])
    struct.pack_into('<H', head, 14, len(t['rows']))
    data = b''.join(rows)
    tail = bytearray(t['tail'])
    # TGA 2.0: the footer's and the developer directory's offsets are file
    # offsets (NfH keeps its RGB565 masks there): moved with the rows cut
    if len(tail) >= 26 and tail[-18:] == b'TRUEVISION-XFILE.\0':
        delta = (t['h'] - len(t['rows'])) * t['w'] * t['bpp'] // 8
        base = len(head) + len(data)		# file offset of the tail
        ext, dev = struct.unpack_from('<II', tail, len(tail) - 26)
        if ext: ext -= delta
        if dev:
            dev -= delta
            d = dev - base
            (n,) = struct.unpack_from('<H', tail, d)
            for k in range(n):
                tag, off, size = struct.unpack_from('<HII', tail, d + 2 + k * 10)
                struct.pack_into('<HII', tail, d + 2 + k * 10, tag, off - delta if off else 0, size)
        struct.pack_into('<II', tail, len(tail) - 26, ext, dev)
    return bytes(head) + data + bytes(tail)

def image(t):
    w, h = t['w'], len(t['rows'])
    if t['bpp'] == 16:
        out = bytearray()
        for r in t['rows']:
            for (v,) in struct.iter_unpack('<H', r):
                out += bytes(((v >> 11 & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31))
        return Image.frombytes('RGB', (w, h), bytes(out))
    return Image.frombytes('RGB', (w, h), b''.join(t['rows']), 'raw', 'BGR')

def scale_rows(t, rows):
    """the picture resampled to ROWS rows (16 bit RGB565 without alpha, or 24 bit)"""
    import struct
    w, h = t['w'], len(t['rows'])
    if t['bpp'] == 16:
        assert not t['desc'] & 0x0f, 'alpha bits'
        im = image(t).resize((w, rows), Image.LANCZOS)
        px = im.tobytes()
        out = []
        for y in range(rows):
            r = bytearray()
            for x in range(w):
                R, G, B = px[(y * w + x) * 3:(y * w + x) * 3 + 3]
                r += struct.pack('<H', (R >> 3) << 11 | (G >> 2) << 5 | B >> 3)
            out.append(bytes(r))
        t['rows'] = out
    else:
        im = image(t).resize((w, rows), Image.LANCZOS)
        b, g, r_ = im.split()[2], im.split()[1], im.split()[0]
        raw = Image.merge('RGB', (b, g, r_)).tobytes()
        t['rows'] = [raw[y * w * 3:(y + 1) * w * 3] for y in range(rows)]
