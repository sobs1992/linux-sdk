#!/usr/bin/env python3
"""
scenemem.py: The Book of Unwritten Tales lets go of the textures of the
scenes left behind once they take too much memory, so that a long chapter
fits into the GO Ultra's 2 GB (games/bout/README.md, "Memory").

The game (KAGE on Ogre 1.7.2) has one Ogre scene manager for all scenes.
Leaving a scene destroys its objects, but its 2D layers (backgrounds,
middle and foreground layers, patches, light patches: ~90% of its
textures) stay referenced by the scene's own object, which lives until the
chapter ends: Ogre keeps every texture of every scene visited (ogu2,
2026-11-23: 1.1 GB of GPU buffers after two hours of chapter 2, 67 MB of
memory left). Ogre loads an unloaded texture again by itself where it is
drawn (TextureUnitState::_getTexturePtr, D3D9RenderSystem::_setTexture:
touch()), so they can be unloaded while referenced.

Two calls into the scene change (0x4ade50, both GoToScene and
SwitchToScene), around its "call 0x4a5d30" that loads the new scene:

- before it (code at 0x5a9d40, in place of the call, which it then
  makes): if Ogre's count of texture memory (ResourceManager::
  getMemoryUsage of the TextureManager: the first level of each texture,
  about 1/1.45 of the GPU buffers) is above LIMIT_MB,
  ResourceManager::unloadAll(true) of the TextureManager: every texture
  that can be loaded again (from a file) is unloaded; the new scene loads
  its own as on a first visit, the rest come back where drawn. Render
  targets and textures made in memory (videos, shadows) are not reloadable
  and stay.
- after it (code at 0x5a9cd0, in place of "mov eax,[ebx+0x98]", which it
  then does): ResourceGroupManager::unloadUnreferencedResourcesInGroup(
  "CHAPTERDATA", true): what no object uses any more (meshes and
  materials of the scenes left).

A scene change that unloads takes 4-5 s, as a first visit (a return to a
scene still loaded 0-2 s); with LIMIT_MB 320 that happens once in a few new
scenes, the textures stay at ~550-750 MB of GPU buffers. Measured on ogu2
(limit 16 MB, so at every change): the hut of chapter 2 71 MB of GPU buffers
(236 without), the swamp 112, back in the hut 73 (its backgrounds loaded
again), the street 127; scenes, inventory, recipe, map, labels drawn right.

The code goes into the zero tail of .text (0x5a9cae-0x5a9e00, in the
file; .text's virtual size made 0x1a8e00), with "OgreMain.dll" at
0x5a9cb0 and the limit at 0x5a9cc0. bout.exe does not import
GetProcAddress: OgreMain.dll's base (GetModuleHandleA) plus the export's
RVA, read here from the game's OgreMain.dll.

Usage: scenemem.py GAME_DIR (or GAME_DIR set, as games-image.py runs it).
What is patched already is left as it is; anything else than expected
stops it before writing.
"""
import os
import struct
import sys

LIMIT_MB = 320

TEXT_VA, TEXT_OFF, TEXT_VSIZE, TEXT_RAW = 0x401000, 0x400, 0x1a8cae, 0x1a8e00
STR, LIMIT, POST, PRE, TAIL_END = 0x5a9cb0, 0x5a9cc0, 0x5a9cd0, 0x5a9d40, 0x5a9e00
HOOK_PRE, HOOK_POST, LOAD_SCENE = 0x4ae178, 0x4ae17d, 0x4a5d30
POST_OLD = bytes.fromhex("8b8398000000")	# mov eax, [ebx+0x98]

# bout.exe's imports used, by their address in its import table
IAT = {
	0x5aa058: ("KERNEL32.dll", "GetModuleHandleA"),
	0x5aad18: ("OgreMain.dll", "?getSingleton@ResourceGroupManager@Ogre@@SAAAV12@XZ"),
	0x5aacac: ("OgreMain.dll", "?getSingleton@TextureManager@Ogre@@SAAAV12@XZ"),
}
# OgreMain.dll's exports called through its base
UNREF = "?unloadUnreferencedResourcesInGroup@ResourceGroupManager@Ogre@@QAEXABV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@_N@Z"
USAGE = "?getMemoryUsage@ResourceManager@Ogre@@UBEIXZ"
UNLOAD_ALL = "?unloadAll@ResourceManager@Ogre@@UAEX_N@Z"

