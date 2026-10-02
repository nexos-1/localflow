"""Unit-Tests: Option processing_feedback (Verarbeitung + Haken in der Pille).

Hardwarefrei: ein kompletter Diktat-Durchlauf durch main.py mit Attrappen,
mitgeschrieben wird jede Pillen-Zustandsfolge. An = processing -> done ->
hidden (wie bisher). Aus = beim Stopp sofort hidden, kein processing, kein
done. Fehler- und Clipboard-Hinweis bleiben in beiden Faellen.
"""

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

import localflow.main as m  # noqa: E402

m.DONE_HOLD_S = m.CLIPBOARD_HOLD_S = m.ERROR_HOLD_S = 0


class Overlay:
    def __init__(self):
        self.states = []

    def set_state(self, s):
        self.states.append(s)

    def __getattr__(self, name):
        return lambda *a, **kw: None


class Inject:
    PASTE_OK, PASTE_CLIPBOARD_ONLY, PASTE_FAILED = "ok", "clipboard_only", "failed"
    SMART_SPACING_SKIP_APPS = set()

    def __init__(self, status):
        self.status = status
        self.calls = []

    def get_active_app(self):
        return "test.exe", "Test"

    def get_foreground_hwnd(self):
        return 1

    def type_text(self, text, target_hwnd=None):
        self.calls.append(text)
        return self.status

    def press_keys(self, keys, target_hwnd=None):
        pass


class Pipeline:
    cleaner = None

    def __init__(self, text, fail=False):
        self.text, self.fail = text, fail

    def process(self, audio, duration_s):
        if self.fail:
            raise RuntimeError("Whisper kaputt")
        return types.SimpleNamespace(status="ok" if self.text else "empty",
                                     final_text=self.text, commands=[],
                                     language="de", total_ms=1.0)

    def record_history(self, *a, **kw):
        pass


def dictate(feedback, text="Hallo Welt", status="ok", fail=False):
    app = object.__new__(m.LocalFlowApp)
    app.settings = types.SimpleNamespace(get=lambda k: {
        "processing_feedback": feedback, "tail_ms": 0, "min_duration_s": 0.4,
        "type_max_chars": 200, "play_sounds": False, "smart_spacing": False}.get(k))
    app.overlay = Overlay()
    app.recorder = types.SimpleNamespace(is_recording=True,
                                         stop=lambda: np.zeros(32000, dtype="float32"))
    app.ducker = types.SimpleNamespace(restore=lambda: None, mute_complete_ts=0.0,
                                       did_mute_sessions=0)
    inj = Inject(status)
    app.backends = types.SimpleNamespace(inject=inj, sounds=types.SimpleNamespace(play=lambda n: None))
    app.pipeline = Pipeline(text, fail)
    app.models_ready = threading.Event()
    app.models_ready.set()
    app._record_session = 1
    app._record_start_mono = 0.0
    app._watchdog_timer = None
    app._jobs, app._jobs_lock = 0, threading.Lock()
    app._overlay_state, app._overlay_state_ts = "recording", 0.0
    app._user_paused, app._tray_variant, app.tray = False, "ready", None
    app._intercept, app._submit_pending = (frozenset(), frozenset()), False
    app._notify = lambda *a, **kw: None
    app._on_dictate_stop()
    time.sleep(0.05)
    t0 = time.time()
    while app._jobs and time.time() - t0 < 5:
        time.sleep(0.02)
    time.sleep(0.05)
    return app.overlay.states, inj.calls


states, pasted = dictate(True)
assert states == ["processing", "done", "hidden"], states
assert pasted == ["Hallo Welt"]
print("an: processing -> done -> hidden OK")

states, pasted = dictate(False)
assert "processing" not in states and "done" not in states, states
assert states[0] == "hidden" and set(states) == {"hidden"}, states
assert pasted == ["Hallo Welt"]
print("aus: sofort hidden, Text trotzdem eingefuegt OK", states)

states, _ = dictate(False, status="clipboard_only")
assert "clipboard" in states and "done" not in states, states
print("aus: Clipboard-Hinweis bleibt OK")

states, _ = dictate(False, fail=True)
assert "error" in states and "processing" not in states, states
print("aus: Fehler bleibt sichtbar OK")

states, _ = dictate(False, text="")
assert set(states) == {"hidden"}, states
print("aus: leeres Diktat OK")

print("ALLE PROCESSING-FEEDBACK-TESTS OK")
