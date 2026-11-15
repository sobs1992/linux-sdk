# Tales of Monkey Island, chapter 1

Telltale's game (2009, Direct3D 9) under Wine on the GO Ultra, Russian
edition. `MonkeyIsland101.exe` always shows Telltale's launcher first: an
HTML page in mshtml, so Wine Gecko must be in the prefix. The image does
not carry it yet; once on the console:

1. Wine Gecko 2.47.4 x86 into the prefix (the console has no internet:
   copy the msi from https://dl.winehq.org/wine/wine-gecko/2.47.4/):

       WINEPREFIX=/data/wine/prefix wine msiexec /i wine-gecko-2.47.4-x86.msi /q

2. Its hang monitor off (otherwise the launcher hangs most starts, see the
   script):

       python3 gecko-hang-monitor.py /data/wine/prefix/drive_c/windows/syswow64/gecko/2.47.4/wine_gecko/xul.dll

   (or run it on the PC on a copy and put that back).

3. Start the game, press "Launch Game!", then in Settings > Graphics choose
   640x480 (the game offers 640x480, 800x600, 1024x768; it starts at
   1024x768, which shrinks to 640x480 anyway and runs at half the speed).
   Leave the game by its menu (Exit) once, so that it keeps the setting.

The launcher's buttons are PNG pictures shown through IE's
AlphaImageLoader filter (its png.js for IE 5.5-7, which Wine is for a page
without a doctype); Wine's patch 0016 shows them.
