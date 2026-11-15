#!/usr/bin/env python3
"""check.py OUTDIR [H]: elements of every dialog whose pictures reach below
row H (default 480): the game draws them without clipping."""
import re, struct, sys, zipfile, os
d, H = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 480
gd = zipfile.ZipFile(os.path.join(d, 'data', 'gamedata.bnd'))
gx = zipfile.ZipFile(os.path.join(d, 'data', 'gfxdata.bnd'))
gxn = {n.lower(): n for n in gx.namelist()}
def size(g):
    n = gxn.get(g.lower().replace('\\', '/'))
    return struct.unpack('<HH', gx.open(n).read(18)[12:16]) if n else None
bad = 0
for n in gd.namelist():
    if not (n.startswith('dialogs/') and n.endswith('.xml')): continue
    b = gd.read(n); s = b.decode('utf-16') if b[:2] == b'\xff\xfe' else b.decode('latin-1')
    m = re.search(r'<dialog\b([^>]*)>', s)
    if not m: continue
    o = re.search(r'offset="(-?\d+)/(-?\d+)"', m.group(1)); dy = int(o.group(2)) if o else 0
    g = re.search(r'gfx="([^"]+)"', m.group(1))
    if g:
        sz = size(g.group(1))
        if sz and dy + sz[1] > H: print(f'{n}: dialog picture {g.group(1)} to {dy + sz[1]}'); bad += 1
    # elements: an element tag with offset, then its images until the next element
    cur = None
    for em in re.finditer(r'<(/?)(\w+)\s*([^>]*?)/?>', s[m.end():]):
        a = em.group(3)
        oo = re.search(r'offset="(-?\d+)/(-?\d+)"', a)
        if oo:
            sz = re.search(r'size="(\d+)/(\d+)"', a)
            nm = re.search(r'name="([^"]*)"', a)
            cur = (em.group(2), nm.group(1) if nm else '', dy + int(oo.group(2)))
            if sz and cur[2] + int(sz.group(2)) > H:
                print(f'{n}: {cur[0]} {cur[1]} box to {cur[2] + int(sz.group(2))}'); bad += 1
        gg = re.search(r'gfx="([^"]+)"', a)
        if gg and cur and em.group(2) != 'dialog':
            sz = size(gg.group(1))
            if sz and cur[2] + sz[1] > H:
                print(f'{n}: {cur[0]} {cur[1]} picture {gg.group(1)} to {cur[2] + sz[1]}'); bad += 1
print(bad, 'past', H)
