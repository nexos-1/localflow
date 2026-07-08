"""Unit-Tests der Diktat-Zustandsmaschine (ohne Tastatur-Hook)."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.controller import DictationController, normalize_combo


class Probe:
    def __init__(self):
        self.events = []
    def start(self): self.events.append("start")
    def stop(self): self.events.append("stop")
    def cancel(self): self.events.append("cancel")
    def lock(self): self.events.append("lock")


def make(mode, clock):
    p = Probe()
    c = DictationController(p.start, p.stop, p.cancel, p.lock, mode=mode,
                            tap_max_s=0.35, double_tap_window_s=0.4, clock=clock)
    return p, c


# --- Modus "hold"/"both": normales Halten ---
t = [0.0]
clock = lambda: t[0]
p, c = make("both", clock)
c.combo_down(); t[0] += 2.0; c.combo_up()
assert p.events == ["start", "stop"], p.events
assert c.state == "idle"
print("Halten OK:", p.events)

# --- Doppeltipp -> Freisprechen -> Druck stoppt ---
t = [0.0]; p, c = make("both", lambda: t[0])
c.combo_down(); t[0] += 0.1; c.combo_up()          # Tipp 1 (kurz) -> ARMED
assert c.state == "armed" and p.events == ["start"]
t[0] += 0.2; c.combo_down()                          # Tipp 2 -> LOCKED
assert c.state == "locked" and p.events == ["start", "lock"]
t[0] += 0.05; c.combo_up()                           # Loslassen von Tipp 2: ignoriert
assert c.state == "locked"
t[0] += 5.0; c.combo_down()                          # dritter Druck stoppt
assert p.events == ["start", "lock", "stop"], p.events
c.combo_up()
assert c.state == "idle"
print("Doppeltipp-Freisprechen OK:", p.events)

# --- Einzeltipp ohne zweiten Tipp -> cancel (kein Fehl-Paste) ---
t = [0.0]; p, c = make("both", lambda: t[0])
c.combo_down(); t[0] += 0.1; c.combo_up()
time.sleep(0.55)  # Timer (0.4s) ablaufen lassen
assert p.events == ["start", "cancel"], p.events
assert c.state == "idle"
print("Einzeltipp-Cancel OK:", p.events)

# --- Modus "hold": kurzer Tipp stoppt sofort (kein ARMED) ---
t = [0.0]; p, c = make("hold", lambda: t[0])
c.combo_down(); t[0] += 0.1; c.combo_up()
assert p.events == ["start", "stop"] and c.state == "idle"
print("Hold-Modus OK:", p.events)

# --- Modus "toggle": Druecken startet, naechstes Druecken stoppt ---
t = [0.0]; p, c = make("toggle", lambda: t[0])
c.combo_down(); c.combo_up()
assert c.state == "locked" and p.events == ["start"]
t[0] += 3.0; c.combo_down(); c.combo_up()
assert c.state == "idle" and p.events == ["start", "stop"]
print("Toggle-Modus OK:", p.events)

# --- normalize_combo ---
assert normalize_combo("ctrl+windows") == "ctrl+win"
assert normalize_combo("Strg+Leertaste") == "ctrl+space"
assert normalize_combo("left windows+alt gr") == "alt+win"      # Modifier-Sortierung
assert normalize_combo("alt+space+ctrl") == "ctrl+alt+space"    # Capture-Reihenfolge egal
assert normalize_combo("Maus5") == "maus5"                       # Maus-Seitentaste solo
assert normalize_combo("xbutton2") == "maus5"
assert normalize_combo("mouse4+ctrl") == "ctrl+maus4"            # gemischt Tastatur+Maus
print("normalize_combo OK")

print("\nDICTATION MODE TESTS PASSED")
