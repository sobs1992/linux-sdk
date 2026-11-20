#!/usr/bin/env python3
"""
Serious Sam (The First and The Second Encounter) on bare_app's gamepad:
rewrites the game's Controls/00-Default.ctl, the controls a new player
gets, with the gamepad as each action's second key (the first, the
keyboard and the mouse, stays) and the sticks as the axes.

  controls.py GAME_DIR

The gamepad is SDL's bareapp joystick: buttons and axes numbered as an SDL
game controller's (A 0, B 1, X 2, Y 3, L1 9, R1 10, D-pad 11-14; the axes
X Y the left stick, Z R the right one). L2 and R2 are buttons paddle3 (18)
and paddle2 (17), as the game.ini's "gamepad" makes them: the engine reads
a trigger only as an axis.
"""
import os
import re
import sys

# action name (as the .ctl names it, "TTRS " left out) -> gamepad button.
# The first action of a name gets it (00-Default.ctl names Strafe twice).
# The GO Ultra: as DOOM 3 BFG's handheld layout (rbdoom3-bfg 0019): A use,
# B jump, X crouch, L1 reload, R1 fire, L2/R2 previous/next weapon, the
# D-pad walks, Back (F4) NETRICSA as DOOM 3's PDA; Y, DOOM 3's flashlight,
# the Serious Bomb (The Second Encounter) or Flip Weapon (The First)
BUTTONS = {
    "Use/Sniper Zoom": 0,           # A (The Second Encounter)
    "Use": 0,                       # A (The First Encounter)
    "Up/Jump": 1,                   # B
    "Down/Duck": 2,                 # X
    "Serious Bomb": 3,              # Y (The Second Encounter)
    "Invoke NETRICSA": 4,           # Back: F4 (game.ini's gamepad f4=back)
    "Reload": 9,                    # L1
    "Fire": 10,                     # R1
    "Previous Weapon": 18,          # L2
    "Next Weapon": 17,              # R2
    "Move Forward": 11,             # D-pad up
    "Move Backward": 12,            # D-pad down
    "Strafe Left": 13,              # D-pad left
    "Strafe Right": 14,             # D-pad right
}
# The First Encounter has no bomb: Y flips the weapon there
BUTTONS_TFE = {
    "Flip Weapon": 3,               # Y
}

# The GO Advance (SSAM_LAYOUT=oga: oga.manifest's env): one stick. The
# stick looks (turn, look up/down), the D-pad walks; the buttons as the GO
# Ultra's (and RTCW's on the GO Advance)
AXES_OGA = {
    "move f/b": ("None", 50, 0, False),
    "move l/r": ("None", 50, 0, False),
    "turn l/r": ("Joy 1 Axis X", 60, 15, False),
    "look u/d": ("Joy 1 Axis Y", 56, 15, True),
}

# axis -> (control, sensitivity, dead zone %, inverted). A stick's turn
# (serious-engine 0009): 60 * 2^((sensitivity - 50) / 5) degrees a second
# at full deflection, the reading squared: 60 is 240 degrees a second, 56
# 138, as DOOM 3 BFG's joy_yawSpeed 240 and joy_pitchSpeed 130
AXES = {
    "move f/b": ("Joy 1 Axis Y", 100, 20, True),
    # the engine moves right on a negative "move l/r" (Game.cpp
    # CreateAction): the stick's X inverted
    "move l/r": ("Joy 1 Axis X", 100, 20, True),
    "turn l/r": ("Joy 1 Axis Z", 60, 15, False),
    "look u/d": ("Joy 1 Axis R", 56, 15, True),
    # the mouse (bare_app's motion sensor too) on the view's axes: the
    # player's turn adds them, and aim assist slows only the stick's
    "view l/r": ("mouse X", 50, 0, False),
    "view u/d": ("mouse Y", 50, 0, False),
}


def main():
    path = sys.argv[1].rstrip("/") + "/Controls/00-Default.ctl"
    with open(path, "rb") as f:
        text = f.read().decode("latin-1")
    lines = text.split("\r\n")
    names = [l.strip()[len("Name: TTRS "):] for l in lines if l.strip().startswith("Name: TTRS ")]
    oga = os.environ.get("SSAM_LAYOUT") == "oga"
    buttons = dict(BUTTONS)
    if "Serious Bomb" not in names:
        buttons.update(BUTTONS_TFE)
    axes = dict(AXES)
    if oga:
        axes.update(AXES_OGA)
    done, out, name = set(), [], None
    for line in lines:
        s = line.strip()
        if s.startswith("Name: TTRS "):
            name = s[len("Name: TTRS "):]
        elif s.startswith("Key2:") and name in buttons and name not in done:
            line = " Key2: Joy 1 Button %d" % buttons[name]
            done.add(name)
        m = re.match(r'Axis "([^"]+)" "[^"]*" \d+ \d+ (\w+) (\w+) (\w+)$', s)
        if m and m.group(1) in axes:
            control, sens, dead, inv = axes[m.group(1)]
            line = 'Axis "%s" "%s" %d %d %s Relative NotSmooth' % (
                m.group(1), control, sens, dead, "Inverted" if inv else "NotInverted")
            done.add(m.group(1))
        out.append(line)
    missing = [n for n in buttons if n not in done and n in names] + [a for a in axes if a not in done]
    if missing:
        sys.exit("controls.py: %s: not set: %s" % (path, ", ".join(missing)))
    with open(path, "wb") as f:
        f.write("\r\n".join(out).encode("latin-1"))


if __name__ == "__main__":
    main()
