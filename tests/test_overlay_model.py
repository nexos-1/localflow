"""Unit-Tests des plattformneutralen Pillen-Kerns (overlay_model.py):
Feder-Engine (Spring), Tween-Stetigkeit, Farb-Mix und Text-Layout.
Reine Mathematik, laeuft auf jedem OS ohne Tk/AppKit."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.overlay_model import (  # noqa: E402
    ARC_TAP, RING_BOUNCE, SPRING_SHOW, WAVE_STATES, Spring, Tween, check_path,
    ease_in_out, fit_text_tail, mix, wrap_text,
)


def run(spring, seconds, dt=1 / 60):
    """Feder fuer `seconds` mit festem Takt integrieren, Verlauf zurueckgeben."""
    trace = []
    for _ in range(int(round(seconds / dt))):
        trace.append(spring.update(dt))
    return trace


# --- 1) Kritisch gedaempft: erreicht das Ziel, schwingt nie ueber ---------
s = Spring(0.0, *SPRING_SHOW)
s.to(1.0)
tr = run(s, 1.0)
assert max(tr) <= 1.0 + 1e-9, f"Ueberschwingen bei damping 1.0: {max(tr)}"
assert all(b >= a - 1e-9 for a, b in zip(tr, tr[1:])), "nicht monoton"
assert s.settled and s.v == 1.0, (s.v, s.vel)
# Settle-Zeit in der Groessenordnung der Response (kritisch gedaempft: ~2-3x)
t90 = next(i for i, v in enumerate(tr) if v >= 0.9) / 60
assert 0.15 < t90 < 0.6, f"90 % nach {t90:.2f}s"
print(f"Spring kritisch gedaempft OK (90 % nach {t90*1000:.0f} ms)")

# --- 2) Unterdaempft (Lock-Ring): schwingt sichtbar ueber und beruhigt sich
s = Spring(0.0, 0.30, RING_BOUNCE)
s.to(1.0)
tr = run(s, 1.5)
assert max(tr) > 1.03, f"kein Ueberschwingen bei damping {RING_BOUNCE}: {max(tr)}"
assert max(tr) < 1.25, f"zu viel Ueberschwingen: {max(tr)}"
assert s.settled and s.v == 1.0
print(f"Spring unterdaempft OK (Peak {max(tr):.3f})")

# --- 3) Unterbrechung: Zielwechsel mitten im Lauf behaelt Geschwindigkeit
s = Spring(0.0, *SPRING_SHOW)
s.to(1.0)
run(s, 0.08)                       # mitten im Anlauf ...
v_before, vel_before = s.v, s.vel
assert vel_before > 0.5, vel_before
s.to(0.0)                          # ... umkehren (Hide unterbricht Show)
assert s.v == v_before and s.vel == vel_before, "Zielwechsel darf nichts springen"
tr = run(s, 0.5)
# Erst laeuft die Feder wegen der Restgeschwindigkeit noch WEITER nach oben,
# dann kehrt sie um - genau das ist die "kein Brick-Wall"-Eigenschaft.
assert tr[0] > v_before, "Restgeschwindigkeit wurde verworfen"
assert abs(tr[-1]) < 1e-3 and s.settled
step = max(abs(b - a) for a, b in zip(tr, tr[1:]))
assert step < 0.08, f"Sprung pro Frame zu gross: {step}"
print("Spring Unterbrechung stetig OK")

# --- 4) Stabil bei grossem dt (Standby/Ruckler): kein Explodieren -------
s = Spring(0.0, 0.22, 1.0)
s.to(1.0)
for _ in range(20):
    s.update(0.1)
assert s.settled and s.v == 1.0, (s.v, s.vel)
s2 = Spring(0.0, 0.22, 1.0)
s2.to(1.0)
s2.update(0.1)
assert 0.0 < s2.v <= 1.0, s2.v
print("Spring dt=0.1 stabil OK")

# --- 5) Geschwindigkeitsuebergabe + snap ----------------------------------
s = Spring(0.0, 0.3, 1.0)
s.to(1.0, velocity=4.0)
assert s.vel == 4.0
first = s.update(1 / 60)
assert first > 0.05, first          # Uebergabe wirkt sofort
s.snap(0.5)
assert s.settled and s.v == 0.5 and s.update(0.05) == 0.5
assert s.update(0.0) == 0.5
print("Spring Velocity/Snap OK")

# --- 6) Tween: neues Ziel startet stetig vom aktuellen Wert ---------------
t = Tween(0.0, ease_in_out)
t.to(1.0, 0.2, 0.0)
t.update(0.1)
mid = t.v
t.to(0.0, 0.2, 0.1)
assert t.update(0.1) == mid
assert abs(t.update(0.3)) < 1e-9
print("Tween Stetigkeit OK")

# --- 7) Farb-Mix und Text-Helfer ------------------------------------------
assert mix("#000000", "#ffffff", 0.0) == "#000000"
assert mix("#000000", "#ffffff", 1.0) == "#ffffff"
assert mix("#000000", "#ffffff", 0.5) == "#808080"
assert mix("#000000", "#ffffff", 2.0) == "#ffffff"   # geclampt
measure = lambda s: 6.0 * len(s)  # noqa: E731 - fixe Monospace-Breite
assert fit_text_tail("hallo welt", 100, measure) == "hallo welt"
tail = fit_text_tail("a" * 40, 60, measure)
assert tail.startswith("… ") and measure(tail) <= 60, tail
lines = wrap_text("eins zwei drei vier", 60, measure)
assert lines == ["eins zwei", "drei vier"], lines
assert wrap_text("", 60, measure) == [""]
assert wrap_text("x" * 30, 60, measure) == ["x" * 30]  # zu langes Wort bleibt ganz
print("mix/fit_text_tail/wrap_text OK")

assert math.isclose(Spring(0.0, 0.3, 1.0).k, (2 * math.pi / 0.3) ** 2)

# --- 8) Haken-Pfad: waechst monoton, endet auf dem vollen Haken ----------
assert check_path(100, 50, 0.0) == []
half = check_path(100, 50, 0.3)
assert len(half) == 4 and half[:2] == [94.0, 50.5], half
full = check_path(100, 50, 1.0)
assert len(full) == 6 and full[4:] == [107.0, 45.0], full
lengths = [len(check_path(100, 50, p)) for p in (0.1, 0.3, 0.6, 0.9)]
assert lengths == [4, 4, 6, 6], lengths
assert "armed" in WAVE_STATES and 0.0 < ARC_TAP < 1.0
print("check_path/armed OK")
print("\nOVERLAY MODEL TESTS PASSED")
