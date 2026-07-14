"""Flow-Bar: kleine schwarze Pill am unteren Bildschirmrand, monochrom.

- Aufnahme: dezent pulsierender Punkt + live Waveform (weiss, aeltere Balken
  ausgegraut), die sanft mit Sub-Pixel-Scroll nach links laeuft.
- Freisprechen: der Punkt morpht in einen Ring (mit kleinem Bestaetigungs-Puls).
- Verarbeitung: drei weich wandernde Dots. Beim Uebergang kollabiert die
  Waveform in die Mittellinie, waehrend die Pill-Breite auf das schmale
  Format tweent - kein harter Sprung mehr.
- Alle State-Wechsel sind choreografiert: Breite tweent (Ease-in-out), der
  alte Inhalt faded aus, der neue faded ein (sequenziell statt ueberlappend,
  weil Canvas-Items opak sind). Fake-Alpha geht ueber Farb-Mix Richtung
  Pill-Hintergrund - moeglich, weil alles monochrom auf Schwarz liegt.
- Das Fenster hat eine FESTE Groesse und wird nur beim Einblenden einmal
  positioniert (Monitor dabei gelatcht). Slide, Breiten-Morph und Fades
  laufen komplett im Canvas - kein geometry()-Call pro Frame, der
  Fenstermanager ruckelt nicht mit, die Pill teleportiert nicht bei
  Fokuswechsel auf einen anderen Monitor.
- Animationen sind zeitbasiert (dt), nicht frame-gebunden: ein verspaeteter
  Tick laesst nichts springen.
- Ein Hide-Request wird erst nach einer Mindest-Sichtbarkeit ausgefuehrt,
  damit ultrakurze Diktate nicht als Blitz erscheinen.

Eine Akzentfarbe existiert bewusst nicht - alle States sind
schwarz/weiss/grau (Nutzerwunsch: weniger Farben, kleiner).
"""

import collections
import ctypes
import logging
import math
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

# Choreografie/Timing/Farben sind plattformneutral in overlay_model.py -
# geteilt mit dem AppKit-Overlay (platform/darwin/overlay.py).
from .overlay_model import (
    BAR_SPAN, BAR_STEP, BAR_W, BOTTOM_MARGIN, EXPAND_MAX_LINES, EXPAND_S,
    EXPAND_VPAD, FONT_SIZE, GLASS_ALPHA, H, HIDE_S, MAX_TEXT_PX,
    MIN_VISIBLE_S, MORPH_S, N_BARS, PAD_BOTTOM, PAD_TOP, SHOW_S, SLIDE_PX,
    SOLID_ALPHA, TEXT_STATES, THEMES, TICK_MS, WAVE_DT, WAVE_LEFT,
    WAVE_STATES, PAD_R, Tween as _Tween, clamp as _clamp,
    ease_in_out as _ease_in_out, ease_out as _ease_out,
    ease_out_back as _ease_out_back, fit_text_tail as _fit_text_tail,
    mix as _mix, smooth as _smooth, wrap_text as _wrap_text,
)

log = logging.getLogger("localflow.overlay")

TRANS = "#010102"          # Transparenz-Schluesselfarbe (kommt sonst nicht vor)


_IVDM_CLASS = None  # lazy definiertes comtypes-Interface (einmal pro Prozess)


def _vdm():
    """IVirtualDesktopManager-Instanz (dokumentierte Shell-COM-API)."""
    global _IVDM_CLASS
    import comtypes
    from ctypes import HRESULT, POINTER
    from ctypes.wintypes import BOOL, HWND
    from comtypes import COMMETHOD, GUID, IUnknown

    if _IVDM_CLASS is None:
        class IVirtualDesktopManager(IUnknown):
            _iid_ = GUID("{a5cd92ff-29be-454c-8d04-d82879fb3f1b}")
            _methods_ = [
                COMMETHOD([], HRESULT, "IsWindowOnCurrentVirtualDesktop",
                          (["in"], HWND, "topLevelWindow"),
                          (["out"], POINTER(BOOL), "onCurrentDesktop")),
                COMMETHOD([], HRESULT, "GetWindowDesktopId",
                          (["in"], HWND, "topLevelWindow"),
                          (["out"], POINTER(GUID), "desktopId")),
                COMMETHOD([], HRESULT, "MoveWindowToDesktop",
                          (["in"], HWND, "topLevelWindow"),
                          (["in"], POINTER(GUID), "desktopId")),
            ]
        _IVDM_CLASS = IVirtualDesktopManager

    comtypes.CoInitialize()  # idempotent pro Thread
    return comtypes.CoCreateInstance(
        GUID("{aa509086-5ca9-4c25-8f95-589d3c07b48a}"), interface=_IVDM_CLASS)


