#!/usr/bin/env python3
"""cover.py GFXDATA.bnd OUT.png: bare_app's 240x240 cover from the game's
main menu picture (gui/main/mainmenu.tga, the 800x480 cut or the 800x600
original), its left square: the neighbour (and his mother)."""
import os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tga
from PIL import Image
z = zipfile.ZipFile(sys.argv[1])
names = {n.lower(): n for n in z.namelist()}
im = tga.image(tga.parse(z.read(names['gui/main/mainmenu.tga'])))
w, h = im.size
im.crop((0, 0, h, h)).resize((240, 240), Image.LANCZOS).save(sys.argv[2])
