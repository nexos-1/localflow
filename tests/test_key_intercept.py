"""Unit-Tests: Enter beendet die Aufnahme und sendet ab, Escape verwirft sie.

Hardwarefrei: prueft die Verschluck-Logik des Tastatur-Hooks (decide), den
Controller-Abbruch, die Tastenliste nach dem Einfuegen und den kompletten
Weg durch main.py (Hook-Callback -> Stopp -> Verarbeitung -> press_keys)
mit Attrappen fuer Mikrofon, Pipeline und Injector.
"""

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import localflow.main as m  # noqa: E402
from localflow.commands import with_submit  # noqa: E402
from localflow.controller import DictationController  # noqa: E402
from localflow.hotkey import _KeyHook  # noqa: E402

E = frozenset()

# --- decide(): was gehoert uns, was geht durch ---
state = {"v": (frozenset({"enter", "escape"}), E)}
h = _KeyHook(lambda: state["v"], lambda n: None)
assert h.decide("enter", True, set()) == (True, True)       # Down: ausloesen + schlucken
assert h.decide("enter", True, set()) == (False, True)      # Auto-Repeat: nur schlucken
state["v"] = (E, E)                                         # Aufnahme ist jetzt vorbei
assert h.decide("enter", True, set()) == (False, True)      # Repeat weiter schlucken
assert h.decide("enter", False, set()) == (False, True)     # Up zum geschluckten Down
assert h.decide("enter", True, set()) == (False, False)     # danach wieder normal
assert h.decide("enter", False, set()) == (False, False)
print("Enter schlucken inkl. Repeat und Up OK")

state["v"] = (frozenset({"enter"}), E)
assert h.decide("enter", True, {"shift"}) == (False, False)   # Shift+Enter = Zeilenumbruch
assert h.decide("enter", True, {"ctrl"}) == (False, False)
assert h.decide("enter", False, set()) == (False, False)      # Up dazu geht auch durch
assert h.decide("escape", True, set()) == (False, False)      # nicht aktiviert
state["v"] = (frozenset({"enter"}), frozenset({"ctrl", "win"}))
assert h.decide("enter", True, {"ctrl", "win"}) == (True, True)   # Hotkey ctrl+win gehalten
assert h.decide("enter", False, set()) == (False, True)
assert h.decide("enter", True, {"ctrl", "shift"}) == (False, False)
print("Modifier-Regeln OK")

bad = _KeyHook(lambda: 1 / 0, lambda n: None)
assert bad.decide("enter", True, set()) == (False, False)   # Fehler: nie eine Taste stehlen
print("Fehler im Status -> Taste geht durch OK")

# --- with_submit(): genau EIN Enter ---
assert with_submit([], True) == ["enter"]
assert with_submit([], False) == []
assert with_submit(["enter"], True) == ["enter"]
assert with_submit(["backspace"], True) == ["backspace", "enter"]
assert with_submit(["enter", "backspace"], True) == ["enter", "backspace", "enter"]
assert with_submit(["escape"], False) == ["escape"]
print("with_submit OK")


# --- Controller.force_cancel() ---
class Probe:
    def __init__(self):
        self.events = []
    def start(self): self.events.append("start")
    def stop(self): self.events.append("stop")
    def cancel(self): self.events.append("cancel")
    def lock(self): self.events.append("lock")


for mode, presses in (("toggle", 1), ("both", 1), ("hold", 1)):
    p = Probe()
    c = DictationController(p.start, p.stop, p.cancel, p.lock, mode=mode)
    c.combo_down()
    c.force_cancel()
    assert p.events == ["start", "cancel"] and c.state == "idle", (mode, p.events, c.state)
    c.combo_up()                       # Loslassen nach dem Abbruch: kein Effekt
    assert p.events == ["start", "cancel"] and c.state == "idle", (mode, p.events)
    c.force_cancel()                   # im Leerlauf: nichts
    assert p.events == ["start", "cancel"]
print("force_cancel OK (toggle/both/hold)")


# --- Kompletter Weg durch main.py mit Attrappen ---
class FakeRecorder:
    def __init__(self):
        self.is_recording = False

    def start(self, device_override=None):
        self.is_recording = True

    def stop(self):
        self.is_recording = False
        import numpy as np
        return np.zeros(16000 * 2, dtype="float32")   # 2 s Audio


class FakeInject:
    PASTE_OK, PASTE_CLIPBOARD_ONLY, PASTE_FAILED = "ok", "clipboard_only", "failed"
    SMART_SPACING_SKIP_APPS = set()

    def __init__(self):
        self.calls = []
        self.done = threading.Event()

    def get_active_app(self):
        return "test.exe", "Testfenster"

    def get_foreground_hwnd(self):
        return 4711

    def type_text(self, text, target_hwnd=None):
        self.calls.append(("type", text, target_hwnd))
        return self.status

    def paste_text(self, text, **kw):
        self.calls.append(("paste", text, kw.get("target_hwnd")))
        return self.status

    def press_keys(self, keys, target_hwnd=None):
        self.calls.append(("keys", list(keys), target_hwnd))


class FakePipeline:
    def __init__(self, text, commands=()):
        self.text, self.commands = text, list(commands)
        self.cleaner = None

    def process(self, audio, duration_s):
        status = "ok" if (self.text or self.commands) else "empty"
        return types.SimpleNamespace(status=status, final_text=self.text,
                                     commands=list(self.commands), language="de",
                                     total_ms=123.0)

    def record_history(self, *a, **kw):
        pass


class FakeOverlay:
    def __getattr__(self, name):
        return lambda *a, **kw: None


