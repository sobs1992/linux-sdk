#!/usr/bin/env python3
"""relayout.py SPEC.py GAMEDIR OUTDIR [PREVIEWDIR]: Neighbours from Hell's
data for a 480-high screen. SPEC defines
  CUTS   = {picture: [(y0, y1), ...]}   rows y0..y1-1 of the picture removed
  SCALES = {picture: rows}              the picture resampled to that height
  SHIFTS = {dialog xml: dy}             the dialog's own offset moved by dy
  EDITS  = [(xml, old, new)]            plain text replacements (done first)
Elements placed in a dialog whose background picture is cut move up by the
rows removed above them (inside a cut: to its start); in a scaled one their
y is scaled. Only elements placed in the dialog itself move: offsets inside
an element with an offset of its own are relative to it. Writes
OUTDIR/data/gamedata.bnd and gfxdata.bnd, keeping order and compression."""
import io, os, re, runpy, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tga

spec = runpy.run_path(sys.argv[1])
CUTS, SCALES = spec.get('CUTS', {}), spec.get('SCALES', {})
SHIFTS, EDITS = spec.get('SHIFTS', {}), spec.get('EDITS', [])
gdir, out = sys.argv[2], os.path.join(sys.argv[3], 'data')
prev = sys.argv[4] if len(sys.argv) > 4 else None
gd = zipfile.ZipFile(os.path.join(gdir, 'data', 'gamedata.bnd'))
gx = zipfile.ZipFile(os.path.join(gdir, 'data', 'gfxdata.bnd'))
gxn = {n.lower(): n for n in gx.namelist()}

def pic_height(p):
    import struct
    return struct.unpack('<H', gx.open(gxn[p]).read(18)[14:16])[0]

def removed_above(cuts, y):
    r = 0
    for y0, y1 in cuts:
        if y >= y1: r += y1 - y0
        elif y > y0: r += y - y0
    return r

def decode(b):
    if b[:2] == b'\xff\xfe': return b.decode('utf-16'), 'utf-16'
    try: return b.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError: return b.decode('latin-1'), 'latin-1'

def encode(s, enc):
    return s.encode('utf-16') if enc == 'utf-16' else s.encode(enc)

TAG = re.compile(r'<(/?)([A-Za-z_][\w]*)([^>]*?)(/?)>')
OFF = re.compile(r'offset="(-?\d+)/(-?\d+)"')

def move_children(body, ymap):
    """offsets of the elements placed in the dialog itself through ymap"""
    out, pos, stack = [], 0, []
    for m in TAG.finditer(body):
        closing, attrs, selfclose = m.group(1), m.group(3), m.group(4)
        if closing:
            if stack: stack.pop()
            continue
        o = OFF.search(attrs)
        if o and not any(stack):
            x, y = int(o.group(1)), int(o.group(2))
            start = m.start(3) + o.start()
            out.append(body[pos:start]); out.append(f'offset="{x}/{ymap(y)}"')
            pos = m.start(3) + o.end()
        if not selfclose and not attrs.rstrip().endswith('/'):
            stack.append(bool(o))
    out.append(body[pos:])
    return ''.join(out)

used = set()
def fix_xml(name, data):
    s, enc = decode(data)
    for x, old, new in EDITS:		# in order: later ones see earlier ones' text
        if x.lower() == name.lower():
            assert s.count(old) == 1, (name, old); s = s.replace(old, new); used.add((x, old))
    m = re.search(r'<(dialog|resizedialog)\b([^>]*)>', s)
    if m:
        g = re.search(r'gfx="([^"]+)"', m.group(2))
        pic = g.group(1).lower().replace('\\', '/') if g else None
        head, body = s[:m.end()], s[m.end():]
        if pic in CUTS:
            cuts = CUTS[pic]
            body = move_children(body, lambda y: y - removed_above(cuts, y))
        elif pic in SCALES:
            f = SCALES[pic] / pic_height(gxn[pic])
            body = move_children(body, lambda y: round(y * f))
        dy = SHIFTS.get(name.lower())
        if dy:
            head = head[:m.start()] + OFF.sub(lambda e: f'offset="{e.group(1)}/{int(e.group(2)) + dy}"', head[m.start():], count=1)
            used.add(('shift', name.lower()))
        s = head + body
    return encode(s, enc)

os.makedirs(out, exist_ok=True)
with zipfile.ZipFile(os.path.join(out, 'gamedata.bnd'), 'w') as zo:
    for i in gd.infolist():
        d = gd.read(i)
        if i.filename.lower().endswith('.xml'):
            d = fix_xml(i.filename, d)
        zo.writestr(i, d, compress_type=i.compress_type)
for x, old, new in EDITS:
    assert (x, old) in used, ('edit not applied', x, old)
for k in SHIFTS:
    assert ('shift', k) in used, ('shift not applied', k)
with zipfile.ZipFile(os.path.join(out, 'gfxdata.bnd'), 'w') as zo:
    for i in gx.infolist():
        d = gx.read(i)
        n = i.filename.lower()
        if n in CUTS or n in SCALES:
            t = tga.parse(d)
            if n in CUTS:
                t['rows'] = [r for k, r in enumerate(t['rows']) if not any(y0 <= k < y1 for y0, y1 in CUTS[n])]
            else:
                tga.scale_rows(t, SCALES[n])
            d = tga.build(t)
            if prev:
                tga.image(t).save(os.path.join(prev, n.replace('/', '_')[:-4] + '.png'))
        zo.writestr(i, d, compress_type=i.compress_type)
for p in list(CUTS) + list(SCALES):
    assert p in gxn, ('no picture', p)
print('ok')
