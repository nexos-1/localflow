"""AppKit-Overlay-Test fuer CI auf echten macOS-Runnern.

Baut die animierte Pill (NSPanel) wirklich auf, pumpt den Main-Runloop von
Hand (kein NSApp.run noetig) und prueft die Zustandsmaschine durch einen
kompletten Diktat-Zyklus: einblenden -> Live-Text -> processing -> hidden.
Das ist der maximale Blind-Test ohne interaktive Hardware - Optik/Position
muessen auf einem echten Mac gesichtet werden (PORTING.md Phase 3b).
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if sys.platform != "darwin":
    sys.exit("Dieser Test braucht macOS (AppKit).")

import AppKit  # noqa: E402
import Foundation  # noqa: E402

from localflow.overlay_model import THEMES  # noqa: E402
from localflow.platform.darwin.overlay import DarwinOverlay, make_overlay  # noqa: E402


def pump(seconds: float):
    """Main-Runloop pumpen, damit callAfter/callLater-Timer feuern."""
    end = time.time() + seconds
    rl = Foundation.NSRunLoop.currentRunLoop()
    while time.time() < end:
        rl.runMode_beforeDate_(
            Foundation.NSDefaultRunLoopMode,
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))


def main():
    AppKit.NSApplication.sharedApplication()

    o = make_overlay()
    assert isinstance(o, DarwinOverlay), f"Fallback statt AppKit: {type(o).__name__}"

    # Wie in main.start(): erst start(), dann Design-Settings, dann Diktat.
    o.start()
    o.set_glass(True)
    o.set_style("Helvetica", 12)
    o.set_theme("light")
    o.set_text("")
    o.set_state("recording")
    o.set_level(0.7)
    o.set_text("dies ist ein langer live-transkript-text " * 4)
    pump(1.0)

    assert o._panel is not None and not o._dead, "NSPanel wurde nicht gebaut"
    st = o._st
    assert st["shown"] is True and st["vis"] == "recording", st["vis"]
    assert st["text"].startswith("dies ist"), st["text"][:30]
    assert st["col"] == THEMES["light"]
    assert o._panel.alphaValue() > 0.5, f"Pill nicht eingeblendet: {o._panel.alphaValue()}"
    assert o._panel.ignoresMouseEvents(), "Panel muss click-through sein"
    fr = o._panel.frame()
    assert fr.size.width == o._max_w and fr.size.height == o._win_h
    assert st["pill_rect"] is not None, "drawRect_ lief nie (kein WindowServer?)"
    print(f"Pill sichtbar: {fr.size.width:.0f}x{fr.size.height:.0f} @ "
          f"({fr.origin.x:.0f},{fr.origin.y:.0f}), alpha={o._panel.alphaValue():.2f}")

    # State-Morphs durchspielen
    o.set_state("locked")
    pump(0.4)
    assert st["vis"] == "locked" and o._ring.v > 0.9, o._ring.v
    o.set_state("processing")
    pump(0.4)
    assert st["vis"] == "processing"
    o.set_state("hidden")
    pump(1.0)
    assert st["shown"] is False, "Pill blieb nach hidden sichtbar"
    assert o._panel.alphaValue() == 0.0

    # Zweiter Zyklus: altes Transkript darf nicht wieder auftauchen
    o.set_state("recording")
    pump(0.4)
    assert st["shown"] is True and st["text"] == "", st["text"][:30]
    o.set_state("hidden")
    pump(1.0)

    print("\nDARWIN OVERLAY TESTS PASSED")


if __name__ == "__main__":
    main()
