#!/usr/bin/env python3
"""dllpatch.py GAME BINDIR OUTDIR H: Neighbours from Hell GAME (1 or 2) with
its interface code for a screen whose top H rows are shown (the game itself
still 800x600): the screen size the interface asks for says 800 x H, and
the places that draw at the old bottom move up. The DLLs patched are
written to OUTDIR; a place patched already stays (a second run gives the
first one's files)."""
import os, struct, sys

def sections(b):
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    n = struct.unpack_from('<H', b, pe + 6)[0]
    osz = struct.unpack_from('<H', b, pe + 20)[0]
    base = struct.unpack_from('<I', b, pe + 24 + 28)[0]
    t = pe + 24 + osz
    return base, [struct.unpack_from('<8sIIII', b, t + i * 40)[1:5] for i in range(n)]

def file_offset(b, va):
    base, secs = sections(b)
    rva = va - base
    for vsize, vaddr, rsize, raddr in secs:
        if vaddr <= rva < vaddr + max(vsize, rsize):
            return raddr + rva - vaddr
    raise ValueError(hex(va))

game, bindir, out, H = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
D = 600 - H
# (dll, VA of the instruction, offset of its imm32, old value, new value)
SITES = {
    '1': [
        ('GFXEngine.dll', 0x1000d8a7, 1, 600, H),		# centring: (H - h) / 2
        ('GFXEngine.dll', 0x10011ce2, 4, 600, H),		# a screen-size rectangle
        ('GFXEngine.dll', 0x1001622a, 3, 600, H),		# the screen size getter
        ('GFXEngine.dll', 0x1001ca74, 3, 529, 529 - D),	# bottom panel: left icon
        ('GFXEngine.dll', 0x1002bf87, 4, 530, 530 - D),	# bottom panel: its bar
        ('GFXEngine.dll', 0x1002c0b2, 4, 473, 473 - D // 2),	# loading bar
    ],
    '2': [
        ('GUIEngine.dll', 0x10005232, 3, 600, H),		# the screen size getter
        ('GUIEngine.dll', 0x10005fa4, 3, 600, H),		# a screen-size rectangle
        ('GUIEngine.dll', 0x10022217, 1, 600, H),		# centring: (H - h) / 2
        ('GFXEngine.dll', 0x1000f3df, 4, 530, 530 - D),	# bottom panel: its bar
        ('GFXEngine.dll', 0x1000f564, 4, 473, 473 - D // 2),	# loading bar
    ],
}[game]
os.makedirs(out, exist_ok=True)
for dll in sorted({s[0] for s in SITES}):
    b = bytearray(open(os.path.join(bindir, dll), 'rb').read())
    for d, va, imm, old, new in SITES:
        if d != dll: continue
        o = file_offset(b, va) + imm
        v = struct.unpack_from('<I', b, o)[0]
        assert v in (old, new), (dll, hex(va), v)	# new: patched already, left as it is
        struct.pack_into('<I', b, o, new)
    open(os.path.join(out, dll), 'wb').write(b)
    print(dll)
