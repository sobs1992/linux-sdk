#!/usr/bin/env python3
"""Readings of a FNIRSI USB tester (FNAC-28, C1: 0483:003b; FNB48: 0483:003a)
over its HID interface, without extra libraries (Linux hidraw).

The FNAC-28 answers a poll, "aa 82" then "aa 83" (64 bytes each: the
command, zeros, a check byte), with a 64-byte report "aa 04": 4 samples of
15 bytes from byte 2, voltage (u32 LE, 1e-5 V), current (u32 LE, 1e-5 A),
D+ and D- (u16 LE, mV), a byte, temperature (u16 LE at +13, 0.1 C). Checked
on the FNAC-28 of 2026-11-21: 5.0758 V, 0.1217 A, 30.9 C. The charge and
the energy are summed here over the real time between two replies.

  fnirsi-meter.py                    one line a second: V, A, W, mAh, Wh
  fnirsi-meter.py --csv FILE         also every averaged line into FILE
  fnirsi-meter.py --interval 0.1     average over 0.1 s instead of 1 s
  fnirsi-meter.py --duration 600     stop after 10 min (default: Ctrl-C)
  fnirsi-meter.py --raw              the reports as hex (protocol checks)

The hidraw node is root's by default; once:
  sudo tee /etc/udev/rules.d/70-fnirsi.rules <<<'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="003[ab]", MODE="0660", TAG+="uaccess"'
  sudo udevadm control --reload && sudo udevadm trigger
"""
import argparse
import glob
import os
import select
import sys
import time

IDS = {("0483", "003B"), ("0483", "003A")}
CMD = {0x82: 0x96, 0x83: 0x9E}


def find_dev():
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            ue = open(os.path.join(d, "device", "uevent")).read()
        except OSError:
            continue
        for line in ue.splitlines():
            if line.startswith("HID_ID="):
                _, vid, pid = line.split("=")[1].split(":")
                if (vid[-4:].upper(), pid[-4:].upper()) in IDS:
                    return "/dev/" + os.path.basename(d)
    return None


def command(fd, code):
    # hidraw: the report number first, 0 for a device without numbered ones
    os.write(fd, bytes([0, 0xAA, code]) + bytes(61) + bytes([CMD[code]]))


def samples(report):
    if len(report) < 62 or report[1] != 0x04:
        return []
    out = []
    for i in range(4):
        o = 2 + 15 * i
        u32 = lambda k: int.from_bytes(report[o + k:o + k + 4], "little")
        u16 = lambda k: int.from_bytes(report[o + k:o + k + 2], "little")
        out.append((u32(0) / 1e5, u32(4) / 1e5, u16(8) / 1e3, u16(10) / 1e3, u16(13) / 10.0))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", help="the hidraw node (found by its USB id)")
    ap.add_argument("--interval", type=float, default=1.0, help="averaging window, s")
    ap.add_argument("--csv", help="write the averaged lines here too")
    ap.add_argument("--duration", type=float, help="stop after this many s")
    ap.add_argument("--poll", type=float, default=0.04, help="a poll every this many s")
    ap.add_argument("--raw", action="store_true", help="print the reports as hex")
    a = ap.parse_args()

    dev = a.dev or find_dev()
    if not dev:
        sys.exit("no FNIRSI tester (0483:003b/003a) among the hidraw devices")
    try:
        fd = os.open(dev, os.O_RDWR)
    except PermissionError:
        sys.exit("%s: no permission (see the udev rule in --help)" % dev)

    csv = open(a.csv, "a", buffering=1) if a.csv else None
    if csv and csv.tell() == 0:
        csv.write("time,volt,amp,watt,dp_v,dn_v,temp_c,mah,wh,n\n")
    t0 = time.time()
    win_end = t0 + a.interval
    acc = [0.0] * 5
    n = 0
    mah = wh = 0.0
    last = None			# (time, V, A) of the last reply
    misses = 0
    try:
        while True:
            now = time.time()
            if a.duration and now - t0 >= a.duration:
                break
            command(fd, 0x82)
            command(fd, 0x83)
            got = None
            end = time.time() + 0.3
            while time.time() < end:
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    continue
                rep = os.read(fd, 64)
                if a.raw:
                    print("%.3f %s" % (time.time() - t0, rep.hex(" ")), flush=True)
                s4 = samples(rep)
                if s4:
                    got = s4
                    break
            tr = time.time()
            if got:
                misses = 0
                v = sum(x[0] for x in got) / len(got)
                i = sum(x[1] for x in got) / len(got)
                if last:
                    dt = tr - last[0]
                    if dt < 2:		# a gap: not summed
                        mah += (i + last[2]) / 2 * 1000 * dt / 3600
                        wh += (v * i + last[1] * last[2]) / 2 * dt / 3600
                last = (tr, v, i)
                acc[0] += v; acc[1] += i
                acc[2] += sum(x[2] for x in got) / len(got)
                acc[3] += sum(x[3] for x in got) / len(got)
                acc[4] = got[0][4]
                n += 1
            else:
                misses += 1
                if misses == 10:
                    print("no reply to 10 polls", file=sys.stderr)
            if tr >= win_end:
                if n and not a.raw:
                    v, i, dp, dn = (x / n for x in acc[:4])
                    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(tr)) + ".%02d" % int(tr % 1 * 100)
                    print("%s  %7.4f V  %7.4f A  %7.4f W  %9.2f mAh  %8.4f Wh  %.1f C" % (
                        time.strftime("%H:%M:%S"), v, i, v * i, mah, wh, acc[4]), flush=True)
                    if csv:
                        csv.write("%s,%.5f,%.5f,%.5f,%.3f,%.3f,%.1f,%.3f,%.5f,%d\n" % (
                            stamp, v, i, v * i, dp, dn, acc[4], mah, wh, n))
                acc = [0.0] * 5
                n = 0
                win_end = tr + a.interval
            time.sleep(max(0.0, a.poll - (time.time() - now)))
    except KeyboardInterrupt:
        pass
    print("total %.2f mAh, %.4f Wh in %.0f s" % (mah, wh, time.time() - t0), file=sys.stderr)


if __name__ == "__main__":
    main()
