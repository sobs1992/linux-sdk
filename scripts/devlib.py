"""
devlib: what the board tools share (oga-serial.py over UART, ogu-ctl.py over
ssh, doom3-test.py): the SDK's paths, the gamepad's evdev codes, input events
and PNG pictures. Standard library only.
"""
import os
import struct
import zlib

SDK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The build outputs: the Makefile's OUTPUT_DIR (output/ unless set)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(SDK, "output"))


def output(fw, *path):
    """A path in the firmware's build output: output("ogu", "buildroot", "target")"""
    return os.path.join(OUTPUT_DIR, fw, *path)


def toolchain_cc(fw, triple="aarch64-buildroot-linux-gnu"):
    """The firmware's cross compiler from its Buildroot host tools"""
    return output(fw, "buildroot", "host", "bin", triple + "-gcc")


# gpio-keys codes of the ODROID-GO Advance (rk3326-odroid-go.dtsi) and the
# GO Ultra (meson-g12b-odroid-go-ultra.dts): the same for the keys both
# have; L2/R2 are the GO Ultra's only (the Advance drops the events)
KEYS = {
    "up": 0x220, "down": 0x221, "left": 0x222, "right": 0x223,
    "a": 0x131, "b": 0x130, "x": 0x133, "y": 0x134,      # BTN_EAST/SOUTH/NORTH/WEST
    "l": 0x136, "r": 0x137, "l2": 0x138, "r2": 0x139,    # BTN_TL/TR/TL2/TR2
    **{"f%d" % i: 0x2bf + i for i in range(1, 7)},       # BTN_TRIGGER_HAPPY1..6
}


def input_event(type_, code, value):
    """struct input_event on arm64: timeval (16 bytes), u16 type, u16 code, s32 value"""
    return b"\0" * 16 + struct.pack("<HHi", type_, code, value)


def key_press(code):
    """A press and a release of a key, each followed by SYN_REPORT: 96 bytes"""
    return (input_event(1, code, 1) + input_event(0, 0, 0) +
            input_event(1, code, 0) + input_event(0, 0, 0))


def write_png(path, w, h, rgb, level=6):
    """RGB bytes (3 a pixel, rows top down) as an 8-bit RGB PNG"""
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, level)) + chunk(b"IEND", b""))


def ppm_to_png(ppm, path):
    """A binary PPM (P6, 8 bits: bare_app's screenshots) as a PNG; (w, h)"""
    end = ppm.index(b"\n255\n")
    w, h = map(int, ppm[:end].split()[-2:])
    write_png(path, w, h, ppm[end + 5:])
    return w, h