def _ensure_on_current_desktop(hwnd):
    """Virtuelle Desktops: eine Topmost-Pill "klebt" auf dem Desktop, auf dem
    sie erzeugt wurde - wechselt der Nutzer den Desktop (Win+Strg+Pfeil),
    diktiert er mit fuer ihn unsichtbarer Pill (Feldbefund 2026-07-14:
    Fenster gesund, alpha korrekt, Inhalt gezeichnet, Nutzer sieht nichts).
    Beim Einblenden daher pruefen und notfalls auf den Desktop des gerade
    fokussierten Fensters umziehen. Best-Effort: comtypes ist ohnehin
    Windows-Dependency, Fehler duerfen das Einblenden nie stoppen."""
    if not hwnd:
        return
    try:
        vdm = _vdm()
        if vdm.IsWindowOnCurrentVirtualDesktop(hwnd):
            return
        fg = ctypes.windll.user32.GetForegroundWindow()
        if not fg:
            return
        vdm.MoveWindowToDesktop(hwnd, vdm.GetWindowDesktopId(fg))
        log.info("Pill war auf einem anderen virtuellen Desktop - auf den "
                 "aktuellen verschoben")
    except Exception:  # noqa: BLE001
        log.debug("Virtual-Desktop-Pruefung fehlgeschlagen", exc_info=True)


def _assert_topmost(hwnd):
    """Topmost-Status real durchsetzen. Windows wirft Fenster gelegentlich
    aus dem Topmost-Band (Vollbild-/Video-Apps), waehrend das
    WS_EX_TOPMOST-Bit gesetzt bleibt - die Pill rendert dann unsichtbar
    HINTER normalen Fenstern weiter (Feldbefund 2026-07-14: Pill mit
    topmost=True auf z=3 unter zwei maximierten Chrome-Fenstern; App-seitig
    war alles korrekt). Tk setzt -topmost nur einmal beim Start, deshalb
    hier bei jedem Einblenden und periodisch waehrend der Sichtbarkeit
    nachdruecken."""
    if not hwnd:
        return
    try:
        # HWND_TOPMOST=-1 als echter Pointer (nacktes int -1 ist auf 64-bit
        # kein zuverlaessiger HWND); SWP_NOSIZE|NOMOVE|NOACTIVATE|NOOWNERZORDER
        ctypes.windll.user32.SetWindowPos(hwnd, ctypes.c_void_p(-1),
                                          0, 0, 0, 0, 0x0213)
    except Exception:  # noqa: BLE001
        log.debug("Topmost-Nachdruck fehlgeschlagen", exc_info=True)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _active_monitor_work_area() -> tuple[int, int, int, int]:
    """Arbeitsflaeche des Monitors mit dem fokussierten Fenster
    (Multi-Monitor: die Pill erscheint dort, wo diktiert wird)."""
    user32 = ctypes.windll.user32
    try:
        hwnd = user32.GetForegroundWindow()
        hmon = user32.MonitorFromWindow(hwnd, 1)  # MONITOR_DEFAULTTOPRIMARY
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
    except Exception:  # noqa: BLE001
        pass
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# Watchdog: erkennt eine gestorbene Overlay-Thread (Heartbeat) und startet
# die Pill neu. Feldbefund 2026-07-13: Fenster existierte noch (alpha=0,
# Styles ok), aber die root.after-Tick-Kette war tot - Sounds/Diktat liefen
# weiter, UI unsichtbar. Tk auf einem Worker-Thread kann durch extern
# zerstoerte Fenster (Display-Wechsel, RDP, Session-Events) so enden.
WATCHDOG_CHECK_S = 5.0     # Pruefintervall
WATCHDOG_MISSES = 2        # so viele stale-Checks in Folge = tot (schuetzt
                           # gegen Fehlalarm direkt nach Standby-Aufwachen)