class FakeSettings(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


def make_app(text, commands=(), paste_status="ok", **settings):
    app = object.__new__(m.LocalFlowApp)
    base = {"enter_submits": True, "escape_cancels": True, "hotkey": "shift+y",
            "hotkey2": "", "ptt_mode": "toggle", "tail_ms": 0, "min_duration_s": 0.4,
            "type_max_chars": 200, "play_sounds": False, "duck_audio": False,
            "couchmic_enabled": False, "live_preview": False, "ai_cleanup": False,
            "max_duration_s": 0, "smart_spacing": False}
    base.update(settings)
    app.settings = FakeSettings(base)
    app.recorder = FakeRecorder()
    app.overlay = FakeOverlay()
    app.ducker = types.SimpleNamespace(duck=lambda: None, restore=lambda: None,
                                       mute_complete_ts=0.0, did_mute_sessions=0)
    inj = FakeInject()
    inj.status = paste_status
    app.backends = types.SimpleNamespace(inject=inj, sounds=types.SimpleNamespace(play=lambda n: None))
    app.pipeline = FakePipeline(text, commands)
    app.models_ready = threading.Event()
    app.models_ready.set()
    app.paused = False
    app._user_paused, app._tray_variant, app.tray = False, "ready", None
    app._record_session = 0
    app._record_start_ts = app._record_start_mono = 0.0
    app._watchdog_timer = None
    app._jobs = 0
    app._jobs_lock = threading.Lock()
    app._overlay_state, app._overlay_state_ts = "hidden", 0.0
    app._intercept = (E, E)
    app._submit_pending = False
    app._notify = lambda *a, **kw: None
    app.controller = DictationController(app._on_dictate_start, app._on_dictate_stop,
                                         on_cancel=app._on_dictate_cancel,
                                         on_lock=app._on_dictate_lock,
                                         mode=base["ptt_mode"])
    return app, inj


def wait_jobs(app, timeout=5.0):
    t0 = time.time()
    time.sleep(0.05)
    while app._jobs > 0 and time.time() - t0 < timeout:
        time.sleep(0.02)
    time.sleep(0.05)


m.DONE_HOLD_S = m.CLIPBOARD_HOLD_S = m.ERROR_HOLD_S = 0  # Haken nicht abwarten


def run(app, key):
    """Aufnahme starten, dann die Taste so melden, wie der Hook es tut."""
    app.controller.combo_down()
    assert app.recorder.is_recording
    keys, _mods = app._intercept
    assert key in keys, (key, app._intercept)
    app._on_intercept_key(key)
    assert app._intercept == (E, E), "nach dem Ausloesen darf nichts mehr abgefangen werden"
    time.sleep(0.1)
    wait_jobs(app)


# Enter: Text einfuegen, danach genau ein Enter ins selbe Fenster
app, inj = make_app("Bitte den Test laufen lassen.")
run(app, "enter")
assert inj.calls == [("type", "Bitte den Test laufen lassen.", 4711),
                     ("keys", ["enter"], 4711)], inj.calls
assert app.controller.state == "idle" and not app.recorder.is_recording
print("Enter -> einfuegen + Enter OK")

# Diktat endet schon auf "press enter": trotzdem nur EIN Enter
app, inj = make_app("Absenden", commands=["enter"])
run(app, "enter")
assert inj.calls[-1] == ("keys", ["enter"], 4711), inj.calls
print("press enter + Enter-Taste -> ein Enter OK")

# Nichts erkannt: kein Enter
app, inj = make_app("")
run(app, "enter")
assert inj.calls == [], inj.calls
print("leeres Diktat -> kein Enter OK")

# Einfuegen gescheitert: kein Enter (sonst Enter im falschen Fenster)
app, inj = make_app("Text", paste_status="clipboard_only")
run(app, "enter")
assert [c[0] for c in inj.calls] == ["type"], inj.calls
print("Paste gescheitert -> kein Enter OK")

# Escape: nichts verarbeiten, nichts einfuegen
app, inj = make_app("Das darf nicht ankommen")
run(app, "escape")
assert inj.calls == [] and app.controller.state == "idle" and not app.recorder.is_recording
print("Escape -> verworfen OK")

# Normaler Stopp per Hotkey danach: KEIN Enter (submit nicht klebrig)
app, inj = make_app("Erst Enter")
run(app, "enter")
inj.calls.clear()
time.sleep(0.45)                    # Toggle-Prellschutz abwarten
app.pipeline.text = "Dann normal"
app.controller.combo_down()
time.sleep(0.45)
app.controller.combo_down()         # zweiter Druck stoppt
wait_jobs(app)
assert inj.calls == [("type", "Dann normal", 4711)], inj.calls
print("Hotkey-Stopp danach ohne Enter OK")

# Optionen aus: nichts wird abgefangen
app, inj = make_app("x", enter_submits=False, escape_cancels=False)
app.controller.combo_down()
assert app._intercept[0] == E, app._intercept   # keine Taste gehoert uns
app.controller.force_stop()
wait_jobs(app)
print("Optionen aus -> nichts abgefangen OK")

# Nur Escape an, Halte-Hotkey ctrl+win: Modifier des Hotkeys erlaubt
app, inj = make_app("x", enter_submits=False, hotkey="ctrl+win", ptt_mode="both")
app.controller.combo_down()
assert app._intercept == (frozenset({"escape"}), frozenset({"ctrl", "win"})), app._intercept
app.controller.force_cancel()
print("Abfangliste je Hotkey OK")

print("ALLE KEY-INTERCEPT-TESTS OK")
