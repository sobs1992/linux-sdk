# Neighbours from Hell 2: On Vacation, its interface in the top 480 rows of
# its 800x600 screen (bare_app_wine rows = 480). y values are the 800x600
# ones. See ../neighbours/prepare.sh.
HUD = -120
SHIFTS = {f'dialogs/{n}.xml': HUD for n in
          ('bubble_mother', 'bubble_neighbor', 'tutorial',
           'mother/menu', 'mother/menucentertop', 'mother/menuleft', 'mother/menuright',
           'nomother/menu', 'nomother/menucentertop', 'nomother/menuleft', 'nomother/menuright')}
CINEMA = [(0, 40), (520, 600)]		# the curtain's top, the seats

CUTS = {
    'gui/main/credits.tga': CINEMA,
    'gui/main/splasher0.tga': CINEMA,
    'gui/main/splasher1.tga': CINEMA,
    'loading.tga': [(0, 60), (540, 600)],
    # main menu: sun rays, the silhouettes' middle, the ground
    'gui/main/mainmenu.tga': [(0, 20), (245, 285), (540, 600)],
    # options: as the first game's
    'gui/main/optionsback.tga': [(0, 30), (175, 205), (540, 600)],
    'gui/main/box_links.tga': [(259, 319)],
    'gui/main/box_rechts.tga': [(259, 319)],
    # the level panel right of the map, in the book and the in-game menu
    'gui/main/newgameright.tga': [(0, 75), (330, 370)],
    'gui/main/ingameright.tga': [(0, 75), (330, 370)],
    # the in-game menu's blurred map below its buttons
    'gui/main/ingameleft.tga': [(450, 570)],
    # the rage meter down the left: above the bottom panel moved up 120
    'gui/ingame2/thermo_back.tga': [(180, 300)],
    'gui/ingame2/thermo_empty.tga': [(180, 300)],
    'gui/ingame2/thermo_full.tga': [(180, 300)],
}
# the episode map: level buttons all over it, so squeezed rather than cut
SCALES = {'gui/main/newgameleft.tga': 480}
EDITS = [
    ('dialogs/mainmenu.xml', 'name="version" offset="10/570"', 'name="version" offset="10/515"'),
    ('dialogs/splasher.xml', 'name="version" offset="5/570"', 'name="version" offset="5/495"'),
    ('dialogs/options.xml', 'name="statusbar" offset="0/540"', 'name="statusbar" offset="0/494"'),
    ('dialogs/mother/menuleft_bar.xml', '<dialog offset="0/0" size="26/473">', '<dialog offset="0/0" size="26/353">'),
    ('dialogs/nomother/menuleft_bar.xml', '<dialog offset="0/0" size="26/473">', '<dialog offset="0/0" size="26/353">'),
]
for d in ('newgameright', 'mmwhilegameright'):
    EDITS += [(f'dialogs/{d}.xml', 'name="briefing" offset="10/262" size="230/220"', 'name="briefing" offset="10/262" size="230/180"'),
              (f'dialogs/{d}.xml', 'name="needmorecoins" offset="7/265" size="234/220"', 'name="needmorecoins" offset="7/265" size="234/180"')]
# the lowest level button of the squeezed map up a little (it ended at 489)
EDITS += [('dialogs/newgameleft.xml', 'name="me_c1" offset="173/504"', 'name="me_c1" offset="173/490"')]
# the briefing 50 rows shorter: its text one font size smaller (13 at 1:1 is
# still bigger than the 15 taken down to 12 before), "need more coins" too
for d in ('newgameright', 'mmwhilegameright'):
    EDITS += [(f'dialogs/{d}.xml', 'size="230/180" valign="top" halign="left" color="0/0/0">\r\n\t\t<font name="briefing_small"/>',
               'size="230/180" valign="top" halign="left" color="0/0/0">\r\n\t\t<font name="briefing_quitesmall"/>'),
              (f'dialogs/{d}.xml', 'size="234/180" valign="top" halign="left" color="0/0/0">\r\n\t\t<font name="briefing_normal"/>',
               'size="234/180" valign="top" halign="left" color="0/0/0">\r\n\t\t<font name="briefing_small"/>')]
