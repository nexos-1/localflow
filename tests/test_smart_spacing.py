"""Unit-Tests: Smart-Spacing-Entscheidungslogik (_should_space) und
Terminal-Ausschlussliste. Die Cursor-Sonde selbst ist interaktiv (synthetische
Tasten) und wird bewusst nur im echten Diktat verifiziert."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.inject import SMART_SPACING_SKIP_APPS, _should_space as sp


# Kernfall: Diktat klebt sonst an Satzende/Wort -> Leerzeichen
assert sp(".", "Und weiter geht es") is True
assert sp("t", "neuer Satz") is True          # mitten am Wort angesetzt
assert sp("?", "Genau") is True
print("Klebefaelle bekommen Leerzeichen OK")

# Kein Leerzeichen: davor ist schon Weissraum
assert sp(" ", "Hallo") is False
assert sp("\n", "Hallo") is False
assert sp("\r\n", "Hallo") is False           # Sonde kann CRLF liefern
assert sp("\t", "Hallo") is False
print("Weissraum davor -> kein doppeltes Leerzeichen OK")

# Kein Leerzeichen: Feldanfang, unbekannt oder Selektion (None)
assert sp("", "Hallo") is False
assert sp(None, "Hallo") is False
print("Feldanfang/Selektion -> unangetastet OK")

# Kein Leerzeichen: neuer Text beginnt mit anschliessender Interpunktion
assert sp("t", ", und noch was") is False
assert sp("t", ".") is False
assert sp("t", ")") is False
assert sp("t", " schon mit Leerzeichen") is False
print("Interpunktions-Fortsetzung klebt korrekt OK")

# Kein Leerzeichen: davor oeffnende Klammer/Anfuehrungszeichen
assert sp("(", "Wort") is False
assert sp('"', "Wort") is False
assert sp("„", "Wort") is False
print("Nach oeffnender Klammer/Quote kein Leerzeichen OK")

# Leere Eingaben
assert sp("t", "") is False
assert sp(None, "") is False
print("Leere Eingaben OK")

# Terminal-Ausschluss: die wichtigsten Windows-Terminals sind gelistet
for app in ("windowsterminal", "cmd", "powershell", "pwsh", "conhost"):
    assert app in SMART_SPACING_SKIP_APPS, app
print("Terminal-Ausschlussliste OK")

print("\nSMART SPACING TESTS PASSED")
