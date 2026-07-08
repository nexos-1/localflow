"""Plattform-Auswahl: liefert das Backend-Buendel fuer das laufende OS.

Vertraege: platform/base.py. Windows: platform/win32/. Ein darwin-Backend
ist geplant (PORTING.md, Phase 3) und haengt sich hier ein.
"""

import sys


def get_backends():
    if sys.platform == "win32":
        from . import win32
        return win32.make_backends()
    if sys.platform == "darwin":
        # EXPERIMENTELL: Code steht, ist aber auf echter Hardware ungetestet
        # (PORTING.md, Phase 3). Overlay ist ein No-op-Platzhalter.
        from . import darwin
        return darwin.make_backends()
    raise RuntimeError(
        f"Kein Plattform-Backend fuer {sys.platform!r} - unterstuetzt sind "
        "Windows und (experimentell) macOS. Siehe PORTING.md.")
