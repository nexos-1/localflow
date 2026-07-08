"""Zweiter Diktat-Hotkey: zwei PushToTalk-Instanzen am SELBEN Controller
loesen beide gleichwertig aus. Ohne echte OS-Hooks - _apply() direkt
gefuettert (so wie es der Worker-Loop nach einem Hook-Event taete)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.hotkey import DictationController, PushToTalk, _MouseHook, normalize_combo


class Probe:
    def __init__(self):
        self.events = []
    def start(self): self.events.append("start")
    def stop(self): self.events.append("stop")
    def cancel(self): self.events.append("cancel")
    def lock(self): self.events.append("lock")


def press(ptt, *parts):
    for p in parts:
        ptt._apply(p, True)
    for p in reversed(parts):
        ptt._apply(p, False)


# Ein Controller (hold-Modus: druecken=start, loslassen=stop), zwei Hooks.
p = Probe()
ctrl = DictationController(p.start, p.stop, p.cancel, p.lock, mode="hold")
ptt_primary = PushToTalk("maus5", ctrl)
ptt_second = PushToTalk("ctrl+win", ctrl)

# 1) Primaerer Hotkey loest aus
press(ptt_primary, "maus5")
assert p.events == ["start", "stop"], p.events

# 2) Zweiter Hotkey loest gleichwertig aus
p.events.clear()
press(ptt_second, "ctrl", "win")
assert p.events == ["start", "stop"], p.events
print("Beide Hotkeys loesen einzeln aus OK")

# 3) Teil-Kombi des zweiten Hotkeys allein tut NICHTS (nur ctrl ohne win)
p.events.clear()
ptt_second._apply("ctrl", True)
ptt_second._apply("ctrl", False)
assert p.events == [], p.events
print("Teilkombination loest nicht aus OK")

# 4) main._install_hotkey-Regel: identische Primaer/Zweit-Kombi -> kein
#    zweiter Hook (waere Doppelmeldung).
assert normalize_combo("win+ctrl") == normalize_combo("ctrl+win")
assert normalize_combo("ctrl+win") != normalize_combo("maus5")
print("Dedupe-Regel (normalize_combo) OK")

# 5) Sequenziell abwechselnd nutzen bleibt sauber
p.events.clear()
press(ptt_primary, "maus5")
press(ptt_second, "ctrl", "win")
press(ptt_primary, "maus5")
assert p.events == ["start", "stop"] * 3, p.events
print("Abwechselnde Nutzung sauber OK")

# 6) REGRESSION: Waehrend Hotkey A HAELT, wird B gedrueckt und losgelassen -
#    das darf die laufende Aufnahme weder stoppen noch verwerfen (frueher
#    mass combo_up die Haltezeit des falschen Drucks -> Stop/Cancel).
p.events.clear()
ptt_primary._apply("maus5", True)      # A haelt: Aufnahme laeuft
ptt_second._apply("ctrl", True)
ptt_second._apply("win", True)         # B komplett gedrueckt (down ist no-op)
ptt_second._apply("win", False)        # B losgelassen -> darf NICHT stoppen
ptt_second._apply("ctrl", False)
assert p.events == ["start"], p.events
ptt_primary._apply("maus5", False)     # A loslassen -> normales Stop
assert p.events == ["start", "stop"], p.events
print("Fremder Hotkey-Release stoppt gehaltene Aufnahme nicht OK")

# 7) Swallow-Verdrahtung: swallow_mouse fliesst bis in den Maus-Hook durch.
#    (Der eigentliche "Event verschlucken"-Zweig ist `if self.suppress:
#    return 1` im WH_MOUSE_LL-Callback - OS-Ebene, hier nicht ausfuehrbar;
#    getestet wird, dass die Einstellung korrekt ankommt.)
mh_on = _MouseHook({"maus5"}, lambda n, d: None, suppress=True)
mh_off = _MouseHook({"maus5"}, lambda n, d: None, suppress=False)
assert mh_on.suppress is True and mh_off.suppress is False
ptt_sw = PushToTalk("maus5", ctrl, swallow_mouse=True)
assert ptt_sw.swallow_mouse is True and ptt_sw.mouse_parts == ["maus5"]
ptt_ns = PushToTalk("maus5", ctrl, swallow_mouse=False)
assert ptt_ns.swallow_mouse is False
# Reiner Tastatur-Hotkey hat keine Maus-Teile -> swallow ist wirkungslos.
ptt_kb = PushToTalk("ctrl+win", ctrl, swallow_mouse=True)
assert ptt_kb.mouse_parts == [] and ptt_kb.kb_parts == ["ctrl", "win"]
print("Swallow-Verdrahtung (Maus verschluckt) OK")

print("\nSECOND HOTKEY TESTS PASSED")
