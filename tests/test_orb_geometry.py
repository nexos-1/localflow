"""Golden-Vektor-Test des Thinking-Orb-Ports (overlay_model.frame_orbits /
frame_wave + Preset-Skalierung) gegen die Originalbibliothek thinking-orbs.

tests/golden/orbs-golden-subset.json ist der Auszug (working + listening, beide
Groessen, vier Zeitpunkte) aus spec/orbs-golden.json der Bibliothek: exakt
die Geometrie, die die TypeScript-Engine erzeugt. Stimmt jeder Punkt in
Position, Radius, Tinte und Alpha innerhalb der Toleranz ueberein, ist der
Port nicht "aehnlich", sondern identisch."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.overlay_model import (  # noqa: E402
    ORB_SIZE, orb_dots, resolve_orb,
)

path = os.path.join(os.path.dirname(__file__), "golden", "orbs-golden-subset.json")
with open(path, encoding="utf-8") as f:
    golden = json.load(f)
tol = float(golden["tolerance"]) + 1e-6   # + Rundung auf 6 Stellen im Golden
print(f"Golden: {golden['sourceLibrary']['name']} {golden['sourceLibrary']['version']}, "
      f"{len(golden['cases'])} Faelle, Toleranz {tol:g}")

# 1) Preset-Aufloesung (count-/size-Skalierung) identisch
for key, exp in golden["resolved"].items():
    state, size = key.split("-")
    frame, speed, opts = resolve_orb(state, int(size))
    assert abs(speed - exp["speed"]) < 1e-9, (key, speed, exp["speed"])
    for k, v in exp["opts"].items():
        assert k in opts, (key, k)
        assert abs(opts[k] - v) < 1e-9, (key, k, opts[k], v)
print("Preset-Skalierung identisch OK")

# 2) Jeder Punkt jedes Frames innerhalb der Toleranz, gleiche Zeichenreihenfolge
worst = 0.0
for case in golden["cases"]:
    frame, speed, opts = resolve_orb(case["state"], case["size"])
    dots = frame(case["size"], case["t"], opts)
    assert len(dots) == case["dotCount"], (case["key"], len(dots), case["dotCount"])
    flat = case["dots"]
    for i, d in enumerate(dots):
        for j in range(6):
            diff = abs(d[j] - flat[i * 6 + j])
            worst = max(worst, diff)
            assert diff <= tol, (case["key"], i, j, d[j], flat[i * 6 + j])
print(f"{len(golden['cases'])} Golden-Frames identisch OK (max. Abweichung {worst:.2e})")

# 3) Painter-Sicht: orb_dots liefert Orb-Raum 0..ORB_SIZE, grow skaliert um die Mitte
full = orb_dots("working", 1.7, ORB_SIZE, 1.0)
assert full and all(0 <= x <= ORB_SIZE and 0 <= y <= ORB_SIZE for x, y, *_ in full), full[:3]
half = orb_dots("working", 1.7, ORB_SIZE, 0.5)
c = ORB_SIZE / 2
for (x1, y1, r1, *_), (x2, y2, r2, *_) in zip(full, half):
    assert abs((x2 - c) - (x1 - c) * 0.5) < 1e-9 and abs((y2 - c) - (y1 - c) * 0.5) < 1e-9
    assert abs(r2 - r1 * 0.5) < 1e-9
assert len(orb_dots("working", 1.7, ORB_SIZE, 1.0, min_r=99.0)) == 0  # min_r-Filter greift
print("orb_dots (Painter-Sicht) OK")

# 4) Budget: ein Frame des 20-px-Presets ist billig (laeuft 60x pro Sekunde in Tk)
t0 = time.perf_counter()
for i in range(200):
    orb_dots("working", i * 0.016, ORB_SIZE, 1.0)
per = (time.perf_counter() - t0) / 200 * 1000
print(f"working-20: {per:.3f} ms pro Frame")
assert per < 2.0, per

print("\nORB GEOMETRY TESTS PASSED")
