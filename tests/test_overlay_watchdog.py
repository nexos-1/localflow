"""Overlay-Watchdog: stellt den Feldbefund vom 2026-07-13 nach.

Symptom damals: Diktat/Sounds liefen, aber die Pill war dauerhaft
unsichtbar - das Tk-Fenster existierte noch (alpha=0), die Tick-Kette der
Overlay-Thread war aber tot. Dieser Test toetet das Overlay-Fenster von
AUSSEN (WM_CLOSE, wie es Display-/Session-Events koennen) und prueft,
dass der Watchdog eine frische Pill startet und der Aufnahme-Zustand
(State + Live-Text + Design) automatisch zurueckkommt.

Windows-only; oeffnet real kurz die Pill unten am Bildschirm. Braucht
eine INTERAKTIVE Windows-Session - auf GitHub-CI-Runnern zerstoert die
Headless-Fensterstation Tk-Fenster sofort (verifiziert 2026-07-13),
deshalb laeuft dieser Test bewusst nicht in ci.yml.
"""

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if sys.platform != "win32":
    sys.exit("Dieser Test braucht Windows (Tk-Overlay + Win32).")

import localflow.overlay as ov  # noqa: E402

# Watchdog fuer den Test beschleunigen (Erkennung sonst ~10-15s)
ov.WATCHDOG_CHECK_S = 0.4
ov.WATCHDOG_MISSES = 2

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010


def window_alpha(hwnd):
    key = ctypes.c_uint()
    alpha = ctypes.c_ubyte()
    flags = ctypes.c_uint()
    if not user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key),
                                             ctypes.byref(alpha),
                                             ctypes.byref(flags)):
        return None
    return alpha.value


def wait_for(cond, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = cond()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError(f"Timeout ({timeout}s): {what}")


def main():
    o = ov.Overlay()
    o.start()

    # 1. Erste Generation kommt hoch und wird bei Aufnahme sichtbar
    hwnd1 = wait_for(lambda: o._hwnd_box.get("hwnd"), 10, "erstes Overlay-Fenster")
    o.set_theme("light")
    o.set_glass(False)
    o.set_state("recording")
    o.set_text("watchdog regressionstest text")
    wait_for(lambda: (window_alpha(hwnd1) or 0) > 200, 5,
             "Pill sichtbar (alpha > 200)")
    print(f"Gen 1: hwnd={hwnd1:#x} alpha={window_alpha(hwnd1)}")

    # 2. Fenster von aussen toeten - Overlay-Thread stirbt, App merkt nichts
    user32.PostMessageW(hwnd1, WM_CLOSE, 0, 0)

    # 3. Watchdog muss eine NEUE Generation starten ...
    hwnd2 = wait_for(
        lambda: (o._hwnd_box.get("hwnd") or None)
        if o._hwnd_box.get("hwnd") not in (None, hwnd1) else None,
        15, "Watchdog-Neustart (neues Fenster)")
    assert hwnd2 != hwnd1
    # ... und der Aufnahme-Zustand kommt per Replay automatisch zurueck
    wait_for(lambda: (window_alpha(hwnd2) or 0) > 200, 5,
             "Pill nach Selbstheilung wieder sichtbar")
    print(f"Gen 2: hwnd={hwnd2:#x} alpha={window_alpha(hwnd2)} (Replay ok)")

    # 4. Normales Verhalten der neuen Generation: hidden blendet aus
    o.set_state("hidden")
    wait_for(lambda: window_alpha(hwnd2) == 0, 5,
             "Pill blendet nach hidden aus")

    print("\nOVERLAY WATCHDOG TEST PASSED")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    # Sofort raus: beim normalen Teardown raeumt der GC Tk-Objekte aus dem
    # falschen Thread ab (Tcl_AsyncDelete-Abort) - Test ist hier fertig.
    os._exit(0)
