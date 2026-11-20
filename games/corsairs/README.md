# Корсары: Пираты Карибского моря (Pirates of the Caribbean)

Akella's Storm engine game (2003, Direct3D 8, WMV videos through
DirectShow), the fan-patched Russian-English edition ("100% dialogues
translated", no CD check), under Wine on the GO Ultra (manifest
`[corsairs]`, wine.ini in `overlay/`).

prepare.sh (games-image.py runs it after the copy):

- the Russian voices, loading screens, world map pictures and videos over
  the English ones, as the edition's `sound_video_on.bat` does on Windows
  (the copy had never had it run: no voices at all);
- the full sea: removes the Intel Fix's second Radeon8500Sea technique
  (`MODULES/Techniques/Weather/RadeonSea.sha`, GeForce 3 pixel shader). The
  ATI one draws the reflections; the frame rate is the same (~50 fps in
  the port: the game's main thread under Box64 is the limit, ~98% of a
  core, wined3d_cs ~56%);
- the gamepad's controls in the game's `options` (its own settings file,
  copied to /data on the first start): the left stick W A S D for walking,
  the sails and the helm (the edition's options walked with the mouse
  buttons), A Space (act, strike, broadside); see wine.ini [keys].

Notes:

- The game reads the mouse by DirectInput: `mouse = relative`.
- system.log shows "BeginScene: The method call is invalid" at every
  start (also on Windows); harmless.
- In the game's screens A (Space) highlights a button, X (Enter) presses
  it; the main menu's highlight wraps around and skips disabled entries.
- F1 is the game's main menu (its own F1; Esc, B, opens it too), as in
  every game of the SDK. F4 is the game's F2: the menu of its screens
  (character, ship, hold, passengers, journal, trade book, nations, items:
  the inventory), moved through by the D-pad (not in a fight nor on the
  world map: the game's rule).
- Saved games in SAVE/, settings in options, both in the writable copy
  (/data/wine/games/corsairs).
- The GO Ultra unit with the older Wine build (unit 1 before its update)
  crashed in wined3d after the main menu; the current build runs it.
