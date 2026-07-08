"""Win32-Hooks fuer den Diktat-Hotkey (Tastatur + Maus-Seitentasten).

Die plattformneutrale Zustandsmaschine (DictationController) und die
Combo-Kanonisierung liegen in controller.py - dieses Modul bindet sie an
die keyboard-lib und einen WH_MOUSE_LL-Hook. PushToTalk trackt den
Gedrueckt-Zustand der Kombinationstasten selbst.
"""

import ctypes
import logging
import queue
import threading
from ctypes import wintypes

import keyboard

# Zustandsmaschine + Combo-Kanonisierung sind plattformneutral und leben in
# controller.py; hier re-exportiert, damit bestehende Importe/Tests
# weiterfunktionieren. Dieses Modul enthaelt nur noch die Win32-Hooks.
from .controller import (DictationController, KEY_ALIASES, MOUSE_PARTS,  # noqa: F401
                         _CANONICAL, _expand, normalize_combo)

log = logging.getLogger("localflow.hotkey")


def add_hotkey(combo: str, callback):
    """Einfacher globaler Hotkey (Toggle) - Backend-Wrapper um keyboard."""
    return keyboard.add_hotkey(combo, callback)


def remove_hotkey(handle):
    keyboard.remove_hotkey(handle)



class _MouseHook(threading.Thread):
    """WH_MOUSE_LL-Hook fuer die Maus-Seitentasten (XButton1/2).

    suppress=False (Default, wie Wispr Flow): die Taste laeuft PARALLEL -
    der Browser navigiert weiter vor/zurueck, LocalFlow reagiert zusaetzlich.
    suppress=True: die Taste wird systemweit verschluckt und ist exklusiv
    fuers Diktieren. Linke/rechte/mittlere Maustaste werden nie angefasst.
    """

    WH_MOUSE_LL = 14
    WM_XBUTTONDOWN = 0x020B
    WM_XBUTTONUP = 0x020C

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    def __init__(self, tracked: set[str], on_event, suppress: bool = False):
        """on_event(name: 'maus4'|'maus5', is_down: bool)"""
        super().__init__(daemon=True, name="localflow-mousehook")
        self.tracked = set(tracked)
        self.on_event = on_event
        self.suppress = suppress
        self._tid: int | None = None
        self._ready = threading.Event()

    def run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      ctypes.c_size_t, ctypes.c_ssize_t)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                             wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_size_t, ctypes.c_ssize_t]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

        def proc(n_code, w_param, l_param):
            if n_code >= 0 and w_param in (self.WM_XBUTTONDOWN, self.WM_XBUTTONUP):
                ms = ctypes.cast(l_param, ctypes.POINTER(self.MSLLHOOKSTRUCT)).contents
                btn = (ms.mouseData >> 16) & 0xFFFF
                name = "maus4" if btn == 1 else ("maus5" if btn == 2 else None)
                if name and name in self.tracked:
                    try:
                        self.on_event(name, w_param == self.WM_XBUTTONDOWN)
                    except Exception:  # noqa: BLE001
                        log.exception("Maus-Hook-Callback fehlgeschlagen")
                    if self.suppress:
                        return 1  # Taste exklusiv fuers Diktieren schlucken
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc_ref = HOOKPROC(proc)  # Referenz halten, sonst GC-Crash
        hook = user32.SetWindowsHookExW(self.WH_MOUSE_LL, self._proc_ref, None, 0)
        if not hook:
            log.error("Maus-Hook konnte nicht installiert werden")
            self._ready.set()
            return
        self._tid = kernel32.GetCurrentThreadId()
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hook)

    def start(self):
        super().start()
        self._ready.wait(timeout=3)

    def stop(self):
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
            self._tid = None


class PushToTalk:
    """Bindet Keyboard- und/oder Maus-Hook an einen DictationController.
    Combo darf Tastatur und Maus-Seitentasten mischen ("maus5", "ctrl+maus4")."""

    def __init__(self, combo: str, controller: DictationController,
                 swallow_mouse: bool = False):
        combo = normalize_combo(combo)
        self.parts = [p.strip() for p in combo.lower().split("+")]
        self.kb_parts = [p for p in self.parts if p not in MOUSE_PARTS]
        self.mouse_parts = [p for p in self.parts if p in MOUSE_PARTS]
        self.swallow_mouse = swallow_mouse
        self.controller = controller
        self._down: set[str] = set()
        self._active = False
        self._hook = None
        self._mouse_hook: _MouseHook | None = None
        # Alle Hook-Events (Tastatur + Maus) laufen durch EINE serielle Queue.
        # Frueher wurde pro Event ein Thread gespawnt - dabei konnte der up-
        # Thread das Controller-Lock vor dem down-Thread bekommen und die
        # Aufnahme startete, obwohl die Taste laengst los war (Endlos-Aufnahme
        # bis zum Watchdog). Ein Worker garantiert die Reihenfolge.
        self._events: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False

    def _logical(self, name: str) -> str | None:
        name = (name or "").lower()
        for part in self.kb_parts:
            if name in _expand(part):
                return part
        return None

    def _enqueue(self, part: str, is_down: bool):
        # Wird aus den Hook-Callbacks aufgerufen (muss schnell zurueckkehren,
        # v.a. der Low-Level-Maus-Hook) - nur einreihen, keine Arbeit.
        self._events.put((part, is_down))

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
            except Exception:  # noqa: BLE001 - ein Fehler darf den Hook nie toeten
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

    def _handler(self, event):
        from .inject import injection_active
        if injection_active.is_set():
            return  # eigene synthetische Events (Ctrl+V, ALT-Tap) ignorieren
        part = self._logical(event.name)
        if part is not None:
            self._enqueue(part, event.event_type == "down")

    def start(self):
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True,
                                        name="localflow-hotkey-dispatch")
        self._worker.start()
        if self.kb_parts:
            self._hook = keyboard.hook(self._handler)
        if self.mouse_parts:
            self._mouse_hook = _MouseHook(set(self.mouse_parts), self._enqueue,
                                          suppress=self.swallow_mouse)
            self._mouse_hook.start()
        swallow_note = ", Maustaste verschluckt" if (self.mouse_parts and self.swallow_mouse) else ""
        log.info("Diktat-Hotkey aktiv: %s (Modus: %s%s)",
                 "+".join(self.parts), self.controller.mode, swallow_note)

    def stop(self):
        if self._hook:
            keyboard.unhook(self._hook)
            self._hook = None
        if self._mouse_hook:
            self._mouse_hook.stop()
            self._mouse_hook = None
        self._running = False
        self._events.put(None)


def capture_combo(timeout: float = 10.0) -> str | None:
    """Naechste gedrueckte Kombination aufzeichnen (Tastatur UND/ODER
    Maus-Seitentasten). Fertig, sobald eine gedrueckte Taste losgelassen wird.
    Gibt den normalisierten Combo-String zurueck oder None bei Timeout."""
    lock = threading.Lock()
    down: set[str] = set()
    best: set[str] = set()
    done = threading.Event()

    def on_part(part: str, is_down: bool):
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

    def kb_handler(event):
        name = (event.name or "").lower()
        part = _CANONICAL.get(name, name)
        if part:
            on_part(part, event.event_type == "down")

    kb_hook = keyboard.hook(kb_handler)
    mouse_hook = _MouseHook({"maus4", "maus5"}, on_part)
    mouse_hook.start()
    try:
        if not done.wait(timeout):
            return None
    finally:
        keyboard.unhook(kb_hook)
        mouse_hook.stop()
    return normalize_combo("+".join(sorted(best))) if best else None
