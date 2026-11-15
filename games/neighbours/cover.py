#!/usr/bin/env python3
"""cover.py GFXDATA.bnd OUT.png ENTRY X Y SIZE: bare_app's 240x240 cover from
a picture of the game's archive (ENTRY, a .tga), its square of SIZE pixels
at X, Y. prepare.sh takes one whole picture: the main menu's is two (its
top and bottom halves meet in a hard edge across the middle)."""
import os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tga
from PIL import Image
bnd, out, entry = sys.argv[1:4]
x, y, s = (int(v) for v in sys.argv[4:7])
z = zipfile.ZipFile(bnd)
names = {n.lower(): n for n in z.namelist()}
im = tga.image(tga.parse(z.read(names[entry.lower()]))).convert('RGB')
if x + s > im.width or y + s > im.height:
    sys.exit('cover.py: %d %d %d outside %s (%dx%d)' % (x, y, s, entry, im.width, im.height))
im.crop((x, y, x + s, y + s)).resize((240, 240), Image.LANCZOS).save(out)
