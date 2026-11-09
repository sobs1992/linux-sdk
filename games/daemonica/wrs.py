#!/usr/bin/env python3
"""wrs.py list|extract FILE.wrs [OUTDIR]: 3D GameStudio A6 WRS2 resources.

Layout: "WRS2", then entries: 32-byte name XOR 0xA5 (zero bytes left
as they are), big-endian compressed and uncompressed sizes, Okumura LZSS (4096 ring, 18 max match,
ring start 0xFEE filled with spaces, flag byte LSB first, 1 = literal)."""
import struct
import sys
import os


def lzss(data, pos, out_size):
    ring = bytearray(b' ' * 4096)
    r = 0xFEE
    out = bytearray()
    flags = 0
    while len(out) < out_size and pos < len(data):
        flags >>= 1
        if not flags & 0x100:
            flags = data[pos] | 0xFF00
            pos += 1
            if pos >= len(data):
                break
        if flags & 1:
            c = data[pos]
            pos += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & 0xFFF
        else:
            if pos + 1 >= len(data):
                break
            i = data[pos] | ((data[pos + 1] & 0xF0) << 4)
            j = (data[pos + 1] & 0x0F) + 3
            pos += 2
            for k in range(j):
                c = ring[(i + k) & 0xFFF]
                out.append(c)
                ring[r] = c
                r = (r + 1) & 0xFFF
    return bytes(out[:out_size]), pos


def entries(data):
    """(name, offset, compressed, size, body) of each entry: a 32-byte name
    XOR 0xA5, big-endian compressed and uncompressed sizes, the data; the
    file starts with "WRS2"."""
    off = 4 if data[:4] == b'WRS2' else 0
    while off + 40 <= len(data):
        name = bytes(c ^ 0xA5 for c in data[off:off + 32] if c).decode('latin1')
        csize, size = struct.unpack_from('>II', data, off + 32)
        body, end = lzss(data[:off + 40 + csize], off + 40, size)
        yield (name, off, csize, size, body)
        off += 40 + csize


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    data = open(path, 'rb').read()
    for name, off, hdr, size, body in entries(data):
        print('0x%08x %-32s %8d -> %8d%s' % (off, name, hdr, size, '' if len(body) == size else ' BAD %d' % len(body)))
        if cmd == 'extract':
            out = os.path.join(sys.argv[3], name.replace('\\', '_').replace('/', '_'))
            open(out, 'wb').write(body)


main()
