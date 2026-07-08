"""Hotkey-Backend fuer macOS auf pynput-Basis (EXPERIMENTELL/ungetestet).

Ersetzt die keyboard-lib (die auf macOS root verlangt) durch pynput, das
mit Accessibility-/Input-Monitoring-Permission auskommt (PORTING.md 3.1).
Kanonische Combo-Tokens bleiben identisch zu Windows; "win" bedeutet auf
dem Mac die Command-Taste.

ASSUMPTIONS (auf Hardware zu verifizieren):
- Maus-Seitentasten melden sich als Button-Werte 3/4 (back/forward).
- Event-Verschlucken (swallow_mouse) via darwin_intercept des
  pynput-Mouse-Listeners; falls nicht verfuegbar, degradiert der Hook zu
  "nicht verschlucken" mit Warnung.
"""

import logging
import queue
import threading

from ...controller import MOUSE_PARTS, _CANONICAL, normalize_combo

log = logging.getLogger("localflow.darwin")

# pynput-Tastennamen -> kanonische Tokens ("win" == Command)
_PYNPUT_TO_CANON = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "space": "space",
}
# kanonisch -> pynput-GlobalHotKeys-Syntax (fuer den Toggle-Hotkey)
_CANON_TO_PYNPUT = {"ctrl": "<ctrl>", "win": "<cmd>", "alt": "<alt>",
                    "shift": "<shift>", "space": "<space>"}
# Maus-Button-Werte (0-basiert: links/rechts/mitte/back/forward)
_MOUSE_VALUE_TO_CANON = {3: "maus4", 4: "maus5"}


def _key_to_part(key) -> str | None:
    """pynput Key/KeyCode -> kanonisches Token (oder None)."""
    name = getattr(key, "name", None)
    if name:
        return _PYNPUT_TO_CANON.get(name, _CANONICAL.get(name, name))
    char = getattr(key, "char", None)
    if char:
        return _CANONICAL.get(char.lower(), char.lower())
    return None


def _button_to_part(button) -> str | None:
    try:
        return _MOUSE_VALUE_TO_CANON.get(int(button.value))
    except Exception:  # noqa: BLE001
        return None


def to_pynput_combo(combo: str) -> str:
    """'ctrl+win+space' -> '<ctrl>+<cmd>+<space>' (GlobalHotKeys-Syntax)."""
    parts = []
    for p in normalize_combo(combo).split("+"):
        if p in MOUSE_PARTS:
            raise ValueError(f"Maus-Taste {p!r} geht nicht als Toggle-Hotkey")
        parts.append(_CANON_TO_PYNPUT.get(p, p if len(p) == 1 else f"<{p}>"))
    return "+".join(parts)


