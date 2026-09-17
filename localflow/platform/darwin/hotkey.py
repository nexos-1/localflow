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

import contextlib
import logging
import queue
import threading

from ...controller import MOUSE_PARTS, _CANONICAL, normalize_combo

log = logging.getLogger("localflow.darwin")

# --- TIS/TSM nur auf dem Main-Thread ---------------------------------------
# pynputs Tastatur-Listener ruft in SEINEM Thread keycode_context() auf und
# damit TISCopyCurrentKeyboardInputSource/TISGetInputSourceProperty. Neuere
# macOS-Versionen brechen den Prozess dabei hart ab (SIGABRT in HIToolbox,
# dispatch_assert_queue: TIS/TSM darf nur vom Main-Thread kommen) - Feldbefund
# v0.4.1: Absturz direkt nach "Diktat-Hotkey aktiv (darwin)", 100 %
# reproduzierbar aus Terminal, LaunchAgent und App-Bundle.
# Loesung: den Layout-Kontext EINMAL auf dem Main-Thread lesen (pynput kopiert
# die Layout-Daten in Python-Bytes, das Ergebnis ist also threadsicher
# weiterverwendbar) und pynputs keycode_context() durch eine Variante
# ersetzen, die nur noch den Cache liefert. Die Listener-Threads fassen TIS
# danach nie mehr an; die spaetere Zeichen-Uebersetzung laeuft ueber
# UCKeyTranslate auf den kopierten Bytes (kein TIS).
_kc = {"ctx": None, "orig": None, "patched": False}
_kc_lock = threading.Lock()


def _pynput_darwin_modules():
    import pynput._util.darwin as pud
    import pynput.keyboard._darwin as pkd
    return pud, pkd


def _install_keycode_patch(pud, pkd):
    if _kc["patched"]:
        return
    _kc["orig"] = pud.keycode_context

    @contextlib.contextmanager
    def cached_keycode_context():
        ctx = _kc["ctx"]
        if ctx is None:
            raise RuntimeError("Tastatur-Layout-Kontext fehlt - TIS darf nur auf "
                               "dem Main-Thread gelesen werden")
        yield ctx

    pud.keycode_context = cached_keycode_context
    pkd.keycode_context = cached_keycode_context
    _kc["patched"] = True


def _read_context_here():
    """Original-keycode_context ausfuehren (NUR auf dem Main-Thread rufen)."""
    with _kc["orig"]() as ctx:
        _kc["ctx"] = ctx


def ensure_keycode_context(wait_s: float = 3.0) -> bool:
    """Vor JEDEM pynput-Tastatur-Listener aufrufen. Auf dem Main-Thread wird
    der Kontext (neu) gelesen - so zieht ein Layoutwechsel beim naechsten
    Hotkey-Setup nach. Abseits des Main-Threads wird nur der Cache benutzt;
    fehlt er noch, wird das Lesen ueber den Cocoa-Main-Loop eingereiht.
    RuntimeError, wenn der Kontext nicht sicher beschafft werden kann -
    lieber kein Hotkey als ein Prozess-Abbruch."""
    pud, pkd = _pynput_darwin_modules()
    with _kc_lock:
        _install_keycode_patch(pud, pkd)
        if threading.current_thread() is threading.main_thread():
            _read_context_here()
            return True
        if _kc["ctx"] is not None:
            return True
    done = threading.Event()

    def hop():
        try:
            with _kc_lock:
                _read_context_here()
        except Exception:  # noqa: BLE001
            log.exception("Tastatur-Layout-Kontext konnte nicht gelesen werden")
        finally:
            done.set()

    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(hop)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Tastatur-Layout-Kontext nicht initialisiert und kein "
                           "Cocoa-Main-Loop erreichbar") from exc
    if not done.wait(wait_s) or _kc["ctx"] is None:
        raise RuntimeError("Tastatur-Layout-Kontext nicht initialisiert "
                           "(Main-Loop antwortet nicht)")
    return True


# Zweite, vom Monkeypatch UNABHAENGIGE Schicht: eigene Listener-Klassen.
# - _run ueberspringt pynputs Listener._run (der keycode_context() ruft) und
#   setzt den gecachten Kontext direkt; weiter geht es in ListenerMixin._run
#   (Event-Tap + CFRunLoop wie gehabt).
# - Die Event-Maske laesst NSSystemDefined (Medientasten) weg: pynput baut
#   dafuer im Listener-Thread ein NSEvent (AppKit abseits des Main-Threads).
#   LocalFlow braucht keine Medientasten.
_safe = {"Listener": None, "GlobalHotKeys": None}


