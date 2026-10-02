"""Unit-Tests: Sound-Pakete (Setting sound_set) und Vorrang eigener WAVs.

Hardwarefrei: laeuft in einem temporaeren Datenordner (LOCALFLOW_DATA_DIR),
spielt nichts ab, prueft nur, welche Datei fuer welchen Sound gewaehlt wird
und dass die mitgelieferten WAVs gueltig sind.
"""

import os
import sys
import tempfile
import wave

os.environ["LOCALFLOW_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow import sounds  # noqa: E402

sounds.ensure_sounds()
own = lambda n: os.path.join(sounds.SOUND_DIR, f"{n}.wav")  # noqa: E731
classic = lambda n: os.path.join(sounds.BUNDLED_DIR, "classic", f"{n}.wav")  # noqa: E731

# Mitgelieferte WAVs: vorhanden und lesbar
for n in ("start", "stop", "lock"):
    with wave.open(classic(n)) as w:
        assert w.getnframes() > 0 and w.getframerate() > 0, n
print("mitgelieferte WAVs gueltig OK")

# Standard: erzeugte Chimes
sounds.set_sound_set("soft")
for n in ("start", "stop", "lock", "error"):
    assert sounds.sound_path(n) == own(n), (n, sounds.sound_path(n))
print("soft -> erzeugte Chimes OK")

# Klassisch: mitgelieferte Dateien, error faellt auf den Chime zurueck
sounds.set_sound_set("classic")
for n in ("start", "stop", "lock"):
    assert sounds.sound_path(n) == classic(n), (n, sounds.sound_path(n))
assert sounds.sound_path("error") == own("error")
print("classic -> mitgelieferte WAVs, error -> Chime OK")

# Unbekannter Name -> soft
sounds.set_sound_set("gibtsnicht")
assert sounds.sound_path("start") == own("start")
print("unbekanntes Paket -> soft OK")

# Eigene WAV in custom.txt hat immer Vorrang
with open(os.path.join(sounds.SOUND_DIR, "custom.txt"), "w", encoding="utf-8") as f:
    f.write("stop\n")
sounds.set_sound_set("classic")
assert sounds.sound_path("stop") == own("stop")
assert sounds.sound_path("start") == classic("start")
print("eigene WAV (custom.txt) vor Paket OK")

# Nicht vorhandener Sound -> None (play tut dann nichts)
assert sounds.sound_path("gibtsnicht") is None
print("ALLE SOUND-SET-TESTS OK")
