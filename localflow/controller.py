"""Plattformneutrale Diktat-Zustandsmaschine + Hotkey-Combo-Kanonisierung.

Bewusst OHNE jeden Plattform-Import (kein keyboard, kein Win32): dieses
Modul ist auf jedem OS importierbar und unit-testbar. Die Low-Level-Hooks
(Tastatur/Maus) liefert das jeweilige Plattform-Backend
(localflow/platform/...), das combo_down/combo_up hier hineinruft.

Drei Modi:
- "hold":   Kombination halten = aufnehmen, loslassen = fertig.
- "both":   wie hold, PLUS Doppeltipp = Freisprechen (Aufnahme laeuft nach dem
            Loslassen weiter, naechster Druck stoppt). Default.
- "toggle": jeder Druck startet bzw. stoppt (kein Halten noetig). Ein
            zweiter Druck kurz nach dem ersten (Prellen der Maustaste oder
            der antrainierte Doppeltipp) wird ignoriert, siehe toggle_guard_s.
"""

import logging
import threading
import time

log = logging.getLogger("localflow.controller")

# Namen, wie Hooks sie melden koennen, je logische Taste. Die kanonischen
# Tokens (ctrl/win/alt/shift/space/maus4/maus5) sind plattformneutral;
# jedes Backend darf weitere rohe Aliasnamen darauf abbilden.
KEY_ALIASES = {
    "ctrl": {"ctrl", "left ctrl", "right ctrl", "strg", "linke strg", "rechte strg"},
    "win": {"windows", "left windows", "right windows", "win", "linke windows", "rechte windows"},
    "alt": {"alt", "left alt", "right alt", "alt gr"},
    "shift": {"shift", "left shift", "right shift", "umschalt", "linke umschalt", "rechte umschalt"},
    "space": {"space", "leertaste", "spacebar"},
    # Maus-Seitentasten (eigener Low-Level-Hook im Backend)
    "maus4": {"maus4", "mouse4", "x1", "xbutton1"},
    "maus5": {"maus5", "mouse5", "x2", "xbutton2"},
}

MOUSE_PARTS = {"maus4", "maus5"}

# Rueckrichtung: gemeldete/getippte Namen -> unsere kanonischen Namen
_CANONICAL = {}
for canon, names in KEY_ALIASES.items():
    for n in names:
        _CANONICAL[n] = canon


_MODIFIER_ORDER = {"ctrl": 0, "shift": 1, "alt": 2, "win": 3}


def normalize_combo(combo: str) -> str:
    """'alt+space+ctrl' / 'strg+leertaste' -> 'ctrl+alt+space' / 'ctrl+space'.
    Kanonisiert Namen und sortiert Modifier in gewohnter Reihenfolge."""
    parts = [_CANONICAL.get(p.strip().lower(), p.strip().lower())
             for p in combo.split("+") if p.strip()]
    seen = list(dict.fromkeys(parts))
    return "+".join(sorted(seen, key=lambda p: (_MODIFIER_ORDER.get(p, 99), p)))


def _expand(part: str) -> set[str]:
    return KEY_ALIASES.get(part, {part})