# after the new scene is loaded; {UNREF} the export's RVA
POST_CODE = [
	("60", "pushad"),
	("9c", "pushfd"),
	("68b09c5a00", "push 0x5a9cb0 ; \"OgreMain.dll\""),
	("ff1558a05a00", "call [0x5aa058] ; GetModuleHandleA"),
	("85c0", "test eax, eax"),
	("7454", "jz done"),
	("8db0{UNREF}", "lea esi, [eax + unloadUnreferencedResourcesInGroup]"),
	("ff1518ad5a00", "call [0x5aad18] ; ResourceGroupManager::getSingleton"),
	("89c7", "mov edi, eax"),
	("83ec1c", "sub esp, 28 ; std::string (VC10: buffer, size, capacity, allocator)"),
	("c7042443484150", "mov [esp], 'CHAP'"),
	("c744240454455244", "mov [esp+4], 'TERD'"),
	("c744240841544100", "mov [esp+8], 'ATA\\0'"),
	("c744240c00000000", "mov [esp+12], 0"),
	("c74424100b000000", "mov [esp+16], 11 ; size"),
	("c74424140f000000", "mov [esp+20], 15 ; capacity"),
	("c744241800000000", "mov [esp+24], 0"),
	("89e0", "mov eax, esp"),
	("6a01", "push 1 ; reloadable only"),
	("50", "push eax ; group name"),
	("89f9", "mov ecx, edi"),
	("ffd6", "call esi ; thiscall, pops 8"),
	("83c41c", "add esp, 28"),
	("9d", "done: popfd"),
	("61", "popad"),
	("8b8398000000", "mov eax, [ebx+0x98] ; the instruction replaced"),
	("c3", "ret"),
]
# before the new scene is loaded, then on to it
PRE_CODE = [
	("60", "pushad"),
	("9c", "pushfd"),
	("68b09c5a00", "push 0x5a9cb0 ; \"OgreMain.dll\""),
	("ff1558a05a00", "call [0x5aa058] ; GetModuleHandleA"),
	("85c0", "test eax, eax"),
	("7428", "jz done"),
	("89c5", "mov ebp, eax"),
	("ff15acac5a00", "call [0x5aacac] ; TextureManager::getSingleton"),
	("89c6", "mov esi, eax"),
	("89f1", "mov ecx, esi"),
	("8d85{USAGE}", "lea eax, [ebp + getMemoryUsage]"),
	("ffd0", "call eax"),
	("3b05c09c5a00", "cmp eax, [0x5a9cc0] ; the limit"),
	("760c", "jbe done"),
	("6a01", "push 1 ; reloadable only"),
	("89f1", "mov ecx, esi"),
	("8d85{UNLOAD_ALL}", "lea eax, [ebp + unloadAll]"),
	("ffd0", "call eax ; thiscall, pops 4"),
	("9d", "done: popfd"),
	("61", "popad"),
	("68305d4a00", "push 0x4a5d30 ; LoadScene, with the caller's stack and ecx"),
	("c3", "ret"),
]


def off(va):
	return va - TEXT_VA + TEXT_OFF


def pe_sections(d):
	pe = struct.unpack_from("<I", d, 0x3c)[0]
	opt = struct.unpack_from("<H", d, pe + 20)[0]
	n = struct.unpack_from("<H", d, pe + 6)[0]
	return pe, [(pe + 24 + opt + 40 * i,) + struct.unpack_from("<8sIIII", d, pe + 24 + opt + 40 * i)
		    for i in range(n)]


def rva_off(secs, rva):
	for _, name, vs, va, rs, ra in secs:
		if va <= rva < va + max(vs, rs):
			return rva - va + ra
	sys.exit("scenemem: RVA %#x outside the sections" % rva)


def cstr(d, o):
	return d[o:d.index(b"\0", o)].decode()


def imports(d):
	"""{IAT address: (dll, name)} of an i386 PE"""
	pe, secs = pe_sections(d)
	base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
	o = rva_off(secs, struct.unpack_from("<I", d, pe + 24 + 104)[0])
	out = {}
	while True:
		olt, _, _, name, iat = struct.unpack_from("<IIIII", d, o)
		o += 20
		if not name:
			return out
		dll = cstr(d, rva_off(secs, name))
		k = 0
		while True:
			e = struct.unpack_from("<I", d, rva_off(secs, olt or iat) + 4 * k)[0]
			if not e:
				break
			if not e & 0x80000000:
				out[base + iat + 4 * k] = (dll, cstr(d, rva_off(secs, e) + 2))
			k += 1