class PynputPtt:
    """Gedrueckt/Losgelassen fuer EINE Kombination -> DictationController.
    Spiegelt die serielle Event-Queue des win32-Backends (Ordnung!)."""

    def __init__(self, combo: str, controller, swallow_mouse: bool = False):
        combo = normalize_combo(combo)
        self.parts = [p for p in combo.split("+") if p]
        self.kb_parts = [p for p in self.parts if p not in MOUSE_PARTS]
        self.mouse_parts = [p for p in self.parts if p in MOUSE_PARTS]
        self.swallow_mouse = swallow_mouse
        self.controller = controller
        self._down: set[str] = set()
        self._active = False
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._kb_listener = None
        self._mouse_listener = None
        self._running = False

    # -- Event-Zufuhr (Listener-Threads) --------------------------------

    def _enqueue(self, part: str, is_down: bool):
        self._events.put((part, is_down))

    def _on_key(self, key, is_down: bool):
        from . import inject
        if inject.injection_active.is_set():
            return  # eigene synthetische Events ignorieren
        part = _key_to_part(key)
        if part in self.kb_parts:
            self._enqueue(part, is_down)

    def _on_click(self, x, y, button, pressed):
        from . import inject
        if inject.injection_active.is_set():
            return
        part = _button_to_part(button)
        if part in self.mouse_parts:
            self._enqueue(part, pressed)

    # -- Verarbeitung (eigener Worker, seriell) --------------------------

    def _worker_loop(self):
        while self._running:
            try:
                item = self._events.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            part, is_down = item
            try:
                self._apply(part, is_down)
            except Exception:  # noqa: BLE001
                log.exception("Hotkey-Event-Verarbeitung fehlgeschlagen")

    def _apply(self, part: str, is_down: bool):
        if is_down:
            self._down.add(part)
            if not self._active and all(p in self._down for p in self.parts):
                self._active = True
                self.controller.combo_down(owner=self)
        else:
            self._down.discard(part)
            if self._active:
                self._active = False
                self.controller.combo_up(owner=self)

    # -- Lifecycle --------------------------------------------------------

    def start(self):
        from pynput import keyboard, mouse
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True,
                                        name="localflow-hotkey-dispatch")
        self._worker.start()
        if self.kb_parts:
            self._kb_listener = keyboard.Listener(
                on_press=lambda k: self._on_key(k, True),
                on_release=lambda k: self._on_key(k, False))
            self._kb_listener.start()
        if self.mouse_parts:
            kwargs = {}
            if self.swallow_mouse:
                # ASSUMPTION: darwin_intercept erlaubt Per-Event-Verschlucken.
                def _intercept(event_type, event):
                    try:
                        import Quartz
                        btn = Quartz.CGEventGetIntegerValueField(
                            event, Quartz.kCGMouseEventButtonNumber)
                        if _MOUSE_VALUE_TO_CANON.get(int(btn)) in self.mouse_parts:
                            return None  # Event schlucken
                    except Exception:  # noqa: BLE001
                        pass
                    return event
                kwargs["darwin_intercept"] = _intercept
            try:
                self._mouse_listener = mouse.Listener(on_click=self._on_click, **kwargs)
            except TypeError:
                log.warning("darwin_intercept nicht verfuegbar - Maustaste wird "
                            "nicht verschluckt")
                self._mouse_listener = mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()
        log.info("Diktat-Hotkey aktiv (darwin): %s (Modus: %s)",
                 "+".join(self.parts), self.controller.mode)

    def stop(self):
        self._running = False
        self._events.put(None)
        for lst in (self._kb_listener, self._mouse_listener):
            if lst is not None:
                lst.stop()
        self._kb_listener = self._mouse_listener = None


def add_hotkey(combo: str, callback):
    """Toggle-Hotkey via pynput.GlobalHotKeys; Handle = Listener."""
    from pynput import keyboard
    hk = keyboard.GlobalHotKeys({to_pynput_combo(combo): callback})
    hk.start()
    return hk


def remove_hotkey(handle):
    handle.stop()


def capture_combo(timeout: float = 10.0) -> str | None:
    """Naechste gedrueckte Kombination aufzeichnen (Tastatur und/oder
    Maus-Seitentasten) - Pendant zur win32-Variante."""
    from pynput import keyboard, mouse
    lock = threading.Lock()
    down: set[str] = set()
    best: set[str] = set()
    done = threading.Event()

    def on_part(part, is_down):
        if part is None:
            return
        with lock:
            if is_down:
                down.add(part)
                if len(down) > len(best):
                    best.clear()
                    best.update(down)
            else:
                if down:
                    done.set()
                down.discard(part)

    kb = keyboard.Listener(
        on_press=lambda k: on_part(_key_to_part(k), True),
        on_release=lambda k: on_part(_key_to_part(k), False))
    ms = mouse.Listener(
        on_click=lambda x, y, b, pressed: on_part(_button_to_part(b), pressed))
    kb.start()
    ms.start()
    try:
        if not done.wait(timeout):
            return None
    finally:
        kb.stop()
        ms.stop()
    return normalize_combo("+".join(sorted(best))) if best else None
