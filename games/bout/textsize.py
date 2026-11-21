#!/usr/bin/env python3
"""
textsize.py: The Book of Unwritten Tales' text 1.3 times bigger and its
menu book darker, for the GO Ultra's 854x480 screen (games/bout/README.md,
"Text size").

The game sizes its text as a share of the screen's height (Ogre overlays in
relative metrics), so no display mode makes it bigger: three numbers of
bout.exe (the 1C edition 1.0.2.0 as the repack has it) do:

- 0x5bd9f4, float 0.0275: char_height of the FormalOutline text areas
  (LogIngame_msg%02i and the centred one), its only users;
- 0x5bddc8, float 0.03375: char_height of the Dauphin text (_pups), its
  only user;
- 0x4dbeb5, "fld dword [0x5bd994]" (0.0375, shared with unrelated code):
  the default char_height of the game's text class, made to load
  0x5bdd20 (0.048667, an existing constant) instead.

And one more for the 854x480 mode it plays in: the game's settings list
only the display modes at least 1024 wide ("cmp eax, 0x400" after atoi of
the width, in two functions that fill "_resolution": 0x4e55cb, 0x4f250b),
so its resolution line showed another mode than the one played, and OK
there would have set it. The bound is made 854 in both.

The menu book (kagedata/interface/original_Bookpages.kad, the only .kad
with <mainmenu>) draws its items dark grey at 60% opacity on the orange
page, hard to read on the small screen: 95% now, the greyed-out ones 45%
(were 30%), the one under the cursor dark red (was the 100% grey the
others now nearly are, so it would no longer stand out). Its italic is
BOOK_SCALE times bigger too: every entry's fontsize; where lines of one
text stand closer than their size (the two-line labels of the settings,
the hint on the settings' left page) their pitch grows the same, from the
first line; and where whole items stood close, BOOK_TOPS spreads them over
the page's free room (the menus' items 0.09 apart, were 0.08; the
settings' rows from "quality" down 0.02-0.035 lower, above OK as before). The lists of saved games and chapters are the game's code,
sized by the text class's default above.

Usage: textsize.py GAME_DIR (or GAME_DIR set, as games-image.py runs it).
What is patched already is left as it is; anything else than expected
stops it before writing.
"""
import os
import re
import struct
import sys

SCALE = 1.3
TEXT_VA, TEXT_OFF = 0x401000, 0x400
RDATA_VA, RDATA_OFF = 0x5aa000, 0x1a9200

FLOATS = [(0x5bd9f4, 0.0275), (0x5bddc8, 0.03375)]
FLD_VA = 0x4dbeb5
FLD_OLD = bytes.fromhex("d905" "94d95b00")	# fld dword [0x5bd994]
FLD_NEW = bytes.fromhex("d905" "20dd5b00")	# fld dword [0x5bdd20]
CMP_VAS = (0x4e55cb, 0x4f250b)
CMP_OLD = bytes.fromhex("3d" "00040000")	# cmp eax, 1024
CMP_NEW = bytes.fromhex("3d" "56030000")	# cmp eax, 854

BOOK = os.path.join("kagedata", "interface", "original_Bookpages.kad")
BOOK_SCALE = 1.2
BOOK_MARK = b"<!-- textsize.py: menu book italic x"
# entries keeping their size: the chapter's title over a saved game
# ("Глава 5 - Возвращение в Дикие земли...", the longest, fills the left
# page's width at its own size already)
BOOK_KEEP = {b"sg_chapter_title"}
# (page, entry text): its new top (was: see the comment)
BOOK_TOPS = {
	("LoadGame_left", b"sg_title"): 0.160,		# 0.150, under the chapter's title
	("SaveGame_left", b"sg_title"): 0.160,		# 0.150
	("MainPage", b"sg_load_game"): 0.490,		# 0.480
	("MainPage", b"$_preferences$"): 0.580,		# 0.560
	("MainPageIngame", b"sg_load_game"): 0.490,	# 0.480
	("MainPageIngame", b"$_preferences$"): 0.580,	# 0.560
	("MainPageIngame", b"$_new_game$"): 0.670,	# 0.646
	("Preferences", b"$_pref_qual1$"): 0.318,	# 0.300
	("Preferences", b"current:quality"): 0.323,	# 0.305
	("Preferences", b"$_pref_aa1$"): 0.425,		# 0.390
	("Preferences", b"current:_smooth"): 0.430,	# 0.395
	("Preferences", b"$_pref_music$"): 0.545,	# 0.525
	("Preferences", b"current:music"): 0.530,	# 0.510
	("Preferences", b"$_pref_sound$"): 0.610,	# 0.585
	("Preferences", b"current:sound"): 0.595,	# 0.570
	("Preferences", b"$_pref_speach$"): 0.675,	# 0.645
	("Preferences", b"current:speach"): 0.660,	# 0.630
	("Preferences", b"$_pref_subtitle$"): 0.765,	# 0.740
	("Preferences", b"current:subtitle"): 0.755,	# 0.730
}
# lines of one text, by their first line's text: the others' tops move
BOOK_GROUPS = [
	[b"$_pref_hint1$", b"$_pref_hint2$", b"$_pref_hint3$", b"$_pref_hint4$"],
	[b"$_pref_res1$", b"$_pref_res2$"],
	[b"$_pref_qual1$", b"$_pref_qual2$"],
	[b"$_pref_aa1$", b"$_pref_aa2$"],
]
BOOK_COLORS = [
	(b"<fontcolor>0.05 0.05 0.05 0.6</fontcolor>", b"<fontcolor>0.05 0.05 0.05 0.95</fontcolor>"),
	(b"<inactivefontcolor>0.05 0.05 0.05 0.3</inactivefontcolor>",
	 b"<inactivefontcolor>0.05 0.05 0.05 0.45</inactivefontcolor>"),
	(b"<highlightfontcolor>0.05 0.05 0.05 1</highlightfontcolor>",
	 b"<highlightfontcolor>0.45 0.06 0.02 1</highlightfontcolor>"),
	(b"<selectedfontcolor>0.05 0.05 0.05 0.9</selectedfontcolor>",
	 b"<selectedfontcolor>0.05 0.05 0.05 1</selectedfontcolor>"),
]


