"""Okumura LZSS as the A6 engine unpacks it (4096 ring of spaces, start
0xFEE, matches 3..18, flag byte LSB first, 1 = literal): a greedy packer
that only refers to bytes it has written itself, never overlapping the
copy, so any such decoder gives the input back."""


def pack(data):
    out = bytearray()
    heads = {}
    n = len(data)
    p = 0
    while p < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if p >= n:
                break
            best_len, best_q = 0, 0
            if p + 3 <= n:
                for q in reversed(heads.get(data[p:p + 3], ())):
                    if p - q > 4096 - 18:
                        break
                    limit = min(18, n - p, p - q)
                    if limit < 3:
                        continue
                    k = 3
                    while k < limit and data[q + k] == data[p + k]:
                        k += 1
                    if k > best_len:
                        best_len, best_q = k, q
                        if k == 18:
                            break
            if best_len >= 3:
                ring = (0xFEE + best_q) & 0xFFF
                out.append(ring & 0xFF)
                out.append(((ring >> 4) & 0xF0) | (best_len - 3))
                step = best_len
            else:
                flags |= 1 << bit
                out.append(data[p])
                step = 1
            for i in range(p, p + step):
                if i + 3 <= n:
                    lst = heads.setdefault(data[i:i + 3], [])
                    lst.append(i)
                    if len(lst) > 64:
                        del lst[:-64]
            p += step
        out[flag_at] = flags
    return bytes(out)


if __name__ == '__main__':
    import sys
    ns = {}
    exec(open(__file__.replace('lzss_pack.py', 'wrs.py')).read().replace('\nmain()\n', '\n'), ns)
    for path in sys.argv[1:]:
        d = open(path, 'rb').read()
        c = pack(d)
        back, _ = ns['lzss'](c, 0, len(d))
        print(path, len(d), '->', len(c), 'ok' if back == d else 'MISMATCH')
