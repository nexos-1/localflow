"""Verwaist-Wächter (main._overlay_orphan_guard): haengt die Pill sichtbar,
obwohl weder Aufnahme noch Verarbeitung laeuft, wird sie zwangsversteckt
(Feldbefund 2026-07-14). Getestet ohne echte App: Instanz via __new__,
Schleife ueber gepatchtes time.sleep begrenzt."""

import os
import sys
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import localflow.main as m  # noqa: E402


class _FakeOverlay:
    def __init__(self):
        self.states = []

    def set_state(self, s):
        self.states.append(s)


def make_app(recording=False, jobs=0, state="processing", age_s=20.0):
    app = object.__new__(m.LocalFlowApp)
    app.overlay = _FakeOverlay()
    app.recorder = types.SimpleNamespace(is_recording=recording)
    app._jobs = jobs
    app._overlay_state = state
    app._overlay_state_ts = time.monotonic() - age_s
    return app


def run_guard(app, iterations=3):
    """Guard-Schleife laufen lassen; nach N sleep-Aufrufen abbrechen."""
    calls = {"n": 0}
    real_sleep = m.time.sleep

    def fake_sleep(_s):
        calls["n"] += 1
        if calls["n"] > iterations:
            raise KeyboardInterrupt

    m.time.sleep = fake_sleep
    try:
        app._overlay_orphan_guard()
    except KeyboardInterrupt:
        pass
    finally:
        m.time.sleep = real_sleep


# 1) Verwaister Zustand (alt, nichts laeuft) -> Pill wird versteckt
app = make_app()
run_guard(app)
assert app.overlay.states == ["hidden"], app.overlay.states
assert app._overlay_state == "hidden"
print("verwaist -> hidden OK")

# 2) Aufnahme laeuft -> Waechter fasst nichts an
app = make_app(recording=True)
run_guard(app)
assert app.overlay.states == [], app.overlay.states
print("Aufnahme aktiv -> unangetastet OK")

# 3) Verarbeitung laeuft -> unangetastet (auch wenn der State alt ist)
app = make_app(jobs=1)
run_guard(app)
assert app.overlay.states == [], app.overlay.states
print("Verarbeitung aktiv -> unangetastet OK")

# 4) Frischer Zustand (unter 15s) -> noch unangetastet
app = make_app(age_s=3.0)
run_guard(app)
assert app.overlay.states == [], app.overlay.states
print("frischer Zustand -> unangetastet OK")

print("\nORPHAN GUARD TESTS PASSED")
