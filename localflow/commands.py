"""Sprachbefehle: erkennt Befehlsphrasen am ENDE des Diktats (z.B.
"press enter") und uebersetzt sie in Tastendruecke.

Die Erkennung laeuft bewusst auf dem ROH-Transkript (vor dem LLM-Cleanup) -
sonst formatiert das kleine Modell die Befehlsphrase um und sie ist nicht mehr
zuverlaessig auffindbar. Erkannte Befehle werden abgeschnitten; der Rest-Text
wird normal weiterverarbeitet und eingefuegt, danach feuern die Tasten in
Sprech-Reihenfolge.

Whisper hoert "press enter" ueberraschend oft als "presenter" - dieser Alias
ist deshalb bewusst mit dabei (im Dashboard editierbar).
"""

import re

# Tasten, die inject.press_keys kennt (nur diese sind als Ziel erlaubt).
VALID_KEYS = {"enter", "backspace", "escape", "tab", "delete"}

DEFAULT_COMMANDS = [
    {"key": "enter", "phrases": ["press enter", "presenter", "presento"]},
    {"key": "backspace", "phrases": ["press backspace", "press back space"]},
    {"key": "escape", "phrases": ["press escape"]},
    {"key": "delete", "phrases": ["press delete"]},
]

# Trennzeichen zwischen den Woertern einer Phrase bzw. am Ende (Whisper haengt
# gern Satzzeichen an: "Press Enter." / "press, enter").
_SEP = r"[\s\.,!?;:\-…]+"
_TRAIL = r"[\s\.,!?;:\-…\"'”』」)]*"


def _triggers(commands) -> list[tuple[list[str], str]]:
    """(Wortliste, Taste)-Paare, laengste Phrase zuerst (damit 'press back
    space' vor 'press backspace' greift)."""
    out = []
    for c in commands or []:
        if not isinstance(c, dict):
            continue
        key = (c.get("key") or "").strip().lower()
        if key not in VALID_KEYS:
            continue
        for phrase in c.get("phrases", []):
            words = [w for w in re.split(r"\s+", (phrase or "").strip().lower()) if w]
            if words:
                out.append((words, key))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def extract_trailing_commands(text: str, commands) -> tuple[str, list[str]]:
    """Schneidet wiederholt passende Befehlsphrasen vom Ende ab.
    Gibt (rest_text, [tasten in Sprech-Reihenfolge]) zurueck."""
    triggers = _triggers(commands)
    if not triggers or not text:
        return text, []
    keys: list[str] = []
    for _ in range(12):  # harte Obergrenze gegen pathologische Schleifen
        stripped = False
        for words, key in triggers:
            inner = _SEP.join(re.escape(w) for w in words)
            m = re.search(r"\b" + inner + _TRAIL + r"$", text, re.IGNORECASE)
            if m:
                text = text[:m.start()].rstrip(" \t\r\n")
                keys.append(key)
                stripped = True
                break
        if not stripped or not text.strip():
            break
    keys.reverse()  # vom Ende abgeschnitten -> zurueck in Sprech-Reihenfolge
    return text, keys
