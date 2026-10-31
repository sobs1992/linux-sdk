#!/usr/bin/env python3
"""
oga-serial: drive an ODROID-GO Advance through its serial console.

Works with the stock SDK rootfs (root without password, busybox sh with
base64/gzip): no network, no extra packages on the board. Files travel
gzip + base64 inside the console stream, about 10 KB/s of compressed data
at 115200.

  oga-serial.py sh 'uname -a'             run a command, print its output, exit with its status
  oga-serial.py push LOCAL REMOTE         copy a file to the board (keeps the x bit, checks md5)
  oga-serial.py pull REMOTE LOCAL         copy a file from the board
  oga-serial.py run LOCAL [ARGS...]       push to /tmp/<name> and run it in the foreground
  oga-serial.py run --bg LOCAL [ARGS...]  same, in the background, output in /tmp/<name>.log
  oga-serial.py shot OUT.png              screenshot of /dev/fb0, turned as the user sees it
  oga-serial.py key right right a f6      press buttons (writes events into gpio-keys)

Buttons: up down left right a b x y f1..f6 l r (TOP-LEFT/TOP-RIGHT).

Logs in as root when the console sits at the login prompt. The port is
opened exclusively: close screen/picocom on it first.
"""
import argparse
import base64
import gzip
import hashlib
import os
import re
import struct
import sys
import time
import zlib

try:
    import serial
except ImportError:
    sys.exit("oga-serial: needs pyserial (apt install python3-serial)")

PROMPT = re.compile(rb"[#$] $")
B64_LINE = 76

# gpio-keys codes from rk3326-odroid-go.dtsi
KEYS = {
    "up": 0x220, "down": 0x221, "left": 0x222, "right": 0x223,
    "a": 0x131, "b": 0x130, "y": 0x134, "x": 0x133,   # BTN_EAST/SOUTH/WEST/NORTH
    "l": 0x136, "r": 0x137,                           # BTN_TL/BTN_TR
    **{"f%d" % i: 0x2bf + i for i in range(1, 7)},    # BTN_TRIGGER_HAPPY1..6
}


class Console:
    def __init__(self, port, baud):
        try:
            self.s = serial.Serial(port, baud, timeout=0.2, exclusive=True)
        except serial.SerialException as e:
            sys.exit("oga-serial: %s (is screen/picocom holding it?)" % e)
        self.nonce = 0

    def read_until(self, pattern, timeout):
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            buf += self.s.read(65536)
            if pattern.search(buf):
                return buf
        raise TimeoutError(buf)

    def login(self):
        """Get to a root shell prompt, logging in if needed."""
        self.s.reset_input_buffer()
        self.s.write(b"\x03\n")         # drop any half-typed line
        try:
            buf = self.read_until(re.compile(rb"(login: |Password: |[#$] )$"), 5)
        except TimeoutError:
            sys.exit("oga-serial: no prompt on the console (board off or still booting?)")
        if buf.endswith(b"Password: "):
            self.s.write(b"\n")         # fail this attempt, get a fresh login
            buf = self.read_until(re.compile(rb"login: $"), 10)
        if buf.endswith(b"login: "):
            self.s.write(b"root\n")
            self.read_until(PROMPT, 10)
        time.sleep(0.1)
        self.s.reset_input_buffer()

    def sh(self, cmd, timeout=60, stdin_lines=()):
        """Run cmd, return (status, output bytes). The console echoes every
        line, so the output is cut out between markers that only appear
        when printf runs, never in the echoed command text."""
        self.nonce += 1
        tag = "%d%d" % (os.getpid(), self.nonce)
        line = "printf '@@B%%s\\n' %s; %s; printf '@@E%%s %%s\\n' %s $?" % (tag, cmd, tag)
        self.s.write(line.encode() + b"\n")
        for l in stdin_lines:
            self.s.write(l)
        end = re.compile(rb"\n@@E%s (\d+)\r?\n" % tag.encode())
        try:
            buf = self.read_until(end, timeout)
        except TimeoutError:
            self.s.write(b"\x03")
            sys.exit("oga-serial: '%s' did not finish in %ds, sent Ctrl-C" % (cmd, timeout))
        m = end.search(buf)
        start = buf.index(b"\n", buf.index(b"\n@@B" + tag.encode()) + 1) + 1
        out = buf[start:m.start()].replace(b"\r\n", b"\n")
        return int(m.group(1)), out.rstrip(b"\r")

    def heredoc_cmd(self, data, cmd):
        """Run 'cmd' with data on stdin (gzip + base64 heredoc)."""
        b64 = base64.b64encode(gzip.compress(data, 9)).decode()
        lines = [(b64[i:i + B64_LINE] + "\n").encode() for i in range(0, len(b64), B64_LINE)]
        lines.append(b"OGA_EOF\n")
        timeout = 30 + len(b64) / 5000
        return self.sh("base64 -d <<'OGA_EOF' | gunzip | %s" % cmd, timeout, lines)

    def push(self, local, remote):
        data = open(local, "rb").read()
        mode = "chmod +x %s; " % remote if os.access(local, os.X_OK) else ""
        st, _ = self.heredoc_cmd(data, "cat > %s" % remote)
        st2, out = self.sh("%smd5sum %s" % (mode, remote))
        if st or st2 or out.split()[0].decode() != hashlib.md5(data).hexdigest():
            sys.exit("oga-serial: push %s -> %s failed: %s" % (local, remote, out.decode(errors="replace")))

    def pull_cmd(self, cmd, timeout=300):
        st, out = self.sh("%s | gzip -c | base64" % cmd, timeout)
        if st:
            sys.exit("oga-serial: '%s' failed" % cmd)
        return gzip.decompress(base64.b64decode(re.sub(rb"\s", b"", out)))


