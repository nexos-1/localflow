"""Overlay-Platzhalter fuer macOS (Phase 3b).

Die animierte Pill von Windows haengt an Tk-Features, die es auf macOS so
nicht gibt (-transparentcolor, Worker-Thread-UI). Der echte Port ist ein
AppKit-NSPanel auf dem Main-Loop (PORTING.md 3.3) und wird erst auf echter
Hardware entwickelt. Bis dahin: API-kompatibler No-op - das Diktat selbst
funktioniert, Feedback kommt ueber die Sounds.
"""

import logging

log = logging.getLogger("localflow.darwin")


class NullOverlay:
    def start(self):
        log.info("Overlay auf macOS noch nicht portiert (NullOverlay aktiv) - "
                 "Status-Feedback kommt ueber Sounds. Siehe PORTING.md 3.3.")

    def set_state(self, state: str):
        log.debug("Overlay-State (no-op): %s", state)

    def set_level(self, level: float):
        pass

    def set_text(self, text: str):
        pass

    def set_glass(self, enabled: bool):
        pass

    def set_style(self, font_family=None, font_size=None):
        pass
