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
BUTTONS = {
    "Fire": 17,                     # R2
    "Use/Sniper Zoom": 18,          # L2 (The Second Encounter)
    "Use": 18,                      # L2 (The First Encounter)
    "Up/Jump": 0,                   # A
    "Down/Duck": 1,                 # B
    "Flip Weapon": 2,               # X
    "Invoke NETRICSA": 3,           # Y
    "Previous Weapon": 9,           # L1
    "Next Weapon": 10,              # R1
    "Serious Bomb": 11,             # D-pad up (The Second Encounter)
    "3rd Person View": 12,          # D-pad down
    "Sniper Zoom -": 13,            # D-pad left (The Second Encounter)
    "Sniper Zoom +": 14,            # D-pad right
}
# The First Encounter has no bomb nor sniper: other weapons there
BUTTONS_TFE = {
    "Cannon": 11,                   # D-pad up
    "Knife": 13,                    # D-pad left
    "Tommygun/Minigun": 14,         # D-pad right
}

# The GO Advance (SSAM_LAYOUT=oga: oga.manifest's env): one stick. The
# stick looks (turn, look up/down), the D-pad walks; the bomb, the
# third-person view and the sniper's zoom have no button there
BUTTONS_OGA = {
    "Move Forward": 11,             # D-pad up
    "Move Backward": 12,            # D-pad down
    "Strafe Left": 13,              # D-pad left
    "Strafe Right": 14,             # D-pad right
}
DPAD_ACTIONS = ("Serious Bomb", "3rd Person View", "Sniper Zoom -", "Sniper Zoom +",
                "Cannon", "Knife", "Tommygun/Minigun")
AXES_OGA = {
    "move f/b": ("None", 50, 0, False),
    "move l/r": ("None", 50, 0, False),
    "turn l/r": ("Joy 1 Axis X", 45, 15, False),
    "look u/d": ("Joy 1 Axis Y", 40, 15, True),
}

# axis -> (control, sensitivity, dead zone %, inverted)
AXES = {
    "move f/b": ("Joy 1 Axis Y", 100, 20, True),
    "move l/r": ("Joy 1 Axis X", 100, 20, False),
    "turn l/r": ("Joy 1 Axis Z", 45, 15, False),
    "look u/d": ("Joy 1 Axis R", 40, 15, True),
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
    buttons = dict(BUTTONS)
    if "Serious Bomb" not in names:
        buttons.update(BUTTONS_TFE)
    axes = dict(AXES)
    if os.environ.get("SSAM_LAYOUT") == "oga":
        for n in DPAD_ACTIONS:
            buttons.pop(n, None)
        buttons.update(BUTTONS_OGA)
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