def off(va):
	return va - (RDATA_VA - RDATA_OFF) if va >= RDATA_VA else va - (TEXT_VA - TEXT_OFF)


def write(path, data):
	tmp = path + ".tmp"
	with open(tmp, "wb") as f:
		f.write(data)
	os.replace(tmp, path)


def book_sizes(data):
	"""fontsize x BOOK_SCALE, the groups' pitch with it; data with the mark"""
	lines = data.split(b"\n")
	page, done = None, set()
	for i, l in enumerate(lines):
		m = re.search(rb'<page id="([^"]+)"', l)
		if m:
			page = m.group(1).decode()
		m = re.search(rb'>([^<]*)</entry>', l)
		key = (page, m.group(1).strip()) if m else None
		if key in BOOK_TOPS:
			lines[i] = re.sub(rb'top="[0-9.]+"', b'top="%.3f"' % BOOK_TOPS[key], l, count=1)
			done.add(key)
	if done != set(BOOK_TOPS):
		sys.exit("textsize: not in the menu book: %s" % sorted(set(BOOK_TOPS) - done))
	tops = {}
	for i, l in enumerate(lines):
		m = re.search(rb'top="([0-9.]+)".*>([^<]*)</entry>', l)
		if m:
			tops[m.group(2).strip()] = (i, float(m.group(1)))
	orig = {}
	for i, l in enumerate(data.split(b"\n")):
		m = re.search(rb'top="([0-9.]+)".*>([^<]*)</entry>', l)
		if m:
			orig[m.group(2).strip()] = float(m.group(1))
	for group in BOOK_GROUPS:
		if any(t not in tops for t in group):
			sys.exit("textsize: no %s in the menu book" % group)
		first = tops[group[0]][1]
		for t in group[1:]:
			i = tops[t][0]
			new = first + (orig[t] - orig[group[0]]) * BOOK_SCALE
			lines[i] = re.sub(rb'top="[0-9.]+"', b'top="%.3f"' % new, lines[i], count=1)
	n = 0
	for i, l in enumerate(lines):
		m = re.search(rb'fontsize="([0-9.]+)"', l)
		t = re.search(rb'>([^<]*)</entry>', l)
		if m and not (t and t.group(1).strip() in BOOK_KEEP):
			lines[i] = l[:m.start(1)] + b"%.3f" % (float(m.group(1)) * BOOK_SCALE) + l[m.end(1):]
			n += 1
	out = b"\n".join(lines)
	mark = BOOK_MARK + b"%g -->" % BOOK_SCALE
	out = out.replace(b"<mainmenu>", b"<mainmenu>" + mark, 1)
	return out, n


def book(game):
	path = os.path.join(game, BOOK)
	data = open(path, "rb").read()
	todo = []
	for old, new in BOOK_COLORS:
		if data.count(old) == 1:
			todo.append((old, new))
		elif data.count(new) != 1:
			sys.exit("textsize: %s: no %s: another menu book" % (path, old.decode()))
	sizes = BOOK_MARK not in data
	if not todo and not sizes:
		print("textsize: %s: already patched" % path)
		return
	for old, new in todo:
		data = data.replace(old, new)
	n = 0
	if sizes:
		data, n = book_sizes(data)
	write(path, data)
	print("textsize: %s: menu colours (%d changes), %d sizes x%g" % (path, len(todo), n, BOOK_SCALE))


def exe(path):
	data = bytearray(open(path, "rb").read())
	edits = []
	for va, old in FLOATS:
		cur = struct.unpack("<f", data[off(va):off(va) + 4])[0]
		if abs(cur - old) < 1e-6:
			edits.append((off(va), struct.pack("<f", old * SCALE)))
		elif abs(cur - old * SCALE) >= 1e-6:
			sys.exit("textsize: %s: 0x%x is %g, not %g: another bout.exe" %
				 (path, va, cur, old))
	for va, old_b, new_b in [(FLD_VA, FLD_OLD, FLD_NEW)] + [(v, CMP_OLD, CMP_NEW) for v in CMP_VAS]:
		cur = data[off(va):off(va) + len(old_b)]
		if cur == old_b:
			edits.append((off(va), new_b))
		elif cur != new_b:
			sys.exit("textsize: %s: 0x%x is %s: another bout.exe" % (path, va, cur.hex()))
	if not edits:
		print("textsize: %s: already patched" % path)
		return
	for o, b in edits:
		data[o:o + len(b)] = b
	write(path, data)
	print("textsize: %s: text x%.1f, modes from 854 wide (%d changes)" % (path, SCALE, len(edits)))


def main():
	game = sys.argv[1] if len(sys.argv) > 1 else os.environ["GAME_DIR"]
	exe(os.path.join(game, "bout.exe"))
	book(game)


if __name__ == "__main__":
	main()
