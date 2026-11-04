#!/usr/bin/env python3
"""
ogu-ctl: drive bare_app on the ODROID-GO Ultra over the network on its
USB-C port (S42usbnet: the board is 192.168.7.2; OGU_HOST to change it).

  ogu-ctl.py shot:FILE.png        screenshot of bare_app's layers (SIGUSR1)
  ogu-ctl.py a wait:2000 down a   buttons: up down left right a b x y l r l2 r2 f1..f6,
                                  NAME:MS holds one for MS (default 100)
  ogu-ctl.py stick:1,0.5,800      left stick at X,Y (-1..1, up and left negative)
                                  for MS (default 300), then back to the center
  ogu-ctl.py rstick:0,-1          the right stick
  ogu-ctl.py wait:MS              pause

Steps run in order, in one go on the board. Button presses are written into
the gpio-keys evdev device, so bare_app and the game get them like real
ones; the sticks need scripts/ogu-hold.c on the board (built with the ogu
firmware's toolchain and copied to /tmp on first use).

The board's SSH host key changes with every image written, and this link is
a cable between two machines: the key is neither checked nor remembered.
"""
import os
import struct
import subprocess
import sys
import zlib

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "root@" + os.environ.get("OGU_HOST", "192.168.7.2")
SSH = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST]
HOLD = "/tmp/ogu-hold"
CC = os.path.join(SDK, "output/ogu/buildroot/host/bin/aarch64-buildroot-linux-gnu-gcc")

# gpio-keys codes from meson-g12b-odroid-go-ultra.dts
KEYS = {"up": 0x220, "down": 0x221, "left": 0x222, "right": 0x223,
        "a": 0x131, "b": 0x130, "x": 0x133, "y": 0x134,      # BTN_EAST/SOUTH/NORTH/WEST
        "l": 0x136, "r": 0x137, "l2": 0x138, "r2": 0x139,
        **{"f%d" % i: 0x2bf + i for i in range(1, 7)}}       # BTN_TRIGGER_HAPPY1..6
# evdev device variable, (code, min, max) of X and Y: the dts ranges, up/left the minimum
STICKS = {"stick": ("L", (0, 700, 2900), (1, 950, 3150)),
          "rstick": ("R", (3, 800, 3000), (4, 950, 3150))}
FIND = ('for d in /sys/class/input/event*; do case "$(cat $d/device/name)" in '
        'gpio-keys) K=/dev/input/${d##*/};; adc-joystick-left) L=/dev/input/${d##*/};; '
        'adc-joystick-right) R=/dev/input/${d##*/};; esac; done')


def die(msg):
    sys.exit("ogu-ctl: " + msg)


def ssh(cmd, data=None):
    r = subprocess.run(SSH + [cmd], input=data, capture_output=True)
    if r.returncode:
        die("%s: %s" % (HOST, r.stderr.decode(errors="replace").strip() or "exit %d" % r.returncode))
    return r.stdout


def event(type_, code, value):
    # struct input_event on arm64: timeval (16), u16 type, u16 code, s32 value
    return b"\0" * 16 + struct.pack("<HHi", type_, code, value)


def shot(path):
    ppm = ssh("kill -USR1 $(pidof bare_app) && sleep 0.7 && cat /tmp/bare_app.ppm")
    end = ppm.index(b"\n255\n")
    w, h = map(int, ppm[:end].split()[-2:])
    px = ppm[end + 5:]
    raw = b"".join(b"\0" + px[y * w * 3:(y + 1) * w * 3] for y in range(h))
    chunk = lambda t, b: struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    print("%s: %dx%d" % (path, w, h))


def need_hold():
    if ssh("[ -x %s ] && echo yes || true" % HOLD).strip() == b"yes":
        return
    if not os.path.exists(CC):
        die("no ogu toolchain (%s): run 'make FW=ogu rootfs'" % CC)
    out = os.path.join(SDK, "output/ogu/ogu-hold")
    subprocess.run([CC, "-O2", "-s", "-Wall", "-o", out, os.path.join(SDK, "scripts/ogu-hold.c")], check=True)
    with open(out, "rb") as f:
        ssh("cat > %s && chmod 755 %s" % (HOLD, HOLD), f.read())


def run(steps):
    """Key events go into one file; a shell script writes them out with the pauses"""
    blob, script = b"", []

    def flush():
        nonlocal blob, script
        if script:
            ssh("cat > /tmp/.ogu-ev && %s; %s; rm -f /tmp/.ogu-ev" % (FIND, "; ".join(script)), blob)
        blob, script = b"", []

    for step in steps:
        name, _, arg = step.partition(":")
        if name == "shot":
            flush()
            shot(arg or "ogu.png")
        elif name == "wait":
            script.append("sleep %.3f" % (int(arg) / 1000))
        elif name in STICKS:
            dev, ax, ay = STICKS[name]
            v = [float(x) for x in arg.split(",")]
            ms = int(v[2]) if len(v) > 2 else 300
            val = lambda a, f: int((a[1] + a[2]) / 2 + max(-1, min(1, f)) * (a[2] - a[1]) / 2)
            need_hold()
            script.append("%s $%s %d %d %d %d %d; sleep 0.15" %
                          (HOLD, dev, ms, ax[0], val(ax, v[0]), ay[0], val(ay, v[1])))
        elif name.lower() in KEYS:
            code = KEYS[name.lower()]
            press, release = event(1, code, 1) + event(0, 0, 0), event(1, code, 0) + event(0, 0, 0)
            # evdev takes whole events per write: blocks of 24 bytes
            for data, pause in ((press, int(arg or 100) / 1000), (release, 0.25)):
                script.append("dd if=/tmp/.ogu-ev of=$K bs=24 skip=%d count=%d 2>/dev/null; sleep %.3f"
                              % (len(blob) // 24, len(data) // 24, pause))
                blob += data
        else:
            die("unknown step '%s' (see %s -h)" % (step, sys.argv[0]))
    flush()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)
    run(sys.argv[1:])
