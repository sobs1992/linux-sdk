#!/usr/bin/env python3
"""
ogu-ctl: drive bare_app on the ODROID-GO Ultra over the network on its
USB-C port (S42usbnet: the board is 192.168.7.2; OGU_HOST to change it).

  ogu-ctl.py shot:FILE.png        screenshot of bare_app's layers (SIGUSR1)
  ogu-ctl.py a wait:2000 down a   buttons: up down left right a b x y l r l2 r2 f1..f6,
                                  NAME:MS holds one for MS (default 100): by
                                  bare_app's FIFO (press/release) where its bare_app
                                  has them, else written into gpio-keys (a write
                                  lasts until the driver's next poll, 16 ms; over
                                  150 ms written again every 2 ms by ogu-hold,
                                  which flickers at each poll)
  ogu-ctl.py stick:1,0.5,800      left stick at X,Y (-1..1, up and left negative)
                                  for MS (default 300), then back to the center
  ogu-ctl.py rstick:0,-1          the right stick
  ogu-ctl.py wait:MS              pause
  ogu-ctl.py launch:monkey2       bare_app starts a game (its directory's name, its
                                  title or key), without going through the menu
  ogu-ctl.py quit-game            bare_app ends the game (in front or minimised)
  ogu-ctl.py wfmove:400,240 wclick
                                  a Windows game's cursor to a pixel of the screenshot
                                  (shot:), a left click there; wmove:X,Y a point of the
                                  Windows screen, wclick:right, wkey:NAME a key of
                                  wine.ini's [keys] names (esc, enter, f10, ctrl+s)

Steps run in order, in one go on the board. launch, quit-game and the w steps
are lines for the FIFOs of bare_app (/tmp/bare_app.ctl) and bare_app_wine
(/tmp/bare_app_wine.ctl, while a Windows game runs). Button presses are written into
the gpio-keys evdev device, so bare_app and the game get them like real
ones; the sticks need scripts/ogu-hold.c on the board (built with the ogu
firmware's toolchain and copied to /tmp on first use).

The board's SSH host key changes with every image written, and this link is
a cable between two machines: the key is neither checked nor remembered.
"""
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devlib
from devlib import KEYS, SDK, input_event as event

HOST = "root@" + os.environ.get("OGU_HOST", "192.168.7.2")
SSH = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST]
HOLD = "/tmp/ogu-hold"
OUT = devlib.output("ogu")      # the firmware's build output (OUTPUT_DIR)
CC = devlib.toolchain_cc("ogu")

# evdev device variable, (code, min, max) of X and Y: the dts ranges, up/left the minimum
STICKS = {"stick": ("L", (0, 700, 2900), (1, 950, 3150)),
          "rstick": ("R", (3, 800, 3000), (4, 950, 3150))}
FIND = ('for d in /sys/class/input/event*; do case "$(cat $d/device/name)" in '
        'gpio-keys) K=/dev/input/${d##*/};; adc-joystick-left) L=/dev/input/${d##*/};; '
        'adc-joystick-right) R=/dev/input/${d##*/};; esac; done')


APP_CTL, WINE_CTL = "/tmp/bare_app.ctl", "/tmp/bare_app_wine.ctl"


def ctl(fifo, line):
    """A shell command writing LINE to FIFO: only into a FIFO there (a game's
    is gone once it ends, and echo would make a file of that name)"""
    return ("if [ -p %s ]; then echo %s > %s; else echo 'ogu-ctl: %s: not there' >&2; fi"
            % (fifo, shlex.quote(line), fifo, fifo))


def die(msg):
    sys.exit("ogu-ctl: " + msg)


def ssh(cmd, data=None):
    r = subprocess.run(SSH + [cmd], input=data, capture_output=True)
    if r.returncode:
        die("%s: %s" % (HOST, r.stderr.decode(errors="replace").strip() or "exit %d" % r.returncode))
    sys.stderr.write(r.stderr.decode(errors="replace"))	# what the steps tell
    return r.stdout


def shot(path):
    ppm = ssh("kill -USR1 $(pidof bare_app) && sleep 0.7 && cat /tmp/bare_app.ppm")
    w, h = devlib.ppm_to_png(ppm, path)
    print("%s: %dx%d" % (path, w, h))


def need_hold():
    if ssh("[ -x %s ] && echo yes || true" % HOLD).strip() == b"yes":
        return
    if not os.path.exists(CC):
        die("no ogu toolchain (%s): run 'make FW=ogu rootfs'" % CC)
    out = os.path.join(OUT, "ogu-hold")
    subprocess.run([CC, "-O2", "-s", "-Wall", "-o", out, os.path.join(SDK, "scripts/ogu-hold.c")], check=True)
    with open(out, "rb") as f:
        ssh("cat > %s && chmod 755 %s" % (HOLD, HOLD), f.read())


_fifo_press = None


def press_by_fifo():
    """Whether the board's bare_app takes "press NAME" on its FIFO (the
    buttons are then pressed there, for exactly as long as asked)"""
    global _fifo_press
    if _fifo_press is None:
        _fifo_press = ssh("grep -q 'no such button' /usr/bin/bare_app && echo yes || true").strip() == b"yes"
    return _fifo_press


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
        elif name == "launch" and arg:
            script.append(ctl(APP_CTL, "launch " + arg))
        elif name == "quit-game":
            script.append(ctl(APP_CTL, "quit-game"))
        elif name in ("wmove", "wfmove") and len(arg.split(",")) == 2:
            x, y = (int(v) for v in arg.split(","))
            script.append(ctl(WINE_CTL, "%s %d %d" % (name[1:], x, y)) + "; sleep 0.1")
        elif name == "wclick":
            script.append(ctl(WINE_CTL, "click right" if arg == "right" else "click") + "; sleep 0.3")
        elif name == "wkey" and arg:
            script.append(ctl(WINE_CTL, "key " + arg) + "; sleep 0.3")
        elif name in STICKS:
            dev, ax, ay = STICKS[name]
            v = [float(x) for x in arg.split(",")]
            ms = int(v[2]) if len(v) > 2 else 300
            val = lambda a, f: int((a[1] + a[2]) / 2 + max(-1, min(1, f)) * (a[2] - a[1]) / 2)
            need_hold()
            script.append("%s $%s %d %d %d %d %d; sleep 0.15" %
                          (HOLD, dev, ms, ax[0], val(ax, v[0]), ay[0], val(ay, v[1])))
        elif name.lower() in KEYS and press_by_fifo():
            # bare_app's own press and release, held exactly that long (a
            # write into gpio-keys-polled's device lasts until its next poll)
            gp = {"l": "l1", "r": "r1"}.get(name.lower(), name.lower())
            script.append(ctl(APP_CTL, "press " + gp) + "; sleep %.3f; " % (int(arg or 100) / 1000)
                          + ctl(APP_CTL, "release " + gp) + "; sleep 0.25")
        elif name.lower() in KEYS and int(arg or 100) > 150:
            # held longer than a poll of gpio-keys-polled: written again and again
            need_hold()
            script.append("%s $K %d k%d 1; sleep 0.15" % (HOLD, int(arg), KEYS[name.lower()]))
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