def _verify_pynput_internals(keyboard, pud):
    """Die Haertung haengt an pynput-Interna (gepinnt: pynput==1.8.2). Passen
    sie nicht mehr, lieber KEIN Tastatur-Hotkey als ein Prozess-Abbruch."""
    lst = keyboard.Listener
    problems = []
    if not hasattr(pud, "ListenerMixin") or not hasattr(pud.ListenerMixin, "_run"):
        problems.append("ListenerMixin._run fehlt")
    elif pud.ListenerMixin not in lst.__mro__:
        problems.append("Listener erbt nicht von ListenerMixin")
    if "_run" not in vars(lst):
        problems.append("Listener._run fehlt")
    ev = getattr(lst, "_event_to_key", None)
    if ev is None or "_context" not in ev.__code__.co_names:
        problems.append("Listener._event_to_key nutzt _context nicht")
    if not hasattr(lst, "_EVENTS"):
        problems.append("Listener._EVENTS fehlt")
    if problems:
        raise RuntimeError("pynput-Interna unerwartet (" + "; ".join(problems) + ") - "
                           "Tastatur-Hotkeys deaktiviert, pynput==1.8.2 installieren")


def _safe_classes():
    if _safe["Listener"] is not None:
        return _safe["Listener"], _safe["GlobalHotKeys"]
    import Quartz
    from pynput import keyboard
    pud, _pkd = _pynput_darwin_modules()
    _verify_pynput_internals(keyboard, pud)
    mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))

    def _run(self):
        ctx = _kc["ctx"]
        if ctx is None:
            raise RuntimeError("Tastatur-Layout-Kontext fehlt (ensure_keycode_context)")
        self._context = ctx
        try:
            # pynputs Listener._run (ruft TIS) ueberspringen -> ListenerMixin._run
            super(keyboard.Listener, self)._run()
        finally:
            self._context = None

    _safe["Listener"] = type("SafeListener", (keyboard.Listener,),
                             {"_EVENTS": mask, "_run": _run})
    _safe["GlobalHotKeys"] = type("SafeGlobalHotKeys", (keyboard.GlobalHotKeys,),
                                  {"_EVENTS": mask, "_run": _run})
    return _safe["Listener"], _safe["GlobalHotKeys"]


def safe_keyboard_listener(**kwargs):
    """Tastatur-Listener, der TIS nie im eigenen Thread anfasst."""
    ensure_keycode_context()
    return _safe_classes()[0](**kwargs)

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

    def __init__(self, combo: str, controller, swallow_mouse: bool = False,
                 gate=None):
        """gate: optionaler Callable -> bool; False = DOWN ignorieren
        (Vollbild-App). UP-Events laufen immer durch (wie win32)."""
        combo = normalize_combo(combo)
        self.parts = [p for p in combo.split("+") if p]
        self.kb_parts = [p for p in self.parts if p not in MOUSE_PARTS]
        self.mouse_parts = [p for p in self.parts if p in MOUSE_PARTS]
        self.swallow_mouse = swallow_mouse
        self.gate = gate
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
        if is_down and not self._gate_open():
            return
        self._events.put((part, is_down))

    def _gate_open(self) -> bool:
        if self.gate is None:
            return True
        try:
            return bool(self.gate())
        except Exception:  # noqa: BLE001 - Gate-Fehler = offen
            log.debug("Hotkey-Gate fehlgeschlagen", exc_info=True)
            return True

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
        from pynput import mouse
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True,
                                        name="localflow-hotkey-dispatch")
        self._worker.start()
        if self.kb_parts:
            try:
                self._kb_listener = safe_keyboard_listener(
                    on_press=lambda k, *a: self._on_key(k, True),
                    on_release=lambda k, *a: self._on_key(k, False))
                self._kb_listener.start()
            except Exception:  # noqa: BLE001
                # Sanfter Ausfall: ohne sicheren Layout-Kontext KEIN Tastatur-
                # Listener - ein stummer Hotkey ist reparierbar, ein SIGABRT
                # beim Start nicht.
                self._kb_listener = None
                log.exception("Tastatur-Hotkey %s deaktiviert (macOS-Listener "
                              "nicht sicher startbar)", "+".join(self.kb_parts))
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
    ensure_keycode_context()
    hk = _safe_classes()[1]({to_pynput_combo(combo): callback})
    hk.start()
    return hk


def remove_hotkey(handle):
    handle.stop()


def capture_combo(timeout: float = 10.0) -> str | None:
    """Naechste gedrueckte Kombination aufzeichnen (Tastatur und/oder
    Maus-Seitentasten) - Pendant zur win32-Variante."""
    from pynput import mouse
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

    kb = safe_keyboard_listener(
        on_press=lambda k, *a: on_part(_key_to_part(k), True),
        on_release=lambda k, *a: on_part(_key_to_part(k), False))
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
