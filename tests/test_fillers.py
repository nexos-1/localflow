"""Unit-Tests: cleanup.strip_fillers entfernt deutsche Fuellwoerter
deterministisch (Gemma 3 4B liess "Ähm" trotz Prompt-Regel stehen)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.cleanup import _finish, strip_fillers  # noqa: E402

CASES = [
    # Satzanfang: Fuellwort weg, naechstes Wort gross
    ("Ähm, also das Meeting ist morgen.", "Also das Meeting ist morgen."),
    ("Äh kannst du mir die Datei schicken?", "Kannst du mir die Datei schicken?"),
    ("ähm also das meeting", "Also das meeting"),
    ("Ja, das ist so. Ähm ich hab kein Problem.", "Ja, das ist so. Ich hab kein Problem."),
    ("Öhm das geht", "Das geht"),
    ("Ähhm, gut", "Gut"),
    # Satzmitte: Kleinschreibung bleibt
    ("Und ähm, ja, es sind", "Und ja, es sind"),
    ("ich habe jetzt, ähm, Viator, ich", "ich habe jetzt, Viator, ich"),
    ("gegenchecken. Ähm...", "gegenchecken."),
    # Woerter, die nur so anfangen, bleiben unangetastet
    ("Ähnlich wie Ährenfeld, Mähmaschine", "Ähnlich wie Ährenfeld, Mähmaschine"),
    # Englisch/"hm" ist Sache des Modells; nur Fuellwort -> Text unveraendert
    ("hmm okay um so", "hmm okay um so"),
    ("Ähm...", "Ähm..."),
    ("", ""),
]

for raw, want in CASES:
    got = strip_fillers(raw)
    assert got == want, f"{raw!r}: {got!r} != {want!r}"
print(f"1. strip_fillers: {len(CASES)} Faelle OK")

# Auch die Modellausgabe wird gefiltert (falls das Modell eins stehen laesst)
assert _finish("ähm also das ist gut so", "Ähm, also das ist gut so.") == "Also das ist gut so."
print("2. _finish filtert die Modellausgabe OK")
print("\nFILLER TESTS PASSED")
