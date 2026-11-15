# Neighbours from Hell 1: its interface in the top 480 rows of its 800x600
# screen (bare_app_wine rows = 480). Rows cut from the 600-high pictures,
# dialogs moved; y values are the 800x600 ones. See prepare.sh.
HUD = -120
SHIFTS = {f'dialogs/{n}.xml': HUD for n in
          ('menu', 'menucentertop', 'menuleft', 'menuleft_bar', 'menuright', 'menu_bubble')}
CUTS = {
    # episode book, left page: the header, empty rows at the boxes' bottoms,
    # the gap above the cancel bar, the bottom margin
    'gui/main/newgameleft.tga': [(0, 40), (142, 150), (303, 311), (402, 410), (511, 517), (550, 600)],
    # right page: the header and empty briefing rows
    'gui/main/newgameright.tga': [(0, 40), (400, 440), (550, 590)],
}
EDITS = [
    ('dialogs/newgameleft.xml', 'name="newgamecaption" offset="75/0"', 'name="newgamecaption" offset="75/-200"'),
]
EDITS += [
    ('dialogs/newgameright.xml', 'name="newgamerightcaption" offset="0/0"', 'name="newgamerightcaption" offset="0/-200"'),
    ('dialogs/mmwhilegameright.xml', 'name="newgamerightcaption" offset="0/0"', 'name="newgamerightcaption" offset="0/-200"'),
    # the X button up over the cancel bar's end (it hung below the page)
    ('dialogs/newgameleft.xml', 'name="cancel" offset="25/530"', 'name="cancel" offset="25/490"'),
]
CINEMA = [(0, 40), (520, 600)]		# the curtain's top, the seats
ENDSCREEN = [(0, 50), (530, 600)]	# the black bars (and the trophy's foot)
CUTS.update({
    'gui/main/splasher0.tga': CINEMA,
    'gui/main/splasher1.tga': CINEMA,
    'gui/main/credits.tga': CINEMA,
    'gui/main/splasher.tga': [(0, 105), (585, 600)],
    'gui/main/endscreen_gold.tga': ENDSCREEN,
    'gui/main/endscreen_silver.tga': ENDSCREEN,
    'gui/main/endscreen_bronze.tga': ENDSCREEN,
    'gui/main/endscreen_default.tga': ENDSCREEN,
    # main menu: between the two busts and the houses, the ground
    'gui/main/mainmenu.tga': [(190, 230), (520, 600)],
    # options: the sky above the TV, the floor
    'gui/main/optionsback.tga': [(0, 30), (175, 205), (540, 600)],
    # in-game menu, left page: the header, parchment under the buttons
    'gui/main/ingamemenu_left.tga': [(0, 40), (450, 515), (585, 600)],
})
EDITS += [
    # the version line from the cut ground up to the screen's bottom
    ('dialogs/mainmenu.xml', 'name="version" offset="10/570"', 'name="version" offset="10/495"'),
    ('dialogs/splasher.xml', 'name="version" offset="10/570"', 'name="version" offset="10/495"'),
    ('dialogs/options.xml', 'name="statusbar" offset="0/540"', 'name="statusbar" offset="0/494"'),
]
EDITS += [
    # the briefing as much shorter as the rows cut from it
    ('dialogs/newgameright.xml', 'name="briefing" offset="28/287" size="343/178"', 'name="briefing" offset="28/287" size="343/138"'),
    ('dialogs/mmwhilegameright.xml', 'name="briefing" offset="28/287" size="343/178"', 'name="briefing" offset="28/287" size="343/138"'),
    # the start/continue arrow up into the page (it hung below it)
    ('dialogs/newgameright.xml', 'name="start" offset="320/530"', 'name="start" offset="320/506"'),
    ('dialogs/mmwhilegameright.xml', 'name="continue" offset="320/530"', 'name="continue" offset="320/506"'),
]
# The options' speakers (frames over the picture's speakers) are drawn
# without clipping: 319 high at y 281 they ended at 600. Moved up 60 by the
# cuts above them, their feet (the rows cut from the picture too) go.
CUTS.update({
    'gui/main/box_links.tga': [(259, 319)],
    'gui/main/box_rechts.tga': [(259, 319)],
})
EDITS += [
    # "back to the game" / "play" above the arrow button moved up with it
    ('dialogs/newgameright.xml', 'name="play" offset="269/475"', 'name="play" offset="269/465"'),
    ('dialogs/mmwhilegameright.xml', 'name="continuetext" offset="269/475"', 'name="continuetext" offset="269/465"'),
]
# The loading screen's picture is drawn whole by the code: 480 rows of it
# (its progress bar moved up 60 in GFXEngine.dll, see gfxsize.py)
CUTS['loading.tga'] = [(0, 60), (540, 600)]
# The victory text boxes reached y 720: ending at the screen's bottom now
for d, x in (('victorydlg', 513), ('victory_bronze_dlg', 463), ('victory_gold_dlg', 463), ('victory_silver_dlg', 463)):
    w = 250 if d == 'victorydlg' else 300
    EDITS += [(f'dialogs/{d}.xml', f'name="victory2shadow" offset="{x}/172" size="{w}/550"', f'name="victory2shadow" offset="{x}/172" size="{w}/350"'),
              (f'dialogs/{d}.xml', f'name="victory2" offset="{x - 3}/170" size="{w}/550"', f'name="victory2" offset="{x - 3}/170" size="{w}/350"')]