def write_png(path, w, h, rgb):
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def screenshot(con, path):
    st, info = con.sh("cat /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel "
                      "/sys/class/graphics/fbcon/rotate 2>/dev/null")
    vals = info.decode().split()
    w, h = map(int, vals[0].split(","))
    bpp = int(vals[1])
    rot = int(vals[2]) if len(vals) > 2 else 0
    if bpp != 32:
        sys.exit("oga-serial: shot supports only 32 bpp, fb0 is %d" % bpp)
    fb = con.pull_cmd("dd if=/dev/fb0 bs=%d count=1 2>/dev/null" % (w * h * 4))
    px = [bytes((fb[i + 2], fb[i + 1], fb[i])) for i in range(0, w * h * 4, 4)]   # BGRX -> RGB
    # fbcon=rotate:N turns the console N*90 degrees clockwise; turn the
    # framebuffer back (N*90 counterclockwise = (4-N)*90 clockwise).
    for _ in range((4 - rot) % 4):
        px = [px[(h - 1 - x) * w + y] for y in range(w) for x in range(h)]   # 90 cw
        w, h = h, w
    write_png(path, w, h, b"".join(px))


def keys(con, names, delay):
    try:
        codes = [KEYS[n.lower()] for n in names]
    except KeyError as e:
        sys.exit("oga-serial: unknown button %s, known: %s" % (e, " ".join(KEYS)))
    # struct input_event on arm64: timeval (16), u16 type, u16 code, s32 value
    ev = lambda t, c, v: b"\0" * 16 + struct.pack("<HHi", t, c, v)
    data = b"".join(ev(1, c, 1) + ev(0, 0, 0) + ev(1, c, 0) + ev(0, 0, 0) for c in codes)
    con.heredoc_cmd(data, "cat > /tmp/.oga-keys")
    st, out = con.sh(
        "for d in /sys/class/input/event*; do [ \"$(cat $d/device/name)\" = gpio-keys ] && dev=/dev/input/${d##*/}; done; "
        "i=0; while [ $i -lt %d ]; do dd if=/tmp/.oga-keys of=$dev bs=96 skip=$i count=1 2>/dev/null; "
        "sleep %s; i=$((i+1)); done; rm /tmp/.oga-keys" % (len(codes), delay), 30 + len(codes) * delay)
    if st:
        sys.exit("oga-serial: key injection failed: %s" % out.decode(errors="replace"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-p", "--port", default=os.environ.get("OGA_PORT", "/dev/ttyUSB0"))
    p.add_argument("-b", "--baud", type=int, default=115200)
    p.add_argument("-t", "--timeout", type=int, default=60, help="for sh/run, seconds")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sh"); s.add_argument("command", nargs="+")
    s = sub.add_parser("push"); s.add_argument("local"); s.add_argument("remote")
    s = sub.add_parser("pull"); s.add_argument("remote"); s.add_argument("local")
    s = sub.add_parser("run"); s.add_argument("--bg", action="store_true")
    s.add_argument("local"); s.add_argument("args", nargs=argparse.REMAINDER)
    s = sub.add_parser("shot"); s.add_argument("out")
    s = sub.add_parser("key"); s.add_argument("--delay", type=float, default=0.2)
    s.add_argument("names", nargs="+")
    a = p.parse_args()

    con = Console(a.port, a.baud)
    con.login()
    if a.cmd == "sh":
        st, out = con.sh(" ".join(a.command), a.timeout)
        sys.stdout.buffer.write(out + (b"\n" if out else b""))
        sys.exit(st)
    elif a.cmd == "push":
        con.push(a.local, a.remote)
    elif a.cmd == "pull":
        open(a.local, "wb").write(con.pull_cmd("cat %s" % a.remote))
    elif a.cmd == "run":
        remote = "/tmp/" + os.path.basename(a.local)
        con.push(a.local, remote)
        args = " ".join(a.args)
        if a.bg:
            con.sh("(%s %s > %s.log 2>&1 &)" % (remote, args, remote))
            print("started %s, log %s.log" % (remote, remote))
        else:
            st, out = con.sh("%s %s" % (remote, args), a.timeout)
            sys.stdout.buffer.write(out + (b"\n" if out else b""))
            sys.exit(st)
    elif a.cmd == "shot":
        screenshot(con, a.out)
    elif a.cmd == "key":
        keys(con, a.names, a.delay)


if __name__ == "__main__":
    main()
