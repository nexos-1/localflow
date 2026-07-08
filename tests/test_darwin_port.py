"""Windows-lauffaehige Pruefungen des macOS-Backends: Syntax aller Module,
reine Logik (plist, Keymaps, Combo-Uebersetzung) und Protocol-Flaeche.
Die Hardware-abhaengigen Teile (CGEvent, NSPasteboard, pynput-Listener)
prueft die CI auf einem echten macOS-Runner (.github/workflows/ci.yml)."""

import os
import plistlib
import py_compile
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = os.path.join(os.path.dirname(__file__), "..", "localflow", "platform", "darwin")

# 1) Alle darwin-Module sind syntaktisch valide
for fn in sorted(os.listdir(ROOT)):
    if fn.endswith(".py"):
        py_compile.compile(os.path.join(ROOT, fn), doraise=True)
print("Syntax aller darwin-Module OK")

# 2) plist-Erzeugung (pure Funktion)
from localflow.platform.darwin.autostart import LABEL, build_launch_agent  # noqa: E402

data = plistlib.loads(build_launch_agent("/usr/bin/python3", "/tmp/run.py"))
assert data["Label"] == LABEL
assert data["ProgramArguments"] == ["/usr/bin/python3", "/tmp/run.py"]
assert data["RunAtLoad"] is True
print("LaunchAgent-plist OK")

# 3) Carbon-Keymap deckt ALLE Sprachbefehl-Tasten ab
from localflow.commands import VALID_KEYS  # noqa: E402
from localflow.platform.darwin.inject import _COMMAND_VK  # noqa: E402

assert set(_COMMAND_VK) == set(VALID_KEYS), (set(_COMMAND_VK), set(VALID_KEYS))
assert len(set(_COMMAND_VK.values())) == len(_COMMAND_VK)  # keine doppelten Codes
print("Carbon-Keymap deckt VALID_KEYS OK")

# 4) Combo-Uebersetzung fuer den Toggle-Hotkey (win -> cmd)
from localflow.platform.darwin.hotkey import (_MOUSE_VALUE_TO_CANON,  # noqa: E402
                                              _PYNPUT_TO_CANON, to_pynput_combo)

assert to_pynput_combo("ctrl+alt+space") == "<ctrl>+<alt>+<space>"
assert to_pynput_combo("ctrl+win") == "<ctrl>+<cmd>"
assert to_pynput_combo("win+ctrl") == "<ctrl>+<cmd>"  # kanonische Reihenfolge
try:
    to_pynput_combo("ctrl+maus5")
    raise AssertionError("Maus-Taste als Toggle haette scheitern muessen")
except ValueError:
    pass
print("Toggle-Combo-Uebersetzung OK")

# 5) Tasten-/Maus-Mappings sind konsistent mit den kanonischen Tokens
from localflow.controller import KEY_ALIASES, MOUSE_PARTS  # noqa: E402

assert set(_PYNPUT_TO_CANON.values()) <= set(KEY_ALIASES)
assert set(_MOUSE_VALUE_TO_CANON.values()) == MOUSE_PARTS
print("Mapping-Konsistenz OK")

# 6) Backend-Flaeche: darwin liefert dieselben Attribute wie win32
#    (make_backends selbst braucht pyobjc erst zur LAUFZEIT der Funktionen,
#    aber die Modul-Importe muessen ueberall funktionieren).
import localflow.platform.darwin as dw  # noqa: E402
import inspect  # noqa: E402

src = inspect.getsource(dw.make_backends)
for attr in ("make_ptt", "add_hotkey", "remove_hotkey", "capture_combo",
             "inject", "make_ducker", "make_overlay", "sounds",
             "autostart", "integration"):
    assert attr + "=" in src.replace(" ", ""), f"Backend-Attribut fehlt: {attr}"
print("Backend-Flaeche vollstaendig OK")

# 7) No-op-Vertraege: Ducker deaktiviert Head-Trim, Overlay ist API-komplett
from localflow.platform.darwin.ducking import NoopDucker  # noqa: E402
from localflow.platform.darwin.overlay import NullOverlay  # noqa: E402

d = NoopDucker(duck_volume=0.5)
assert d.did_mute_sessions == 0 and d.duck_volume == 0.5
d.duck(); d.restore()
o = NullOverlay()
for m in ("start", "set_state", "set_level", "set_text", "set_glass", "set_style"):
    assert callable(getattr(o, m)), m
o.set_state("recording"); o.set_level(0.5); o.set_text("x")
o.set_glass(True); o.set_style("Arial", 12)
print("No-op-Vertraege OK")

print("\nDARWIN PORT TESTS PASSED")
