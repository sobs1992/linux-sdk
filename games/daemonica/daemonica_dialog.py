#!/usr/bin/env python3
"""daemonica_dialog.py IN.wrs OUT.wrs: Daemonica's daemonica.wrs with the
800x600 dialog laid out for the bigger fonts of WINE_FONT_SCALE=1.25 (the
GO Ultra): NPC text 25 px further left and up, at most 53 width units a
line (was 58) and 12 lines a page (was 14), so it stays clear of the
portrait and of the frame's bottom; player replies keep their font (as
big as the NPC's) on a 20 px pitch (was 17), 6 px higher, their click
areas 460x20 to match; a few of the longest replies reach past the
frame's right edge. --debug: F9 opens a talk starting with NPC line 1 (the gate guard's words) (to
look at the dialog; not for playing). Every other entry is copied byte for byte; the
changed ones are packed again (lzss_pack.py). The engine accepts the file
only if the sum of its first 16 KB and its size give the number the
original gives (wrscheck.py): the last changed entry gets as many unused
bytes after its data as that needs. The output is checked by unpacking
it again."""
import struct
import sys

sys.path.insert(0, __import__('os').path.dirname(__file__))
DEBUG = '--debug' in sys.argv
if DEBUG:
    sys.argv.remove('--debug')
src = open(sys.argv[1], 'rb').read()

ns = {}
code = open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'wrs.py')).read()
exec(code.replace('\nmain()\n', '\n'), ns)
entries, lzss = ns['entries'], ns['lzss']


def block(text, start_marker, end_marker):
    a = text.index(start_marker)
    b = text.index(end_marker, a)
    return a, b


def sub(text, old, new, count=1):
    n = text.count(old)
    if n != count:
        raise SystemExit('%r found %d times, expected %d' % (old, n, count))
    return text.replace(old, new)


def edit_text_settings(t):
    t = sub(t, b'define MaxCharPerLine800 \t= 58;', b'define MaxCharPerLine800 \t= 53;')
    t = sub(t, b'define NPCLinesPerPage \t\t= 14;', b'define NPCLinesPerPage \t\t= 12;')
    return t


def edit_set_panels(t):
    a, b = block(t, b'if (video_mode == 7) {', b'if (video_mode == 8) {')
    part = t[a:b]
    part = sub(part, b'txt_NPCDialogLines.pos_x = 115;', b'txt_NPCDialogLines.pos_x = 90;')
    part = sub(part, b'txt_NPCDialogLines.pos_y = 95;', b'txt_NPCDialogLines.pos_y = 85;')
    part = sub(part, b'txt_DialogReplyString1.pos_y = pnl_Dialog.pos_y + 388;',
               b'txt_DialogReplyString1.pos_y = pnl_Dialog.pos_y + 382;')
    for i, (old, new) in enumerate(((17, 20), (34, 40), (51, 60), (68, 80))):
        part = sub(part, b'txt_DialogReplyString%d.pos_y = txt_DialogReplyString1.pos_y + %d;' % (i + 2, old),
                   b'txt_DialogReplyString%d.pos_y = txt_DialogReplyString1.pos_y + %d;' % (i + 2, new))
    t = t[:a] + part + t[b:]
    return sub(t, b'pnl_DialogPlrReply800.pos_y = pnl_Dialog.pos_y + 390;',
               b'pnl_DialogPlrReply800.pos_y = pnl_Dialog.pos_y + 384;')


def edit_dialog(t):
    t = sub(t, b'bmap bmp_DialogInvisButt800 = "dialog_replyinvisbutt.tga",0,0,350,16;',
            b'bmap bmp_DialogInvisButt800 = "dialog_replyinvisbutt.tga",0,0,460,20;')
    a, b = block(t, b'panel pnl_DialogPlrReply800', b'}')
    part = t[a:b]
    for old, new in ((16, 20), (32, 40), (48, 60), (64, 80)):
        part = sub(part, b'\tbutton = 0,%d,bmp_DialogInvisButt800' % old, b'\tbutton = 0,%d,bmp_DialogInvisButt800' % new)
    t = t[:a] + part + t[b:]
    if DEBUG:
        t += (b'\r\n// debug: F9 opens the talk that starts with NPC line 1\r\nfunction dbgTalkGateGuard() { TalkTo(null, EntType_Tanner); }\r\n'
              b'on_f9 dbgTalkGateGuard;\r\n')
    return t


EDITS = {'Text_settings.wdl': edit_text_settings,
         'SYS_set_panels.wdl': edit_set_panels,
         'SYS_dialog.wdl': edit_dialog}


def literals(data):
    out = bytearray()
    for i in range(0, len(data), 8):
        chunk = data[i:i + 8]
        out.append((1 << len(chunk)) - 1)
        out += chunk
    return bytes(out)


from wrscheck import wrs_check
from lzss_pack import pack


def build(pad):
    out = bytearray(b'WRS2')
    done = set()
    last = max(i for i, e in enumerate(entries(src)) if e[0] in EDITS)
    for i, (name, off, csize, size, body) in enumerate(entries(src)):
        raw = src[off:off + 40 + csize]
        if name in EDITS:
            new = EDITS[name](body)
            comp = pack(new) + (b'\0' * pad if i == last else b'')
            raw = src[off:off + 32] + struct.pack('>II', len(comp), len(new)) + comp
            done.add(name)
        out += raw
    if done != set(EDITS):
        raise SystemExit('not found: %s' % (set(EDITS) - done))
    return out


target = wrs_check(src)
base = build(0)
packed = {n: len(pack(EDITS[n](b))) for n, o, c, sz, b in entries(src) if n in EDITS}
print('packed', packed)
for pad in range(0, 1 << 21):
    if wrs_check(base, len(base) + pad) == target:
        break
else:
    raise SystemExit('no size gives the check number %d' % target)
out = build(pad)
print('check %d with %d bytes of padding' % (target, pad))

# check: same entries, edited ones as intended, the rest identical
old = {n: b for n, o, c, s, b in entries(src)}
new = {n: b for n, o, c, s, b in entries(bytes(out))}
assert list(old) == list(new), 'entry list changed'
for n in old:
    want = EDITS[n](old[n]) if n in EDITS else old[n]
    assert new[n] == want, n
open(sys.argv[2], 'wb').write(out)
assert wrs_check(bytes(out)) == target
print('%s: %d entries, %d -> %d bytes, checked' % (sys.argv[2], len(new), len(src), len(out)))
