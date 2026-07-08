"""Unit-Tests: Sprachbefehl-Erkennung am Ende des Transkripts."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.commands import DEFAULT_COMMANDS, extract_trailing_commands as ex

C = DEFAULT_COMMANDS


def check(text, exp_rest, exp_keys):
    rest, keys = ex(text, C)
    assert rest == exp_rest and keys == exp_keys, \
        f"{text!r} -> ({rest!r}, {keys}) erwartet ({exp_rest!r}, {exp_keys})"


# --- Grundfaelle ---
check("hallo welt press enter", "hallo welt", ["enter"])
check("press enter", "", ["enter"])
check("Press Enter.", "", ["enter"])
check("fix this press escape", "fix this", ["escape"])
check("das ist nur ganz normaler text", "das ist nur ganz normaler text", [])
print("Grundfaelle OK")

# --- Whisper-Alias "presenter" fuer "press enter" ---
check("kannst du das machen presenter", "kannst du das machen", ["enter"])
print("presenter-Alias OK")

# --- Backspace + "back space" (zwei Woerter) ---
check("ups press backspace", "ups", ["backspace"])
check("ups press back space", "ups", ["backspace"])
print("Backspace-Varianten OK")

# --- Delete (Entfernen-Taste) ---
check("das weg press delete", "das weg", ["delete"])
check("press delete", "", ["delete"])
print("Delete OK")

# --- Wiederholung: zweimal am Ende ---
check("lösch das press backspace press backspace", "lösch das",
      ["backspace", "backspace"])
print("Wiederholung OK")

# --- Reihenfolge bleibt Sprech-Reihenfolge ---
check("geh dahin press enter press escape", "geh dahin", ["enter", "escape"])
print("Reihenfolge OK")

# --- Satzzeichen/Gross-/Kleinschreibung ---
check("Bitte absenden, Press Enter!", "Bitte absenden,", ["enter"])
print("Satzzeichen OK")

# --- Kein False-Positive mitten im Wort ---
check("the representer said hi", "the representer said hi", [])
print("kein Teilwort-Treffer OK")

# --- Deaktiviert / leere Befehlsliste ---
assert ex("press enter", []) == ("press enter", [])
assert ex("press enter", None) == ("press enter", [])
print("leere Befehlsliste OK")

# --- Nur-Text bleibt unveraendert, keine Befehle ---
check("wir nehmen press enter als beispiel und reden weiter",
      "wir nehmen press enter als beispiel und reden weiter", [])
print("Befehl nur am ENDE, nicht in der Mitte OK")

print("\nCOMMAND TESTS PASSED")