class DictationController:
    """Zustandsmaschine. Callbacks:
    on_start()  -> Aufnahme starten
    on_stop()   -> Aufnahme stoppen und verarbeiten
    on_cancel() -> Aufnahme verwerfen (versehentlicher Einzeltipp)
    on_lock()   -> Freisprechen aktiviert (nur UI-Feedback)
    on_arm()    -> kurzer Tipp, Tipp-Fenster laeuft (nur UI-Feedback:
                   die Pille deutet mit einem Ringbogen an, dass ein
                   zweiter Tipp jetzt Freisprechen bedeutet)
    """

    IDLE, HOLD, ARMED, LOCKED, STOPPING = "idle", "hold", "armed", "locked", "stopping"

    def __init__(self, on_start, on_stop, on_cancel=None, on_lock=None,
                 mode: str = "both", tap_max_s: float = 0.35,
                 double_tap_window_s: float = 0.40, toggle_guard_s: float = 0.40,
                 clock=time.monotonic, on_arm=None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel or on_stop
        self.on_lock = on_lock or (lambda: None)
        self.on_arm = on_arm or (lambda: None)
        self.mode = mode
        self.tap_max_s = tap_max_s
        self.double_tap_window_s = double_tap_window_s
        # Nur Modus "toggle": Druecke, die schneller als toggle_guard_s auf
        # den letzten Start/Stopp folgen, zaehlen nicht. Ohne diese Sperre
        # beendete ein prellender Taster oder ein reflexhafter Doppeltipp
        # die Aufnahme sofort wieder (im Log: 200-350 ms lange Aufnahmen),
        # bzw. startete nach dem Stopp-Druck gleich die naechste. Eine
        # Aufnahme unter 0,4 s wird ohnehin verworfen (min_duration_s),
        # der Nutzer verliert also nichts.
        self.toggle_guard_s = toggle_guard_s
        self._t_toggle = None  # Zeitpunkt des letzten Toggle-Start/Stopps
        self._clock = clock
        self._state = self.IDLE
        self._t_down = 0.0
        self._armed_timer: threading.Timer | None = None
        self._lock = threading.RLock()
        # Wer (welcher Hook) die laufende Aufnahme gestartet hat. Mit ZWEI
        # parallelen Diktat-Hotkeys darf das Loslassen des NICHT haltenden
        # Hotkeys die Aufnahme sonst stoppen/verwerfen (combo_up misst die
        # Haltezeit des falschen Drucks).
        self._owner = None

    @property
    def state(self) -> str:
        return self._state

    def _cancel_timer(self):
        if self._armed_timer is not None:
            self._armed_timer.cancel()
            self._armed_timer = None

    def _toggle_bounce(self) -> bool:
        """True, wenn dieser Druck im Toggle-Modus zu dicht auf den letzten
        Start/Stopp folgt und ignoriert werden soll."""
        if self.mode != "toggle":
            return False
        now = self._clock()
        if self._t_toggle is not None and (now - self._t_toggle) < self.toggle_guard_s:
            log.info("Toggle: Druck %.0f ms nach dem letzten ignoriert "
                     "(Tastenprellen/Doppeltipp)", (now - self._t_toggle) * 1000)
            return True
        self._t_toggle = now
        return False

    def combo_down(self, owner=None):
        with self._lock:
            if self._state == self.IDLE:
                if self._toggle_bounce():
                    return
                self._owner = owner
                self._t_down = self._clock()
                self._state = self.LOCKED if self.mode == "toggle" else self.HOLD
                self.on_start()
            elif self._state == self.ARMED:
                # zweiter Tipp innerhalb des Fensters -> Freisprechen
                # (auch vom anderen Hotkey erlaubt; er uebernimmt die Aufnahme)
                self._cancel_timer()
                self._owner = owner
                self._state = self.LOCKED
                self.on_lock()
            elif self._state == self.LOCKED:
                # Druck beendet das Freisprechen / den Toggle (jeder Hotkey darf)
                if self._toggle_bounce():
                    return
                self._state = self.STOPPING
                self.on_stop()

    def combo_up(self, owner=None):
        with self._lock:
            if self._state == self.HOLD:
                if owner is not self._owner:
                    return  # fremder Hotkey: sein Druck hat nichts gestartet
                held = self._clock() - self._t_down
                if self.mode == "both" and held < self.tap_max_s:
                    # kurzer Tipp: auf zweiten Tipp warten, Aufnahme laeuft weiter
                    self._state = self.ARMED
                    self._armed_timer = threading.Timer(self.double_tap_window_s,
                                                        self._armed_timeout)
                    self._armed_timer.daemon = True
                    self._armed_timer.start()
                    self.on_arm()
                else:
                    self._state = self.IDLE
                    self.on_stop()
            elif self._state == self.STOPPING:
                self._state = self.IDLE
            # LOCKED: Loslassen des zweiten Tipps ignorieren

    def _armed_timeout(self):
        with self._lock:
            if self._state == self.ARMED:
                # Einzeltipp ohne zweiten Tipp: versehentlich -> verwerfen
                self._state = self.IDLE
                self.on_cancel()

    def force_stop(self):
        """Von aussen stoppen (z.B. Toggle-Hotkey oder Fehlerfall)."""
        with self._lock:
            self._cancel_timer()
            self._owner = None
            if self._state in (self.HOLD, self.ARMED, self.LOCKED):
                self._state = self.IDLE
                self.on_stop()

    def start_locked(self):
        """Von aussen direkt im Freisprech-Modus starten (Toggle-Hotkey)."""
        with self._lock:
            if self._state == self.IDLE:
                self._owner = None
                self._state = self.LOCKED
                self.on_start()
                self.on_lock()
