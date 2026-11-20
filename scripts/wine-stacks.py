#!/usr/bin/env python3
"""
wine-stacks: the i386 call stacks of every thread of a 32-bit Windows game
running under the SDK's Wine (WoW64, Box64) on the GO Ultra, over ssh, to see
where a game hangs or spins.

  wine-stacks.py                  the biggest WoW64 process on the board
  wine-stacks.py 1234             that process
  wine-stacks.py maindata         the process whose name has this in it
  wine-stacks.py -o DIR ...       the raw data there (default:
                                  output/wine-stacks/<time>)

The board is 192.168.7.2 (OGU_HOST to change it), as for ogu-ctl.py. It
needs gdbserver on the board and the firmware's build output (OUTPUT_DIR):
Buildroot's gdb and llvm-mingw, and Wine's build directory with the i386
DLLs, unstripped, for the function names.

How: gdbserver attaches twice for a moment (the game stops for a second or
two each time; an attach also interrupts the system calls the threads wait
in, which they restart). The TEBs are found in 0x7f000000..0x80000000 (64 KB
blocks whose NT_TIB.Self, at +0x30, is themselves): register x18 holds the
TEB only in Wine's own code, not in a thread that is in Mesa. A WoW64 thread
keeps its i386 context at the last system call in TEB64.TlsSlots[1] + 4 (an
I386_CONTEXT): EIP, ESP and EBP. Each stack is walked by its EBP chain (Wine
is built with frame pointers; the game's code may not be) and also scanned
for words that point into a module (return addresses, and noise). A thread
that has no i386 context yet is still in its 64-bit start. The loader locks
(the 64-bit ntdll's loader_section, the i386 one's) are shown with their
owners' thread ids.

What it is not: a hang detector. A main thread spinning in its message loop
and an idle wined3d_cs thread are normal while a game plays its intro videos;
look at the screen first (ogu-ctl.py shot).
"""
import argparse
import os
import re
import subprocess
import sys
import time

import devlib

HOST = "root@" + os.environ.get("OGU_HOST", "192.168.7.2")
SSH = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
       "-o", "LogLevel=ERROR", HOST]
FW = "ogu"
GDB = devlib.output(FW, "buildroot", "host", "bin", "aarch64-buildroot-linux-gnu-gdb")
MINGW = devlib.output(FW, "buildroot", "host", "llvm-mingw", "bin")
PORT = 2345
TEB_LO, TEB_HI = 0x7f000000, 0x80000000
# I386_CONTEXT (winnt.h), in 32-bit words: Ebp, Eip, Esp
CTX_WORDS, CTX_EBP, CTX_EIP, CTX_ESP = 52, 45, 46, 49


def ssh(cmd):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, check=True).stdout


def wine_build():
    builds = sorted(d for d in os.listdir(devlib.output(FW, "buildroot", "build"))
                    if d.startswith("wine-wow64-"))
    if not builds:
        sys.exit("wine-stacks: no wine-wow64 build in " + devlib.output(FW, "buildroot", "build"))
    return devlib.output(FW, "buildroot", "build", builds[-1])


def find_process(what):
    """The PID: given, by name, or the biggest process with the i386 ntdll"""
    if what and what.isdigit():
        return int(what)
    out = ssh("for p in /proc/[0-9]*; do grep -q i386-windows/ntdll.dll $p/maps 2>/dev/null && "
              "echo ${p#/proc/} $(awk '/VmRSS/{print $2}' $p/status) "
              "$(tr '\\0' ' ' < $p/cmdline | cut -c1-80); done; true")
    procs = []
    for line in out.splitlines():
        f = line.split(" ", 2)
        if len(f) == 3 and f[1].isdigit() and (not what or what in f[2]):
            procs.append((int(f[1]), int(f[0]), f[2]))
    if not procs:
        sys.exit("wine-stacks: no WoW64 process%s on %s" % (" like " + what if what else "", HOST))
    procs.sort(reverse=True)
    print("process %d: %s" % (procs[0][1], procs[0][2]))
    return procs[0][1]