def exports(d):
	"""{name: RVA} of a PE"""
	pe, secs = pe_sections(d)
	e = rva_off(secs, struct.unpack_from("<I", d, pe + 24 + 96)[0])
	n = struct.unpack_from("<I", d, e + 24)[0]
	funcs, names, ords = (rva_off(secs, struct.unpack_from("<I", d, e + k)[0]) for k in (28, 32, 36))
	out = {}
	for i in range(n):
		name = cstr(d, rva_off(secs, struct.unpack_from("<I", d, names + 4 * i)[0]))
		out[name] = struct.unpack_from("<I", d, funcs + 4 * struct.unpack_from("<H", d, ords + 2 * i)[0])[0]
	return out


def code(lines, rvas):
	hexs = "".join(h for h, _ in lines)
	for k, v in rvas.items():
		hexs = hexs.replace("{%s}" % k, struct.pack("<I", v).hex())
	return bytes.fromhex(hexs)


def main():
	game = sys.argv[1] if len(sys.argv) > 1 else os.environ["GAME_DIR"]
	path = os.path.join(game, "bout.exe")
	data = bytearray(open(path, "rb").read())
	ogre = open(os.path.join(game, "OgreMain.dll"), "rb").read()

	imp = imports(data)
	for va, want in IAT.items():
		if imp.get(va) != want:
			sys.exit("scenemem: %s: %#x imports %s, not %s: another bout.exe" % (path, va, imp.get(va), want))
	exp = exports(ogre)
	rvas = {}
	for k, name in (("UNREF", UNREF), ("USAGE", USAGE), ("UNLOAD_ALL", UNLOAD_ALL)):
		if name not in exp:
			sys.exit("scenemem: OgreMain.dll exports no %s" % name)
		rvas[k] = exp[name]
	post, pre = code(POST_CODE, rvas), code(PRE_CODE, rvas)
	assert POST + len(post) <= PRE and PRE + len(pre) <= TAIL_END

	tail = bytearray(off(TAIL_END) - off(STR))
	tail[0:13] = b"OgreMain.dll\0"
	struct.pack_into("<I", tail, LIMIT - STR, LIMIT_MB << 20)
	tail[POST - STR:POST - STR + len(post)] = post
	tail[PRE - STR:PRE - STR + len(pre)] = pre
	pre_old = b"\xe8" + struct.pack("<i", LOAD_SCENE - (HOOK_PRE + 5))
	pre_new = b"\xe8" + struct.pack("<i", PRE - (HOOK_PRE + 5))
	post_new = b"\xe8" + struct.pack("<i", POST - (HOOK_POST + 5)) + b"\x90"
	pe, secs = pe_sections(data)
	sh = secs[0][0]
	if data[sh:sh + 5] != b".text":
		sys.exit("scenemem: %s: no .text first: another bout.exe" % path)

	edits = [
		(off(HOOK_PRE), pre_old, pre_new),
		(off(HOOK_POST), POST_OLD, post_new),
		(off(STR), bytes(len(tail)), bytes(tail)),
		(sh + 8, struct.pack("<I", TEXT_VSIZE), struct.pack("<I", TEXT_RAW)),
	]
	todo = []
	for o, old, new in edits:
		cur = bytes(data[o:o + len(old)])
		if cur == old:
			todo.append((o, new))
		elif cur != new:
			sys.exit("scenemem: %s: %d bytes at file offset %#x are %s...: another bout.exe" %
				 (path, len(old), o, cur[:16].hex()))
	if not todo:
		print("scenemem: %s: already patched" % path)
		return
	if len(todo) != len(edits):
		sys.exit("scenemem: %s: patched in part: another bout.exe" % path)
	for o, new in todo:
		data[o:o + len(new)] = new
	tmp = path + ".tmp"
	with open(tmp, "wb") as f:
		f.write(data)
	os.replace(tmp, path)
	print("scenemem: %s: textures let go above %d MB at a scene change (%d changes)" %
	      (path, LIMIT_MB, len(todo)))


if __name__ == "__main__":
	main()