class Overlay:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._hb = {"t": 0.0}      # letzter Tick (perf_counter) der Overlay-Thread
        self._hwnd_box = {"hwnd": None}  # HWND der aktuellen Pill (fuer Aufraeumen)
        self._last = {}            # zuletzt gesetzte Werte (Replay nach Neustart)
        self._gen = 0
        self._thread = None
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        self._launch()
        threading.Thread(target=self._watch, daemon=True,
                         name="localflow-overlay-watchdog").start()

    def _launch(self):
        self._gen += 1
        # Frische Objekte pro Generation: eine evtl. noch zuckende alte
        # Thread haelt ihre eigenen (verwaisten) Captures und kann weder
        # die neue Queue leeren noch den neuen Heartbeat faelschen.
        self._hb = {"t": time.perf_counter()}
        self._hwnd_box = {"hwnd": None}
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"localflow-overlay-{self._gen}")
        self._thread.start()

    def _watch(self):
        """Heartbeat pruefen; bleibt er WATCHDOG_MISSES Checks in Folge stehen,
        gilt die Overlay-Thread als tot: Zombie-Fenster verstecken, Queue
        austauschen (die tote Thread haelt evtl. noch die alte) und die Pill
        mit den gemerkten Design-Einstellungen neu starten."""
        misses = 0
        while True:
            time.sleep(WATCHDOG_CHECK_S)
            stale = time.perf_counter() - self._hb["t"]
            if stale < WATCHDOG_CHECK_S * 1.5:
                misses = 0
                continue
            misses += 1
            if misses < WATCHDOG_MISSES:
                continue  # z.B. Aufwachen aus Standby: naechster Check entscheidet
            misses = 0
            log.warning("Overlay-Thread tot (letzter Tick vor %.0fs) - starte die "
                        "Pill neu", stale)
            self._hide_zombie_window()
            self._queue = queue.Queue()
            self._launch()
            self._replay_settings()

    def _hide_zombie_window(self):
        """Fenster einer toten Overlay-Thread unsichtbar machen (reines Win32,
        braucht kein lebendes Tk). Verhindert einen eingefrorenen Pill-Geist,
        falls die Thread mitten in einer sichtbaren Phase starb."""
        hwnd = self._hwnd_box.get("hwnd")
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            if user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, 0)  # SW_HIDE
        except Exception:  # noqa: BLE001
            log.debug("Zombie-Fenster verstecken fehlgeschlagen", exc_info=True)

    def _replay_settings(self):
        """Design + aktuellen Zustand in die frische Pill spielen (sonst kaeme
        sie mit Defaults zurueck: dunkles Thema, Standardschrift, hidden)."""
        last = self._last
        if "glass" in last:
            self._queue.put(("glass", last["glass"]))
        if "style" in last:
            self._queue.put(("style", last["style"]))
        if "theme" in last:
            self._queue.put(("theme", last["theme"]))
        # Reihenfolge: state VOR text - ein frischer Show loescht das
        # Transkript, der Replay-Text kommt danach wieder rein.
        if last.get("state") not in (None, "hidden"):
            self._queue.put(("state", last["state"]))
            if last.get("text"):
                self._queue.put(("text", last["text"]))

    def set_state(self, state: str):
        # Breadcrumb auf INFO: macht die State-Timeline im Log sichtbar
        # (Feldbefund 2026-07-14: Pill haengt sichtbar ohne erkennbaren
        # Grund - ohne Timeline ist so etwas nicht diagnostizierbar).
        if state != self._last.get("state"):
            log.info("Overlay-State: %s -> %s", self._last.get("state", "-"), state)
        self._last["state"] = state
        if state not in WAVE_STATES:
            self._last["text"] = ""  # Preview-Text gehoert nur zur Aufnahme
        self._queue.put(("state", state))

    def set_level(self, level: float):
        """Adaptiver Mikrofonpegel 0..1 (siehe audio.LevelMeter)."""
        self._queue.put(("level", level))

    def set_text(self, text: str):
        """Live-Transkript fuer die Aufnahme-Anzeige. Wird nur in den
        WAVE_STATES (recording/locked) gezeichnet; leer = Waveform zeigen."""
        self._last["text"] = text or ""
        self._queue.put(("text", text or ""))

    def set_glass(self, enabled: bool):
        """Glas-Optik an/aus: durchscheinende Pille (Desktop schimmert durch)."""
        self._last["glass"] = bool(enabled)
        self._queue.put(("glass", bool(enabled)))

    def set_style(self, font_family: str | None = None, font_size: int | None = None):
        """Schriftart/-groesse der Pille live setzen (Widget-Design)."""
        self._last["style"] = (font_family, font_size)
        self._queue.put(("style", (font_family, font_size)))

    def set_theme(self, theme: str):
        """Farb-Thema der Pille: "dark" (Standard) oder "light"."""
        self._last["theme"] = theme
        self._queue.put(("theme", theme))

    # ------------------------------------------------------------------ Tk

    def _run(self):
        """Traegerfunktion der Overlay-Thread: loggt den Todesgrund - vor der
        Watchdog-Einfuehrung starb die Thread bei pythonw voellig lautlos."""
        try:
            self._run_tk()
            log.warning("Overlay-Mainloop hat sich beendet (Tk-Fenster weg?)")
        except Exception:  # noqa: BLE001
            log.warning("Overlay-Thread gestorben", exc_info=True)

    def _run_tk(self):
        # Lokale Captures der Generations-Objekte (siehe _launch)
        q = self._queue
        hb = self._hb
        hwnd_box = self._hwnd_box

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=TRANS)
        try:
            root.attributes("-transparentcolor", TRANS)
        except tk.TclError:
            pass

        canvas = tk.Canvas(root, bg=TRANS, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        font = tkfont.Font(family="Segoe UI", size=FONT_SIZE, weight="bold")

        st = {
            "target": "hidden",    # zuletzt gewuenschter State
            "vis": "recording",    # gezeichneter State (bleibt beim Fade-out)
            "prev": None,          # alter State waehrend des Content-Fades
            "level": 0.0,
            "smooth": 0.0,
            "text": "",            # Live-Transkript (nur in WAVE_STATES gezeigt)
            "shown": False,        # laeuft gerade eine Sicht-Session?
            "shown_at": 0.0,       # Beginn der aktuellen Sichtbarkeit
            "state_t0": 0.0,       # Phasen-Anker (Dots/Spinner) des vis-States
            "wave_acc": 0.0,
            "scroll": 0.0,
            "win_alpha": -1.0,     # zuletzt gesetztes Fenster-Alpha
            "fine": False,         # feine Timer-Aufloesung aktiv?
            "hwnd": None,          # Overlay-Fenster (fuer Hover-Erkennung)
            "pill_scr": None,      # Pill-Rechteck in Bildschirm-Px (letzter Frame)
            "glass": False,        # Glas-Optik: durchscheinende Pille
            "col": THEMES["dark"],  # aktives Farb-Thema (set_theme)
            "top_ts": 0.0,         # letzter Topmost-Nachdruck (_assert_topmost)
        }

        def content_width(state: str) -> float:
            if state in WAVE_STATES:
                # Mit Live-Text waechst die Pill mit dem Text (bis MAX_TEXT_PX),
                # ohne Text zeigt sie die Waveform in fester Breite.
                if st["text"]:
                    tw = min(font.measure(st["text"]) + 6, MAX_TEXT_PX)
                    return WAVE_LEFT + tw + PAD_R
                return WAVE_LEFT + BAR_SPAN + PAD_R
            if state == "processing":
                return 64
            if state == "loading":
                return 14 + 12 + 8 + font.measure("Lade Modelle …") + 14
            if state == "clipboard":
                return 14 + font.measure("Text im Clipboard – Strg+V") + 14
            if state == "error":
                return 14 + 7 + 8 + font.measure("Fehler") + 14
            return 100

        def fit_text_tail(s: str, max_px: float) -> str:
            return _fit_text_tail(s, max_px, font.measure)

        def wrap_text(s: str, max_px: float) -> list[str]:
            return _wrap_text(s, max_px, font.measure)

        st["line_h"] = font.metrics("linespace") + 3

        # Fenster so breit wie der breiteste State inkl. voller Text-Zone (+Luft).
        # Die Hoehe fasst die MAXIMAL ausgeklappte Pille - das Fenster ist
        # transparent/click-through, der leere Bereich oben stoert also nicht.
        # Die Pille wird UNTEN im Fenster verankert und waechst beim Hover nach
        # oben; eingeklappt sitzt sie exakt an der alten Position. Grosszuegig
        # fuer die groesste erlaubte Schrift, weil die Schrift live umstellbar ist.
        base_w = max(content_width(s) for s in WAVE_STATES + ("processing",) + TEXT_STATES)
        max_w = int(max(base_w, WAVE_LEFT + MAX_TEXT_PX + PAD_R)) + 8
        # 48 px/Zeile = Worst Case bei Schriftgroesse 20 + DPI-Skalierung
        # (Schrift ist live umstellbar, das Fenster nicht - grosszuegig sein).
        expand_max_h = 2 * EXPAND_VPAD + EXPAND_MAX_LINES * 48
        win_h = int(max(PAD_TOP + H, expand_max_h) + SLIDE_PX + PAD_BOTTOM + 6)
        canvas.configure(width=max_w, height=win_h)

        width = _Tween(content_width("recording"), _ease_in_out)
        expand = _Tween(0.0, _ease_in_out)   # 0 = eingeklappt, 1 = ausgeklappt
        fade = _Tween(1.0, lambda p: p)      # linear; Haelften via _smooth
        ring = _Tween(0.0, _ease_in_out)     # 0 = Punkt, 1 = Ring (locked)
        # Slide und Alpha sind kontinuierliche Tweens: ein Hide, das ein
        # laufendes Show unterbricht (Tap-dann-sofort-los), startet stetig vom
        # aktuellen Wert - kein Positionssprung durch Easing-Wechsel mehr.
        slide = _Tween(1.0, _ease_out_back)  # 1 = unten (versteckt), 0 = Ruhe
        alpha = _Tween(0.0, _ease_out)       # 0..1 globale Praesenz (Fade)
        wave = collections.deque([0.0] * N_BARS, maxlen=N_BARS)
        last = {"t": time.perf_counter()}
        stats = {"n": 0, "sum": 0.0, "max": 0.0, "t0": time.perf_counter()}

        def position_window():
            # Physische Monitor-Arbeitsflaeche (Win32) in Tk-Koordinaten
            # umrechnen: der Prozess ist DPI-aware, aber Tk-geometry/winfo_*
            # koennen in einem anderen (skalierten) Raum liegen als die
            # Win32-API. scale normalisiert beide Faelle (=1, wenn Tk ebenfalls
            # in physischen Pixeln misst) - so sitzt die Pille zentriert unten,
            # egal bei welcher Windows-Skalierung.
            try:
                phys_w = ctypes.windll.user32.GetSystemMetrics(0) or 1
                scale = root.winfo_screenwidth() / phys_w
            except Exception:  # noqa: BLE001
                scale = 1.0
            left, top, right, bottom = _active_monitor_work_area()
            x = int((left + right) / 2 * scale - max_w / 2)
            # Fenster so setzen, dass die UNTERKANTE der (eingeklappten) Pille
            # BOTTOM_MARGIN ueber dem Arbeitsflaechen-Rand sitzt - unabhaengig
            # von der Fensterhoehe, die jetzt fuers Ausklappen groesser ist.
            y = int(bottom * scale) - BOTTOM_MARGIN - win_h + PAD_BOTTOM
            root.geometry(f"{max_w}x{win_h}+{x}+{y}")

        def apply_state(new: str, now: float):
            if new == st["target"]:
                return
            st["target"] = new
            if new in ("hidden", None):
                return  # vis bleibt stehen, damit der Inhalt mit ausfadet
            old = st["vis"]
            if not st["shown"]:
                # Frisch einblenden: Fenster (unsichtbar, alpha 0) auf den
                # aktiven Monitor setzen - kein Mapping/deiconify im Hot-Path,
                # daher kein DWM-Ruckler im ersten Frame.
                position_window()
                _ensure_on_current_desktop(st["hwnd"])
                _assert_topmost(st["hwnd"])
                st["top_ts"] = now
                st["vis"], st["prev"] = new, None
                st["text"] = ""      # frisches Diktat: kein altes Transkript
                st["state_t0"] = now
                st["shown_at"] = now
                st["shown"] = True
                width.snap(content_width(new))
                fade.snap(1.0)
                ring.snap(1.0 if new == "locked" else 0.0)
                slide.snap(1.0)      # startet unten
                expand.snap(0.0)     # frisch immer eingeklappt
                wave.extend([0.0] * N_BARS)
                st["smooth"] = 0.0
                return
            if new == old:
                return
            # Sichtbarer Wechsel: Breite tweent, Inhalt wechselt weich.
            if new in WAVE_STATES and old not in WAVE_STATES:
                st["text"] = ""  # neues Diktat zeigt nie den alten Preview-Text
            st["vis"] = new
            width.to(content_width(new), MORPH_S, now)
            if {old, new} <= set(WAVE_STATES):
                # recording <-> locked: gleicher Inhalt, nur der Punkt
                # morpht in den Ring - kein Content-Fade, Phase laeuft weiter.
                ring.to(1.0 if new == "locked" else 0.0, MORPH_S, now)
            else:
                st["prev"] = old
                st["state_t0"] = now
                fade.snap(0.0)
                fade.to(1.0, MORPH_S, now)
                ring.snap(1.0 if new == "locked" else 0.0)

        def rounded_pill(x: float, y: float, w: float, h: float = H):
            r = H // 2
            if h <= H + 0.5:
                # Eingeklappt: exakt die alte Stadium-Pille (mit Rand) -
                # unveraendert, damit die Standard-Ansicht identisch bleibt.
                canvas.create_oval(x + 1, y + 1, x + 2 * r - 1, y + H - 1,
                                   fill=st["col"]["bg"], outline=st["col"]["border"])
                canvas.create_oval(x + w - 2 * r + 1, y + 1, x + w - 1, y + H - 1,
                                   fill=st["col"]["bg"], outline=st["col"]["border"])
                canvas.create_rectangle(x + r, y + 1, x + w - r, y + H - 1,
                                        fill=st["col"]["bg"], outline=st["col"]["bg"])
                canvas.create_line(x + r, y + 1, x + w - r, y + 1, fill=st["col"]["border"])
                canvas.create_line(x + r, y + H - 1, x + w - r, y + H - 1, fill=st["col"]["border"])
                return
            # Ausgeklappt (hohe Pille): abgerundetes Rechteck, gleiche Eckradien.
            canvas.create_oval(x, y, x + 2 * r, y + 2 * r, fill=st["col"]["bg"], outline="")
            canvas.create_oval(x + w - 2 * r, y, x + w, y + 2 * r, fill=st["col"]["bg"], outline="")
            canvas.create_oval(x, y + h - 2 * r, x + 2 * r, y + h, fill=st["col"]["bg"], outline="")
            canvas.create_oval(x + w - 2 * r, y + h - 2 * r, x + w, y + h,
                               fill=st["col"]["bg"], outline="")
            canvas.create_rectangle(x + r, y, x + w - r, y + h, fill=st["col"]["bg"], outline="")
            canvas.create_rectangle(x, y + r, x + w, y + h - r, fill=st["col"]["bg"], outline="")

        def draw_content(state: str, alpha: float, now: float,
                         px: float, py: float, w: float, ph: float = H):
            if alpha <= 0.01:
                return
            # cy = Mitte der UNTEREN H-Zone der Pille. Eingeklappt (ph==H) ist
            # das die alte Mitte; ausgeklappt bleiben Punkt und neueste Zeile
            # unten, waehrend der Text nach oben waechst.
            cy = py + ph - H / 2
            if state in WAVE_STATES:
                # Punkt (Aufnahme) bzw. Ring (Freisprechen); rp blendet
                # stetig zwischen beiden und macht mittig einen Mini-Puls.
                rp = ring.v
                pulse = 1 + 0.10 * math.sin((now - st["shown_at"]) * 4.5)
                r = 3.2 * pulse * (1 + 0.22 * math.sin(math.pi * rp))
                cx = px + 18
                if rp < 0.99:
                    canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                       fill=_mix(st["col"]["bg"], st["col"]["fg"], (1 - rp) * alpha),
                                       outline="")
                if rp > 0.01:
                    canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                       outline=_mix(st["col"]["bg"], st["col"]["fg"], rp * alpha),
                                       width=1.6)
                zone = max(6.0, w - WAVE_LEFT - PAD_R)
                x0 = px + WAVE_LEFT
                if st["text"] and ph > H + 1.0:
                    # Ausgeklappt: ganzer Text umgebrochen, unten-buendig -
                    # neueste Zeile unten neben dem Punkt, aeltere darueber.
                    lines = wrap_text(st["text"], zone)
                    maxn = max(1, int((ph - 2 * EXPAND_VPAD) / st["line_h"]))
                    col = _mix(st["col"]["bg"], st["col"]["fg"], 0.94 * alpha)
                    for k, ln in enumerate(reversed(lines[-maxn:])):
                        canvas.create_text(x0, cy - k * st["line_h"], text=ln,
                                           anchor="w", font=font, fill=col)
                elif st["text"]:
                    # Eingeklappt: einzeilig, Ende des Textes (neueste Woerter).
                    shown = fit_text_tail(st["text"], zone)
                    canvas.create_text(x0, cy, text=shown, anchor="w", font=font,
                                       fill=_mix(st["col"]["bg"], st["col"]["fg"], 0.94 * alpha))
                else:
                    # Mittellinie + Waveform. zone schrumpft mit der Pill-Breite,
                    # dadurch implodieren die Balken beim Morph zur Mitte hin
                    # statt ueber den Pill-Rand zu ragen.
                    scale = min(1.0, zone / BAR_SPAN)
                    canvas.create_line(x0, cy, x0 + BAR_SPAN * scale, cy,
                                       fill=_mix(st["col"]["bg"], st["col"]["fg"], 0.22 * alpha))
                    bw = max(1.0, BAR_W * scale)
                    for i, lvl in enumerate(wave):
                        h = lvl * (H - 14) / 2
                        if h < 0.5:
                            continue  # geht optisch in der Mittellinie auf
                        off = i * BAR_STEP - st["scroll"] * BAR_STEP
                        edge = _clamp((off + BAR_STEP) / 10.0)  # links weich raus
                        if edge <= 0.0:
                            continue
                        x = x0 + off * scale
                        shade = (0.45 + 0.55 * (i / (N_BARS - 1))) * edge * alpha
                        canvas.create_rectangle(x, cy - h, x + bw, cy + h,
                                                fill=_mix(st["col"]["bg"], st["col"]["fg"], shade),
                                                outline="")
            elif state == "processing":
                # Drei weich wandernde Dots (durchgehende Sinuswelle, kein
                # Halbwellen-Kleben am Boden); Phase startet beim Betreten
                # des States bei 0, alle Dots unten.
                cx = px + w / 2
                t = now - st["state_t0"]
                for i in range(3):
                    s = 0.5 + 0.5 * math.sin(t * 4.6 - i * 0.85 - math.pi / 2)
                    dy = -3.4 * s
                    rr = 2.6 + 0.5 * s
                    col = _mix(st["col"]["bg"], st["col"]["fg"], (0.32 + 0.34 * s) * alpha)
                    x = cx - 12 + i * 12
                    canvas.create_oval(x - rr, cy + dy - rr, x + rr, cy + dy + rr,
                                       fill=col, outline="")
            elif state == "loading":
                a = ((now - st["state_t0"]) * 240) % 360
                canvas.create_arc(px + 14, cy - 6, px + 26, cy + 6, start=a,
                                  extent=100, style="arc",
                                  outline=_mix(st["col"]["bg"], st["col"]["dim"], alpha), width=2)
                canvas.create_text(px + 34, cy, text="Lade Modelle …",
                                   fill=_mix(st["col"]["bg"], st["col"]["dim"], alpha),
                                   font=font, anchor="w")
            elif state == "clipboard":
                canvas.create_text(px + 14, cy, text="Text im Clipboard – Strg+V",
                                   fill=_mix(st["col"]["bg"], st["col"]["fg"], alpha),
                                   font=font, anchor="w")
            elif state == "error":
                canvas.create_oval(px + 14, cy - 3.5, px + 21, cy + 3.5,
                                   fill=_mix(st["col"]["bg"], st["col"]["dim"], alpha), outline="")
                canvas.create_text(px + 29, cy, text="Fehler",
                                   fill=_mix(st["col"]["bg"], st["col"]["fg"], alpha),
                                   font=font, anchor="w")

        def draw(now: float):
            canvas.delete("all")
            w = width.v
            px = (max_w - w) / 2
            # Pille UNTEN verankert (Slide schiebt sie beim Ein/Ausblenden runter).
            slide_off = SLIDE_PX * _clamp(slide.v, -0.25, 1.1)
            pill_bottom = (win_h - PAD_BOTTOM) + slide_off
            # Ausklapphoehe aus den umgebrochenen Zeilen. Bewusst NICHT an
            # WAVE_STATES gebunden: endet die Aufnahme mit ausgeklappter
            # Pille, klingt der expand-Tween weich aus statt hart zu springen.
            ph = float(H)
            if expand.v > 0.001 and st["text"]:
                zone = max(20.0, w - WAVE_LEFT - PAD_R)
                nlines = min(len(wrap_text(st["text"], zone)), EXPAND_MAX_LINES)
                full_h = max(float(H), 2 * EXPAND_VPAD + max(1, nlines) * st["line_h"])
                # Nie hoeher als das Fenster (Schrift ist live umstellbar,
                # die Fensterhoehe nicht - sonst wird oben hart abgeschnitten).
                full_h = min(full_h, float(win_h - PAD_BOTTOM - 2))
                ph = H + (full_h - H) * expand.v
            py = pill_bottom - ph
            rounded_pill(px, py, w, ph)

            # Sequenzieller Content-Fade: prev raus (erste Haelfte), vis rein
            # (zweite Haelfte) - Canvas-Items sind opak, ein echter Crossfade
            # wuerde dunkle Loecher stanzen.
            f = fade.v
            if st["prev"] is not None:
                a_prev = _smooth(1 - f / 0.45)
                draw_content(st["prev"], a_prev, now, px, py, w, ph)
                a_vis = _smooth((f - 0.5) / 0.5)
            else:
                a_vis = 1.0
            if st["vis"] in TEXT_STATES:
                # Text erst zeigen, wenn die Pill (fast) breit genug ist -
                # sonst raegen helle Glyphen ueber die Rundung hinaus.
                a_vis *= _clamp((w - content_width(st["vis"]) + 8) / 8)
            draw_content(st["vis"], a_vis, now, px, py, w, ph)

            # Pill-Rechteck in Bildschirm-Pixeln fuer die Hover-Erkennung merken
            # (ein Frame Verzoegerung ist unmerklich).
            try:
                r = wintypes.RECT()
                if st["hwnd"] and ctypes.windll.user32.GetWindowRect(
                        st["hwnd"], ctypes.byref(r)):
                    sx = (r.right - r.left) / max_w
                    sy = (r.bottom - r.top) / win_h
                    st["pill_scr"] = (r.left + px * sx, r.top + py * sy,
                                      r.left + (px + w) * sx, r.top + (py + ph) * sy)
            except Exception:  # noqa: BLE001
                st["pill_scr"] = None

        def tick():
            # try/finally garantiert, dass IMMER der naechste Tick geplant
            # wird - eine einzelne Exception (z.B. TclError, Monitor-API)
            # darf die Render-Kette nicht dauerhaft toeten.
            present = False
            try:
                now = time.perf_counter()
                dt = min(now - last["t"], 0.1)  # Sleep/Ruckler nicht aufholen
                last["t"] = now
                try:
                    while True:
                        kind, value = q.get_nowait()
                        if kind == "state":
                            apply_state(value, now)
                        elif kind == "level":
                            st["level"] = float(value)
                        elif kind == "text":
                            st["text"] = value
                        elif kind == "glass":
                            st["glass"] = value
                            st["win_alpha"] = -1.0  # Alpha neu anwenden erzwingen
                        elif kind == "theme":
                            st["col"] = THEMES.get(value, THEMES["dark"])
                        elif kind == "style":
                            fam, sz = value
                            try:
                                if fam:
                                    font.configure(family=str(fam))
                                if sz:
                                    font.configure(size=max(7, min(20, int(sz))))
                                st["line_h"] = font.metrics("linespace") + 3
                            except Exception:  # noqa: BLE001
                                log.debug("Schrift-Umstellung fehlgeschlagen", exc_info=True)
                except queue.Empty:
                    pass

                # Praesenz-Ziel: sichtbar solange gewuenscht, plus Anti-Blitz
                # Mindestdauer. Slide/Alpha tweenen dahin - der Zielwechsel
                # (Show<->Hide) ist immer stetig vom aktuellen Wert.
                want = st["target"] not in ("hidden", None)
                hold = st["shown"] and (now - st["shown_at"]) < MIN_VISIBLE_S
                if want or hold:
                    alpha.to(1.0, SHOW_S, now)
                    slide.to(0.0, SHOW_S, now)
                else:
                    alpha.to(0.0, HIDE_S, now)
                    slide.to(1.0, HIDE_S, now)

                alpha.update(now)
                slide.update(now)
                present = st["shown"] and (alpha.v > 0.003 or alpha.target > 0.0)

                if present:
                    if not st["fine"]:
                        try:  # feine Timer-Aufloesung nur waehrend sichtbar
                            ctypes.windll.winmm.timeBeginPeriod(1)
                        except Exception:  # noqa: BLE001
                            pass
                        st["fine"] = True
                    # Topmost periodisch nachdruecken: Windows kann die Pill
                    # auch MITTEN in einer Aufnahme aus dem Topmost-Band
                    # werfen (siehe _assert_topmost).
                    if now - st["top_ts"] > 2.0:
                        _assert_topmost(st["hwnd"])
                        st["top_ts"] = now
                    # Pegel zeitbasiert glaetten (Attack schnell, Release traege).
                    target = st["level"] if (st["vis"] in WAVE_STATES
                                             and want) else 0.0
                    tau = 0.035 if target > st["smooth"] else 0.09
                    st["smooth"] += (target - st["smooth"]) * (1 - math.exp(-dt / tau))
                    st["wave_acc"] += dt
                    while st["wave_acc"] >= WAVE_DT:
                        st["wave_acc"] -= WAVE_DT
                        wave.append(st["smooth"] if st["vis"] in WAVE_STATES else 0.0)
                    st["scroll"] = st["wave_acc"] / WAVE_DT
                    if st["vis"] not in WAVE_STATES:
                        k = math.exp(-dt / 0.055)  # verlassene Aufnahme kollabiert
                        for i in range(len(wave)):
                            wave[i] *= k

                    # Hover-Erkennung: Cursor ueber der Pille -> ausklappen.
                    # Nur bei Aufnahme mit Text. Das Fenster bleibt click-
                    # through; wir fragen nur die globale Mausposition ab und
                    # vergleichen sie mit dem gemerkten Pill-Rechteck.
                    hovering = False
                    if st["vis"] in WAVE_STATES and st["text"] and st["pill_scr"]:
                        try:
                            pt = wintypes.POINT()
                            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                                lft, top_, rgt, bot = st["pill_scr"]
                                m = 8  # Toleranz gegen Flackern am Rand
                                over = (lft - m <= pt.x <= rgt + m
                                        and top_ - m <= pt.y <= bot + m)
                                # Nur ausklappen, wenn der Text ueberhaupt mehr
                                # als eine Zeile braucht - bei wenigen Woertern
                                # gaebe es sonst nur eine fast leere grosse Pille.
                                if over and len(wrap_text(st["text"], MAX_TEXT_PX)) > 1:
                                    hovering = True
                        except Exception:  # noqa: BLE001
                            hovering = False
                    expand.to(1.0 if hovering else 0.0, EXPAND_S, now)
                    expand.update(now)

                    # Breite: mit dem Live-Text mitwachsen; beim Ausklappen auf
                    # die volle Textbreite gehen (fuer den Zeilenumbruch).
                    if st["vis"] in WAVE_STATES:
                        cw = content_width(st["vis"])
                        fw = WAVE_LEFT + MAX_TEXT_PX + PAD_R
                        width.to(cw + (fw - cw) * expand.v, 0.14, now)
                    width.update(now)
                    ring.update(now)
                    if fade.update(now) >= 1.0:
                        st["prev"] = None
                    draw(now)

                    base = GLASS_ALPHA if st["glass"] else SOLID_ALPHA
                    a = base * _clamp(alpha.v)
                    if abs(a - st["win_alpha"]) > 0.004:
                        root.attributes("-alpha", a)
                        st["win_alpha"] = a

                    if log.isEnabledFor(logging.DEBUG):
                        stats["n"] += 1
                        stats["sum"] += dt
                        stats["max"] = max(stats["max"], dt)
                        if now - stats["t0"] >= 10.0 and stats["n"]:
                            log.debug("Overlay-Frames: avg=%.1f ms, max=%.1f ms",
                                      stats["sum"] / stats["n"] * 1000,
                                      stats["max"] * 1000)
                            stats.update(n=0, sum=0.0, max=0.0, t0=now)
                elif st["shown"]:
                    # Vollstaendig aus: Session beenden (Fenster bleibt aber
                    # gemappt + click-through), Canvas leeren, Timer grob.
                    st["shown"] = False
                    st["prev"] = None
                    fade.snap(1.0)
                    canvas.delete("all")
                    if st["win_alpha"] != 0.0:
                        root.attributes("-alpha", 0.0)
                        st["win_alpha"] = 0.0
                    if st["fine"]:
                        try:
                            ctypes.windll.winmm.timeEndPeriod(1)
                        except Exception:  # noqa: BLE001
                            pass
                        st["fine"] = False
            except Exception:  # noqa: BLE001
                log.debug("Overlay-Tick fehlgeschlagen", exc_info=True)
            finally:
                hb["t"] = time.perf_counter()  # Herzschlag fuer den Watchdog
                root.after(TICK_MS if present else 30, tick)

        # Fenster EINMAL mappen und click-through machen (WS_EX_TRANSPARENT),
        # danach nie mehr deiconify/withdraw: Ein-/Ausblenden laeuft rein ueber
        # Alpha + Slide-Tween. Kein Fenster-Mapping im Hot-Path = kein
        # DWM-Ruckler im ersten Einblend-Frame. Click-through, damit die
        # (unsichtbare wie sichtbare) Pill nie Mausklicks abfaengt.
        root.attributes("-alpha", 0.0)
        root.deiconify()
        root.update_idletasks()
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
            GWL_EXSTYLE = -20
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            ex |= 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            st["hwnd"] = hwnd  # fuer die Hover-Erkennung (GetWindowRect)
            hwnd_box["hwnd"] = hwnd  # fuer den Watchdog (Zombie-Aufraeumen)
        except Exception:  # noqa: BLE001
            log.debug("Click-through-Style konnte nicht gesetzt werden", exc_info=True)

        tick()
        root.mainloop()
