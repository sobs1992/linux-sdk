#!/usr/bin/env python3
"""Set values in an ini file of Gothic (Gothic.ini, SystemPack.ini).

gothic_ini.py FILE SECTION.KEY=VALUE...

Each key is replaced in its section (the first [SECTION] of that name), or
added at the end of the section when it has none. The file keeps its line
ends (CRLF) and its bytes (cp1252/cp1251 comments are left as they are).
"""
import sys


def main():
    path = sys.argv[1]
    with open(path, "rb") as f:
        lines = f.read().split(b"\n")
    for arg in sys.argv[2:]:
        name, value = arg.split("=", 1)
        section, key = name.split(".", 1)
        sect = None	# index of the [SECTION] line
        end = None	# where the section's lines stop
        done = False
        for i, raw in enumerate(lines):
            line = raw.rstrip(b"\r").strip()
            if line.startswith(b"[") and line.endswith(b"]"):
                if sect is not None and end is None:
                    end = i
                if sect is None and line[1:-1].decode("latin1").lower() == section.lower():
                    sect = i
                continue
            if sect is None or end is not None:
                continue
            k = line.split(b"=", 1)[0].strip()
            if b"=" in line and k.decode("latin1").lower() == key.lower():
                cr = b"\r" if raw.endswith(b"\r") else b""
                lines[i] = k + b"=" + value.encode("latin1") + cr
                done = True
                break
        if done:
            continue
        if sect is None:
            sys.exit("%s: no section [%s]" % (path, section))
        if end is None:
            end = len(lines)
        # after the section's last non-empty line
        at = end
        while at > sect + 1 and not lines[at - 1].strip(b"\r").strip():
            at -= 1
        cr = b"\r" if lines[sect].endswith(b"\r") else b""
        lines.insert(at, key.encode("latin1") + b"=" + value.encode("latin1") + cr)
    with open(path, "wb") as f:
        f.write(b"\n".join(lines))


main()
