#!/usr/bin/env python3
"""gecko-hang-monitor.py XUL.DLL: Wine Gecko 2.47.4 (x86) without the stack
snapshots of its hang monitor, which hang games under Box64.

Gecko's BackgroundHangMonitor thread takes a snapshot of the main thread's
stack when an event takes long (ThreadStackHelper::GetStack): it calls
SuspendThread on the main thread. Under Wine's WoW64 with Box64 the main
thread may be suspended anywhere, also while it holds a lock of Box64's;
the monitor then waits for that lock: deadlock. Telltale's launcher
(Tales of Monkey Island) hung so in 6 runs of 7, never with this patch
(7 of 7), and again without it (2 of 2). The snapshots only feed Gecko's
telemetry. Gecko 47 has no preference that turns the monitor off.

The patch: at VA 0x100919d8 (file offset 0x919d8), "if (!mInitialized)
return" becomes "always return" (74 1e -> eb 1e). The file is changed in
place; the original must be the one of wine-gecko-2.47.4-x86.msi."""
import hashlib, sys

ORIG = '2bc96cd52ce43c123dc37e40a2304325'
DONE = 'e55d58eedaca8348f3fc043d73dbb7aa'
OFF, OLD, NEW = 0x919d8, b'\x74\x1e', b'\xeb\x1e'

path = sys.argv[1]
data = bytearray(open(path, 'rb').read())
md5 = hashlib.md5(data).hexdigest()
if md5 == DONE:
    print(path + ': patched already')
    sys.exit(0)
if md5 != ORIG or data[OFF:OFF + 2] != OLD:
    sys.exit(path + ': not the xul.dll of Wine Gecko 2.47.4 x86 (md5 ' + md5 + ')')
data[OFF:OFF + 2] = NEW
assert hashlib.md5(data).hexdigest() == DONE
open(path, 'r+b').write(data)
print(path + ': hang monitor snapshots off')
