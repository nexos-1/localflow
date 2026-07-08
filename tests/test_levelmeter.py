"""Unit-Test: LevelMeter passt sich an leise UND laute Mikros an."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.audio import LevelMeter


def rms_from_db(db):
    return 10 ** (db / 20)


# 1. LEISES Mikro: Sprache schwankt um -42..-34 dB (frueher: Balken fast flach)
m = LevelMeter()
levels = []
for i in range(60):  # ~4 s Sprache
    db = -38 + 4 * math.sin(i * 0.7)
    levels.append(m.level(rms_from_db(db)))
peak_seen = max(levels[20:])   # nach Einschwingzeit
avg_seen = sum(levels[20:]) / len(levels[20:])
print(f"leises Mikro: peak={peak_seen:.2f} avg={avg_seen:.2f}")
assert peak_seen > 0.85, "Balken schlagen bei leisem Mikro nicht aus"
assert avg_seen > 0.4

# 2. LAUTES Mikro: -14..-8 dB -> darf nicht dauerhaft am Anschlag kleben
m = LevelMeter()
levels = [m.level(rms_from_db(-11 + 3 * math.sin(i * 0.7))) for i in range(60)]
clipped = sum(1 for x in levels[20:] if x >= 0.99) / len(levels[20:])
print(f"lautes Mikro: anteil_vollausschlag={clipped:.2f}")
assert clipped < 0.6, "Balken kleben bei lautem Mikro am Anschlag"

# 3. Stille -> 0
m = LevelMeter()
assert m.level(rms_from_db(-70)) == 0.0
assert m.level(0.0) == 0.0
print("Stille: 0.0")

# 4. Nach lauter Passage erholt sich die Skala fuer leise Sprache
m = LevelMeter()
for _ in range(30):
    m.level(rms_from_db(-10))       # laut
mid = m.level(rms_from_db(-38))
for _ in range(120):                 # ~8 s leise weiter
    late = m.level(rms_from_db(-38 + 2))
print(f"nach lauter Passage: sofort={mid:.2f} spaeter={late:.2f}")
assert late > mid, "Skala erholt sich nicht"
assert late > 0.5

print("\nLEVELMETER TESTS PASSED")