def gdb(pid, cmds):
    """gdb's output of the commands, gdbserver attached for them; an error in
    one (memory that is not there) does not stop the others"""
    server = subprocess.Popen(SSH + ["gdbserver --attach :%d %d" % (PORT, pid)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in server.stdout:
        if "Listening on port" in line:
            break
        if "Cannot attach" in line or "error" in line.lower():
            sys.exit("wine-stacks: gdbserver: " + line.strip())
    args = [GDB, "-q", "-batch", "-ex", "set pagination off",
            "-ex", "target remote %s:%d" % (HOST.split("@")[1], PORT)]
    for c in cmds:
        args += ["-ex", c]
    args += ["-ex", "detach"]
    out = subprocess.run(args, capture_output=True, text=True, timeout=300).stdout
    server.wait(timeout=30)
    return out


def symbol_offset(dll, name):
    """name's offset from the image base in a PE DLL of the build"""
    nm = subprocess.run([os.path.join(MINGW, "llvm-nm"), dll], capture_output=True, text=True).stdout
    dump = subprocess.run([os.path.join(MINGW, "llvm-objdump"), "-p", dll], capture_output=True, text=True).stdout
    base = int(re.search(r"ImageBase\s+([0-9a-fA-F]+)", dump).group(1), 16)
    for line in nm.splitlines():
        f = line.split()
        if len(f) == 3 and f[2] == name:
            return int(f[0], 16) - base
    return None


class Modules:
    """The PE files mapped below 4 GB, and names for addresses in them"""

    def __init__(self, maps, build):
        self.build, self.mods, self.bases = build, {}, {}
        for line in maps.splitlines():
            f = line.split()
            if len(f) < 6 or not f[5].startswith("/"):
                continue
            s, e = (int(x, 16) for x in f[0].split("-"))
            if s >= 1 << 32:
                continue
            lo, hi = self.mods.get(f[5], (s, e))
            self.mods[f[5]] = (min(lo, s), max(hi, e))
        self.cache = {}

    def of(self, a):
        for p, (s, e) in self.mods.items():
            if s <= a < e:
                return p, s
        return None, None

    def local(self, path):
        """The build's unstripped copy of an i386 Wine module"""
        name = os.path.basename(path)
        if "/i386-windows/" not in path:
            return None
        stem = name.rsplit(".", 1)[0]
        for d in ("dlls/" + stem, "dlls/" + name, "programs/" + stem, "programs/" + name):
            cand = os.path.join(self.build, d, "i386-windows", name)
            if os.path.exists(cand):
                return cand
        return None

    def name(self, a):
        if a in self.cache:
            return self.cache[a]
        path, start = self.of(a)
        if not path:
            text = "%08x" % a
        else:
            text = "%08x %s+%x" % (a, os.path.basename(path), a - start)
            dll = self.local(path)
            if dll:
                if dll not in self.bases:
                    dump = subprocess.run([os.path.join(MINGW, "llvm-objdump"), "-p", dll],
                                          capture_output=True, text=True).stdout
                    self.bases[dll] = int(re.search(r"ImageBase\s+([0-9a-fA-F]+)", dump).group(1), 16)
                out = subprocess.run([os.path.join(MINGW, "llvm-addr2line"), "-f", "-i", "-e", dll,
                                      hex(self.bases[dll] + a - start)],
                                     capture_output=True, text=True).stdout.split("\n")
                funcs = [out[i] for i in range(0, len(out) - 1, 2) if out[i] != "??"]
                if funcs:
                    text += " " + " <- ".join(funcs)
        self.cache[a] = text
        return text


def words(text):
    """'0x...: w w w w' lines of gdb's x/wx as (address of the first, words)"""
    first, ws = None, []
    for line in text.splitlines():
        m = re.match(r"0x([0-9a-f]+):\s+(.*)", line)
        if m:
            if first is None:
                first = int(m.group(1), 16)
            ws += [int(w, 16) for w in m.group(2).split()]
    return first, ws


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("process", nargs="?", help="PID or a part of its command line")
    ap.add_argument("-o", "--out", help="directory for the raw data")
    opt = ap.parse_args()
    for tool in (GDB, os.path.join(MINGW, "llvm-addr2line")):
        if not os.path.exists(tool):
            sys.exit("wine-stacks: no %s (build the ogu firmware first)" % tool)
    build = wine_build()
    out = opt.out or os.path.join(devlib.OUTPUT_DIR, "wine-stacks", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)

    pid = find_process(opt.process)
    maps = ssh("cat /proc/%d/maps" % pid)
    tasks = ssh("cd /proc/%d/task && for t in *; do echo $t $(tr ' ' _ < $t/comm) "
                "$(cut -d' ' -f14,15 $t/stat) $(cat $t/wchan); done" % pid)
    open(os.path.join(out, "maps.txt"), "w").write(maps)
    open(os.path.join(out, "tasks.txt"), "w").write(tasks)
    mods = Modules(maps, build)

    # pass 1: the TEBs, each thread's x18 (the TEB, where it still holds it), the loader locks
    cands = []
    for line in maps.splitlines():
        f = line.split()
        s, e = (int(x, 16) for x in f[0].split("-"))
        if "rw" not in f[1] or e <= TEB_LO or s >= TEB_HI:
            continue
        a = (max(s, TEB_LO) + 0xffff) & ~0xffff
        while a + 0x2000 <= min(e, TEB_HI):
            cands.append(a)
            a += 0x10000
    cmds = ['printf "C %%lx %%lx %%lx %%lx\\n", %d, *(unsigned long *)(%d + 0x30), '
            '*(unsigned long *)(%d + 0x1488), *(unsigned long *)(%d + 0x48)' % (a, a, a, a) for a in cands]
    cmds += ["info threads", 'thread apply all -q -s printf "X %d %lx\\n", $_thread, $x18']
    locks = []
    for arch, rel, name, ptr, owner_off in (("aarch64-windows", "dlls/ntdll/aarch64-windows/ntdll.dll", "loader_section", 8, 16),
                                            ("i386-windows", "dlls/ntdll/i386-windows/ntdll.dll", "_loader_section", 4, 12)):
        off = symbol_offset(os.path.join(build, rel), name)
        base = None    # the file's first mapping: its image base
        for line in maps.splitlines():
            if line.rstrip().endswith(arch + "/ntdll.dll"):
                base = int(line.split("-")[0], 16)
                break
        if off is not None and base is not None:
            a = base + off
            locks.append(arch)
            cmds.append('printf "L %s %%d %%d %%lx\\n", *(int *)(%d + %d), *(int *)(%d + %d), *(%s *)(%d + %d)'
                        % (arch, a, ptr, a, ptr + 4, "unsigned long" if ptr == 8 else "unsigned int", a, owner_off))
    p1 = gdb(pid, cmds)
    open(os.path.join(out, "pass1.txt"), "w").write(p1)

    tebs = []          # (teb, cpu area, windows thread id)
    for line in p1.splitlines():
        f = line.split()
        if len(f) == 5 and f[0] == "C" and f[1] == f[2]:
            tebs.append((int(f[1], 16), int(f[3], 16), int(f[4], 16)))
    gdb_lwp = {}       # gdb thread number -> (unix tid, name)
    for line in p1.splitlines():
        m = re.match(r"[\s*]*(\d+)\s+Thread \d+\.(\d+) \"([^\"]*)\"", line)
        if m:
            gdb_lwp[m.group(1)] = (m.group(2), m.group(3))
    unix_of = {}       # teb -> "tid name"
    for line in p1.splitlines():
        f = line.split()
        if len(f) == 3 and f[0] == "X" and f[1] in gdb_lwp:
            unix_of[int(f[2], 16)] = "%s %s" % gdb_lwp[f[1]]
    ticks = {f[0]: f[2:4] for f in (l.split() for l in tasks.splitlines()) if len(f) >= 4}

    # pass 2: each WoW64 thread's i386 context and stack
    cmds = []
    for teb, cpu, tid in tebs:
        if not cpu:
            continue
        ctx = cpu + 4
        cmds += ["echo CTX %x\\n" % teb, "x/%dwx %d" % (CTX_WORDS, ctx),
                 "echo STK %x\\n" % teb, "x/1024wx *(unsigned int *)(%d + %d)" % (ctx, 4 * CTX_ESP),
                 "echo STK2 %x\\n" % teb, "x/256wx *(unsigned int *)(%d + %d)" % (ctx, 4 * CTX_ESP)]
    p2 = gdb(pid, cmds)
    open(os.path.join(out, "pass2.txt"), "w").write(p2)
    parts = {}
    for chunk in re.split(r"^(?=(?:CTX|STK2?) [0-9a-f]+$)", p2, flags=re.M):
        m = re.match(r"(CTX|STK2?) ([0-9a-f]+)\n", chunk)
        if m:
            parts[(m.group(1), int(m.group(2), 16))] = words(chunk)

    # the report
    print("threads (unix tid, name, user/system ticks):")
    for line in tasks.splitlines():
        print("  " + line)
    for line in p1.splitlines():
        f = line.split()
        if len(f) == 5 and f[0] == "L":
            print("loader lock %s: %s (LockCount %s, RecursionCount %s, owner thread %s)"
                  % (f[1], "free" if f[2] == "-1" else "HELD", f[2], f[3], f[4]))
    for teb, cpu, tid in tebs:
        unix = unix_of.get(teb, "")
        if unix and unix.split()[0] in ticks:
            unix += " ticks %s/%s" % tuple(ticks[unix.split()[0]])
        head = "== windows thread %04x, TEB %x%s" % (tid, teb, ", unix " + unix if unix else "")
        ctx = parts.get(("CTX", teb), (None, []))[1]
        if not cpu or len(ctx) < CTX_WORDS:
            print(head + ": no i386 context (still in its 64-bit start, or not a WoW64 thread)")
            continue
        ebp, eip, esp = ctx[CTX_EBP], ctx[CTX_EIP], ctx[CTX_ESP]
        print(head + ": eip %08x esp %08x ebp %08x" % (eip, esp, ebp))
        print("     " + mods.name(eip))
        base, stack = parts.get(("STK", teb), (None, []))
        if not stack:
            base, stack = parts.get(("STK2", teb), (None, []))
        if not stack:
            continue
        mem = lambda a: stack[(a - base) // 4] if base <= a < base + 4 * len(stack) and not (a - base) % 4 else None
        for _ in range(30):
            ret, nxt = mem(ebp + 4), mem(ebp)
            if ret is None or not ret:
                break
            print("     " + mods.name(ret))
            if nxt is None or nxt <= ebp:
                break
            ebp = nxt
        found = [w for w in stack[:400]
                 if (mods.of(w)[0] or "").lower().endswith((".dll", ".drv", ".exe", ".dae", ".sys"))]
        if found:
            print("     scan: " + "; ".join(mods.name(w).split(" ", 1)[1] for w in found[:12]))
    print("raw data in " + out)


main()
