"""Plattform-Auswahl: liefert das Backend-Buendel fuer das laufende OS.

Vertraege: platform/base.py. Windows: platform/win32/. Ein darwin-Backend
ist geplant (PORTING.md, Phase 3) und haengt sich hier ein.
"""

import sys

_backends = None


def get_backends():
    # Gecacht: main.py ruft das auch aus Tray-Callbacks auf (Autostart-
    # Checkbox bei jedem Menue-Oeffnen) - ein frisches Bundle pro Aufruf
    # waere eine Falle, sobald make_backends() je etwas Eageres konstruiert.
    global _backends
    if _backends is not None:
        return _backends
    if sys.platform == "win32":
        from . import win32
        _backends = win32.make_backends()
    elif sys.platform == "darwin":
        # EXPERIMENTELL: Code steht, ist aber auf echter Hardware ungetestet
        # (PORTING.md, Phase 3). Overlay ist ein No-op-Platzhalter.
        from . import darwin
        _backends = darwin.make_backends()
    else:
        raise RuntimeError(
            f"Kein Plattform-Backend fuer {sys.platform!r} - unterstuetzt sind "
            "Windows und (experimentell) macOS. Siehe PORTING.md.")
    return _backends
