"""LocalFlow - Hauptprogramm: Tray-App mit Push-to-Talk-Diktat.

Start:  .venv\\Scripts\\pythonw.exe -m localflow.main
"""

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time
import webbrowser

if sys.platform not in ("win32", "darwin"):
    # Vor den Plattform-Imports pruefen (deckt `python -m localflow.main` ab).
    raise SystemExit(f"LocalFlow: kein Backend fuer {sys.platform!r} - siehe PORTING.md")

import pystray

from . import __version__
from .appicon import make_icon
from .audio import Recorder
from .db import Database
from .overlay_model import CLIPBOARD_HOLD_S, DONE_HOLD_S, ERROR_HOLD_S, WAVE_STATES
from .pipeline import Pipeline
from .platform import get_backends
from .settings import APP_DIR, Settings

log = logging.getLogger("localflow")


# Bleibt bewusst global offen: faulthandler schreibt beim Absturz direkt in
# diesen Dateideskriptor, ein geschlossenes/GC-tes Objekt wuerde die Diagnose
# genau dann verschlucken, wenn man sie braucht.
_crash_file = None


def _error_reason(exc: BaseException) -> str:
    """Kurzer, lesbarer Grund fuer die Fehler-Pille (max. ~28 Zeichen)."""
    msg = (str(exc) or exc.__class__.__name__).splitlines()[0].strip()
    low = msg.lower()
    if "modelle nicht" in low:
        return "Modelle nicht geladen"
    if "cuda" in low or "cublas" in low or "out of memory" in low:
        return "GPU-Fehler"
    if "ollama" in low or "11434" in low:
        return "Ollama nicht erreichbar"
    if any(w in low for w in ("portaudio", "audio", "device", "mikro", "microphone")):
        return "Kein Mikrofon"
    return msg[:28] + ("…" if len(msg) > 28 else "")


def setup_crash_log():
    """Native Abstuerze und stille Thread-Exceptions sichtbar machen.

    Feldbefund 2026-08-26: die App verschwand ohne eine einzige Zeile im Log.
    Windows meldete APPCRASH 0xc0000374 (Heap-Korruption in einer nativen
    Erweiterung) - so etwas faengt kein `except Exception`. Unter pythonw.exe
    gibt es zudem KEIN stderr, d.h. jeder Traceback ging bisher ins Leere.
    Beides landet ab jetzt in logs/crash.log:
      * faulthandler -> C-Level-Stack ALLER Threads im Moment des Absturzes
      * sys.stderr   -> Tracebacks, die an der Logging-Konfiguration vorbeigehen
      * excepthooks  -> unbehandelte Exceptions in Haupt- und Worker-Threads
    """
    global _crash_file
    path = os.path.join(APP_DIR, "logs", "crash.log")
    try:
        _crash_file = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return
    _crash_file.write("\n===== Start %s pid=%d v%s =====\n"
                      % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), __version__))
    faulthandler.enable(file=_crash_file, all_threads=True)
    if sys.stderr is None:  # pythonw.exe: sonst gehen Tracebacks verloren
        sys.stderr = _crash_file

    def _hook(exc_type, exc, tb, thread=None):
        where = f" in Thread {thread.name}" if thread is not None else ""
        log.critical("Unbehandelte Exception%s", where, exc_info=(exc_type, exc, tb))

    sys.excepthook = _hook
    threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback,
                                           a.thread)


def setup_logging():
    os.makedirs(os.path.join(APP_DIR, "logs"), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(APP_DIR, "logs", "localflow.log"),
        maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.environ.get("LOCALFLOW_DEBUG") == "1" else logging.INFO)
    root.addHandler(handler)
    if sys.stdout is not None:  # bei pythonw.exe gibt es kein stdout
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    setup_crash_log()


class LocalFlowApp:
    def __init__(self):
        self.backends = get_backends()
        self.settings = Settings()
        self.db = Database()
        self.pipeline = Pipeline(self.settings, self.db)
        self.overlay = self.backends.make_overlay()
        self.last_level = 0.0
        self.recorder = Recorder(device=self.settings.get("audio_device"),
                                 level_callback=self._on_level)
        self.ducker = self.backends.make_ducker(duck_volume=self.settings.get("duck_volume"))
        self.paused = False
        self._user_paused = False           # vom Tray gesetzt (getrennt von Capture-Pause)
        self._capture_count = 0
        self._capture_lock = threading.Lock()
        # Verwaist-Wächter: merkt sich den zuletzt gesendeten Overlay-State
        # und wie viele _process-Jobs laufen (Feldbefund 2026-07-14: Pill
        # hing minutenlang sichtbar, obwohl nichts mehr lief).
        self._overlay_state = "hidden"
        self._overlay_state_ts = 0.0
        self._jobs = 0
        self._jobs_lock = threading.Lock()
        self.models_ready = threading.Event()
        self._record_start_ts = 0.0
        self._record_start_mono = 0.0
        self._record_session = 0
        self._watchdog_timer: threading.Timer | None = None
        self.controller = None
        self.ptt = None
        self.ptt2 = None                     # optionaler zweiter Diktat-Hotkey
        self._toggle_hotkey = None
        self._fullscreen_logged = False     # 1 Log-Zeile pro Vollbild-Phase, kein Spam
        self.tray: pystray.Icon | None = None
        self._tray_variant = "ready"         # zuletzt gesetzte Icon-Variante

    # --- Lebenszyklus ---

    def start(self):
        self.backends.sounds.ensure_sounds()
        threading.Thread(target=self._ensure_shortcut, daemon=True).start()
        self.overlay.start()
        self.overlay.set_glass(self.settings.get("glass_pill"))
        self.overlay.set_style(self.settings.get("overlay_font"),
                               self.settings.get("overlay_font_size"))
        self.overlay.set_theme(self.settings.get("overlay_theme"))
        self.overlay.set_position(self.settings.get("overlay_position"))
        self.overlay.set_margin(self.settings.get("overlay_margin"))
        try:
            reduced = bool(self.backends.integration.prefers_reduced_motion())
        except Exception:  # noqa: BLE001 - Kosmetik, nie fatal
            reduced = False
        if reduced:
            log.info("Systemeinstellung 'Bewegung reduzieren' aktiv - Pille ohne Slide")
        self.overlay.set_reduced_motion(reduced)
        # Kein recorder.open() hier: der Mikrofon-Stream wird erst beim
        # Diktieren geoeffnet, damit Windows das Mikro nicht dauerhaft
        # als "in Verwendung" anzeigt.
        threading.Thread(target=self._load_models, daemon=True).start()
        threading.Thread(target=self._run_dashboard, daemon=True).start()

        self._install_hotkey()
        self._install_toggle()
        threading.Thread(target=self._overlay_orphan_guard, daemon=True,
                         name="localflow-orphan-guard").start()

        self._run_tray()  # blockiert bis Beenden

    def _ensure_shortcut(self):
        self.backends.integration.ensure_launcher_shortcut()

    def _load_models(self):
        try:
            self.pipeline.load()
            self.models_ready.set()
            log.info("Modelle bereit")
            # Laeuft gerade schon ein Diktat, zeigt die Pill noch "Lade
            # Modelle" - jetzt auf den echten Aufnahme-State weiterschalten.
            if self.recorder.is_recording:
                cstate = self.controller.state if self.controller else "hold"
                self._set_overlay_state(
                    {"locked": "locked", "armed": "armed"}.get(cstate, "recording"))
        except Exception:
            log.exception("Modell-Laden fehlgeschlagen")

    def _run_dashboard(self):
        port = self.settings.get("dashboard_port")
        try:
            from .web.app import create_app
            app = create_app(self.settings, self.db, self)
            log.info("Dashboard: http://127.0.0.1:%s", port)
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
        except Exception:  # noqa: BLE001
            # Ohne das stirbt der Daemon-Thread STUMM (pythonw hat kein
            # stderr) und "Dashboard oeffnen" zeigt eine tote Seite.
            log.exception("Dashboard-Start fehlgeschlagen (Port %s belegt?)", port)
            time.sleep(3)  # Tray existiert beim App-Start evtl. noch nicht
            self._notify("Dashboard nicht verfuegbar",
                         f"Start auf Port {port} fehlgeschlagen - siehe Log.")

    # --- Aufnahme-Steuerung ---

    def _install_hotkey(self):
        """Hotkey-Hook(s) (neu) installieren. Der DictationController wird EINMAL
        erzeugt und danach wiederverwendet - so bleibt bei einem Hotkey-Wechsel
        waehrend einer laufenden Aufnahme der Zustand erhalten und force_stop
        trifft weiter den aktiven Controller. Ein optionaler zweiter Hotkey
        (hotkey2) haengt am SELBEN Controller und laeuft damit gleichwertig
        parallel zum ersten."""
        from .controller import DictationController, normalize_combo
        if self.controller is None:
            self.controller = DictationController(
                on_start=self._on_dictate_start,
                on_stop=self._on_dictate_stop,
                on_cancel=self._on_dictate_cancel,
                on_lock=self._on_dictate_lock,
                on_arm=self._on_dictate_arm,
                mode=self.settings.get("ptt_mode"),
            )
        else:
            self.controller.mode = self.settings.get("ptt_mode")
        # Laeuft gerade eine Aufnahme, gehoert ihr Loslassen zum ALTEN Hook -
        # nach dem Tausch kaeme das up-Event nie an und die Aufnahme liefe
        # bis zum Watchdog weiter. Deshalb vor dem Tausch sauber beenden.
        if self.controller.state != "idle":
            self.controller.force_stop()
        # Beide Hooks stoppen und frisch aufsetzen.
        for attr in ("ptt", "ptt2"):
            if getattr(self, attr) is not None:
                getattr(self, attr).stop()
                setattr(self, attr, None)
        swallow = self.settings.get("swallow_mouse_hotkey")
        primary = (self.settings.get("hotkey") or "").strip()
        if primary:
            self.ptt = self.backends.make_ptt(primary, self.controller,
                                              swallow_mouse=swallow,
                                              gate=self._hotkey_gate)
            self.ptt.start()
        # Zweiter Hotkey nur, wenn gesetzt UND nicht identisch zum ersten
        # (sonst wuerden zwei Hooks dieselbe Kombination doppelt melden).
        second = (self.settings.get("hotkey2") or "").strip()
        if second and (not primary or normalize_combo(second) != normalize_combo(primary)):
            self.ptt2 = self.backends.make_ptt(second, self.controller,
                                               swallow_mouse=swallow,
                                               gate=self._hotkey_gate)
            self.ptt2.start()

    def _hotkey_gate(self) -> bool:
        """Darf ein Hotkey-Druck gerade etwas ausloesen? False im Spiel /
        in einer Vollbild-App (Option pause_in_fullscreen). Wird NUR beim
        Tastendruck gefragt - kein Polling, kein Thread, kein Zustand
        ausser einer Log-Bremse. Liest das Setting live, damit die
        Tray-Checkbox/Dashboard-Aenderung sofort wirkt."""
        if not self.settings.get("pause_in_fullscreen"):
            self._fullscreen_logged = False
            return True
        try:
            blocked = self.backends.integration.is_fullscreen_app_active()
        except Exception:  # noqa: BLE001 - Erkennung darf das Diktat nie sperren
            log.debug("Vollbild-Erkennung fehlgeschlagen", exc_info=True)
            return True
        if blocked:
            if not self._fullscreen_logged:
                self._fullscreen_logged = True
                # NICHT direkt loggen: das Gate laeuft im WH_MOUSE_LL-Hook-
                # Thread, und ein log.info nimmt das Handler-Lock + schreibt
                # die Datei. Haengt gerade ein anderer Thread im Log (Rotation,
                # langsame Platte), stuende der Maus-Hook - Windows entfernt
                # Low-Level-Hooks, die zu lange brauchen. Ausgelagert, und
                # das nur einmal pro Vollbild-Phase.
                threading.Thread(
                    target=log.info, daemon=True, name="localflow-fullscreen-log",
                    args=("Vollbild-App im Vordergrund - Diktat-Hotkey pausiert "
                          "(Option 'Im Spiel pausieren')",)).start()
        else:
            self._fullscreen_logged = False
        return not blocked

    def _remove_toggle(self):
        if self._toggle_hotkey is not None:
            try:
                self.backends.remove_hotkey(self._toggle_hotkey)
            except (KeyError, ValueError):
                pass
            self._toggle_hotkey = None

    def _install_toggle(self):
        """Toggle-Hotkey (neu) registrieren - inkl. Entfernen des alten, damit
        eine Aenderung im Dashboard sofort wirkt (nicht erst nach Neustart)."""
        self._remove_toggle()
        combo = (self.settings.get("toggle_hotkey") or "").strip()
        if combo:
            try:
                self._toggle_hotkey = self.backends.add_hotkey(combo, self._on_toggle)
            except Exception:  # noqa: BLE001 - ungueltige Combo darf nicht crashen
                log.warning("Toggle-Hotkey %r konnte nicht registriert werden", combo)

    def _set_overlay_state(self, state: str):
        """Einziger Weg, den Overlay-State zu setzen - der Verwaist-Wächter
        braucht den zuletzt gesendeten Zustand samt Zeitstempel."""
        self._overlay_state = state
        self._overlay_state_ts = time.monotonic()
        self.overlay.set_state(state)
        self._update_tray_icon()

    def _update_tray_icon(self):
        """Tray-Icon spiegelt den Zustand: Pause grau, Aufnahme invertiert
        (weisse Scheibe), sonst orange. Nur bei echtem Wechsel neu setzen -
        Shell_NotifyIcon soll nicht pro Overlay-Event feuern."""
        if self._user_paused:
            variant = "paused"
        elif self._overlay_state in WAVE_STATES:
            variant = "recording"
        else:
            variant = "ready"
        if variant == self._tray_variant or self.tray is None:
            return
        self._tray_variant = variant
        tray = self.tray

        def apply():
            try:
                tray.icon = make_icon(variant=variant)
            except Exception:  # noqa: BLE001 - Kosmetik, nie fatal
                log.debug("Tray-Icon-Wechsel fehlgeschlagen", exc_info=True)
        # Wird aus Hotkey-/Worker-Threads gerufen; auf macOS setzt pystray das
        # Bild per AppKit im Aufrufer-Thread -> auf den Main-Thread marshallen.
        try:
            self.backends.integration.run_on_main(apply)
        except Exception:  # noqa: BLE001
            log.debug("Tray-Icon-Wechsel nicht einreihbar", exc_info=True)

    def _overlay_orphan_guard(self):
        """Sicherheitsnetz: zeigt die Pill einen Nicht-hidden-Zustand, obwohl
        seit 15s weder Aufnahme noch Verarbeitung laeuft, zwangsverstecken
        und WARNING loggen. Faengt verlorene hidden-Uebergaenge ab, egal wo
        sie verloren gingen."""
        while True:
            time.sleep(5)
            try:
                if self._overlay_state in ("hidden", None):
                    continue
                if self.recorder.is_recording or self._jobs > 0:
                    continue
                idle_s = time.monotonic() - self._overlay_state_ts
                if idle_s < 15:
                    continue
                log.warning("Overlay-Zustand %r verwaist (seit %ds keine "
                            "Aufnahme/Verarbeitung) - verstecke Pill",
                            self._overlay_state, int(idle_s))
                self._set_overlay_state("hidden")
            except Exception:  # noqa: BLE001 - Wächter darf nie sterben
                log.debug("Orphan-Guard-Fehler", exc_info=True)

    def _on_level(self, level: float):
        self.last_level = level
        self.overlay.set_level(level)

    def _on_dictate_start(self):
        if self.paused or self.recorder.is_recording:
            return
        try:
            self._record_start_ts = time.time()
            self._record_start_mono = time.monotonic()
            self._record_session += 1
            if self.settings.get("duck_audio"):
                self.ducker.duck()
            device_override = None
            if self.settings.get("couchmic_enabled"):
                from . import couchmic
                if couchmic.active(self.settings.get("couchmic_url") or couchmic.DEFAULT_URL):
                    device_override = self.settings.get("couchmic_device") or couchmic.DEFAULT_DEVICE
                    log.info("CouchMic aktiv: Aufnahme vom iPad (%s)", device_override)
            self.recorder.start(device_override)
            # Badge in der Pille: "iPad", wenn die Aufnahme ueber CouchMic laeuft.
            self.overlay.set_source("ipad" if device_override else "pc")
            self._arm_max_duration_watchdog(self._record_session)
            if self.settings.get("play_sounds"):
                self.backends.sounds.play("start")
            # Preview-Text des VORIGEN Diktats loeschen, bevor die Pille
            # wieder auf recording geht (Queue ist geordnet: text vor state).
            self.overlay.set_text("")
            self._set_overlay_state("recording" if self.models_ready.is_set() else "loading")
            # Bubble nach laengerem Halten: nur solange die Taste wirklich
            # gehalten wird (Controller-Zustand hold), nicht bei Toggle/Lock.
            self.overlay.set_held(bool(self.controller and self.controller.state == "hold"))
            if self.settings.get("live_preview") and self.models_ready.is_set():
                session = self._record_session
                threading.Thread(target=self._run_preview, args=(session,),
                                 daemon=True, name="localflow-preview").start()
            # Cleanup-Modell parallel zur Aufnahme vorwaermen: ein Ollama-
            # Kaltstart (3-8s) faellt so in die Sprechzeit statt in die
            # Wartezeit nach dem Loslassen (touch ist entprellt und billig,
            # wenn das Modell schon warm ist).
            if self.settings.get("ai_cleanup") and self.pipeline.cleaner is not None:
                threading.Thread(target=self.pipeline.cleaner.touch,
                                 daemon=True, name="localflow-cleanup-touch").start()
        except Exception:
            # z.B. Mikro abgesteckt -> Aufnahme kam nicht zustande: sauber
            # zuruecksetzen, sonst blieben Apps stumm / Overlay haengt.
            log.exception("Diktat-Start fehlgeschlagen")
            self._abort_recording()

    def _abort_recording(self):
        """Alles zuruecksetzen, ohne zu verarbeiten (Fehler/Cancel)."""
        try:
            self.recorder.stop()
        except Exception:  # noqa: BLE001
            log.debug("recorder.stop im Abbruch fehlgeschlagen", exc_info=True)
        self.ducker.restore()
        self._cancel_watchdog()
        self.overlay.set_held(False)
        self._set_overlay_state("hidden")

    def _arm_max_duration_watchdog(self, session: int):
        """Auto-Stopp, wenn das Freisprechen vergessen wurde."""
        self._cancel_watchdog()
        max_s = self.settings.get("max_duration_s") or 0
        if max_s <= 0:
            return
        def check():
            if self._record_session == session and self.recorder.is_recording:
                log.info("Maximale Diktatdauer (%ss) erreicht - Auto-Stopp", max_s)
                self._notify("Diktat automatisch beendet",
                             f"Maximale Dauer ({int(max_s)} s) erreicht.")
                if self.controller:
                    self.controller.force_stop()
        self._watchdog_timer = threading.Timer(max_s, check)
        self._watchdog_timer.daemon = True
        self._watchdog_timer.start()

    def _cancel_watchdog(self):
        if self._watchdog_timer is not None:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

    def _run_preview(self, session: int):
        """Live-Vorschau: waehrend der Aufnahme wiederholt das bisher
        Gesprochene transkribieren (nur Roh-STT, kein Cleanup) und den
        Zwischenstand ins Overlay geben. Der finale, bereinigte Text kommt
        erst beim Loslassen. Bricht ab, sobald ein neues Diktat startet oder
        die Aufnahme endet."""
        MIN_SAMPLES = int(0.5 * 16000)   # erst ab ~0.5s Audio
        MAX_SAMPLES = int(20 * 16000)    # nur die letzten ~20s (Latenz begrenzen)
        last = ""
        time.sleep(0.25)  # kurz die Waveform zeigen, bevor Text kommt
        while self._record_session == session and self.recorder.is_recording:
            try:
                audio = self.recorder.snapshot(MAX_SAMPLES)
                if len(audio) >= MIN_SAMPLES:
                    text = self.pipeline.transcribe_preview(audio)
                    if (text and text != last
                            and self._record_session == session
                            and self.recorder.is_recording):
                        last = text
                        self.overlay.set_text(text)
            except Exception:  # noqa: BLE001 - Vorschau darf das Diktat nie stoeren
                log.debug("Preview-Schleife fehlgeschlagen", exc_info=True)
            # Kurzes Intervall = haeufigere Updates. Die Transkription selbst
            # dauert ~150-250ms, macht mit diesem Sleep ~0.35-0.45s pro Update.
            time.sleep(0.18)

    def _on_dictate_arm(self):
        """Kurzer Tipp im Modus "both": das Tipp-Fenster laeuft. Die Pille
        deutet mit einem Ringbogen an, dass ein zweiter Tipp jetzt
        Freisprechen bedeutet (Antizipation statt Stillstand)."""
        self.overlay.set_held(False)
        if self.recorder.is_recording:
            self._set_overlay_state("armed")

    def _on_dictate_lock(self):
        """Doppeltipp: Freisprechen aktiv, Aufnahme laeuft weiter."""
        self.overlay.set_held(False)
        if not self.recorder.is_recording:
            return  # z.B. pausiert oder Start fehlgeschlagen - nicht "locked" zeigen
        if self.settings.get("play_sounds"):
            self.backends.sounds.play("lock")
        self._set_overlay_state("locked")

    def _on_dictate_cancel(self):
        """Versehentlicher Einzeltipp: verwerfen ohne Verarbeitung."""
        self._abort_recording()

    def _on_dictate_stop(self):
        self.overlay.set_held(False)
        if not self.recorder.is_recording:
            self._set_overlay_state("hidden")  # ggf. haengende "locked"-Pill aufloesen
            return
        session = self._record_session
        inj = self.backends.inject
        try:
            # Ziel-App VOR dem Tail erfassen (Nutzer ist jetzt noch im Zielfenster)
            app_name, title = inj.get_active_app()
            target_hwnd = inj.get_foreground_hwnd()
            tail = (self.settings.get("tail_ms") or 0) / 1000
            if tail:
                time.sleep(tail)
            audio = self.recorder.stop()
            # Trim-Werte JETZT snapshotten (das naechste Diktat ueberschreibt sie)
            trim_ctx = (self._record_start_mono, self.ducker.mute_complete_ts,
                        self.ducker.did_mute_sessions)
        finally:
            self.ducker.restore()
            self._cancel_watchdog()
        duration = len(audio) / 16000
        if duration < self.settings.get("min_duration_s"):
            self._set_overlay_if_current(session, "hidden")
            return
        if self.settings.get("play_sounds"):
            self.backends.sounds.play("stop")
        self._set_overlay_if_current(session, "processing")
        threading.Thread(target=self._process,
                         args=(session, audio, duration, app_name, title,
                               target_hwnd, trim_ctx),
                         daemon=True).start()

    def _set_overlay_if_current(self, session: int, state: str):
        """Overlay nur setzen, wenn kein neueres Diktat gestartet wurde -
        sonst wuerde ein verspaeteter alter Thread die Pill eines neuen
        Diktats ueberschreiben (z.B. altes 'hidden' verdeckt neues 'recording')."""
        if session == self._record_session:
            self._set_overlay_state(state)

    def _on_toggle(self):
        if not self.controller:
            return
        if self.recorder.is_recording:
            self.controller.force_stop()
        elif self.controller.state != "idle":
            # Haengender Zustand (z.B. Start scheiterte waehrend Pause):
            # erst aufraeumen - sonst no-opt start_locked fuer immer.
            self.controller.force_stop()
        elif self._hotkey_gate():
            # Nur das STARTEN wird im Spiel/Vollbild unterdrueckt - Stoppen
            # und Aufraeumen (oben) gehen immer.
            self.controller.start_locked()

    def _trim_muted_head(self, audio, trim_ctx):
        """Anfang der Aufnahme wegschneiden, in dem das System-Audio (YouTube
        etc.) noch hoerbar war - sonst transkribiert Whisper fremde Sprache
        als Teil des Diktats. trim_ctx ist der beim Stop gesnapshottete
        (start_mono, mute_complete_ts, did_mute_sessions)-Zustand."""
        start_mono, mute_complete_ts, did_mute = trim_ctx
        if not self.settings.get("duck_audio") or not did_mute:
            return audio
        cut_s = (mute_complete_ts - start_mono) + 0.06
        if cut_s <= 0 or cut_s > 0.8:
            return audio
        n = int(cut_s * 16000)
        if len(audio) - n < int(0.35 * 16000):
            return audio  # zu wenig uebrig - lieber nichts schneiden
        log.info("Aufnahme-Anfang getrimmt: %.0f ms (System-Audio noch hoerbar)",
                 cut_s * 1000)
        return audio[n:]

    def _process(self, session, audio, duration, app_name, title, target_hwnd, trim_ctx):
        with self._jobs_lock:
            self._jobs += 1
        try:
            self._process_inner(session, audio, duration, app_name, title,
                                target_hwnd, trim_ctx)
        finally:
            with self._jobs_lock:
                self._jobs -= 1

    def _process_inner(self, session, audio, duration, app_name, title, target_hwnd, trim_ctx):
        inj = self.backends.inject
        try:
            if not self.models_ready.wait(timeout=120):
                raise RuntimeError("Modelle nicht rechtzeitig geladen")
            audio = self._trim_muted_head(audio, trim_ctx)
            duration = len(audio) / 16000
            result = self.pipeline.process(audio, duration_s=duration)
            if result.status != "ok" or (not result.final_text and not result.commands):
                log.info("Kein Text (status=%s)", result.status)
                self._set_overlay_if_current(session, "hidden")
                return
            status = inj.PASTE_OK
            if result.final_text:
                smart = (bool(self.settings.get("smart_spacing"))
                         and (app_name or "").lower()
                         not in inj.SMART_SPACING_SKIP_APPS)
                # Kurze Diktate tippen statt einfuegen: das Einfuegen laeuft
                # ueber die Zwischenablage und macht uns zu deren Besitzer -
                # Programme mit Zwischenablage-Ueberwachung melden dann bei
                # jedem Diktat eine Aenderung. Getippt bleibt sie unberuehrt.
                # Preis: kein Smart Spacing, denn dessen Sonde misst ihrerseits
                # ueber die Zwischenablage.
                type_max = self.settings.get("type_max_chars") or 0
                if 0 < len(result.final_text) <= type_max:
                    status = inj.type_text(result.final_text, target_hwnd=target_hwnd)
                else:
                    status = inj.paste_text(result.final_text,
                                            restore_delay=self.settings.get("paste_restore_delay"),
                                            target_hwnd=target_hwnd,
                                            smart_spacing=smart)
            # Sprachbefehle NACH dem Einfuegen ausfuehren (Text zuerst, dann
            # z.B. Enter zum Absenden) - aber NUR, wenn das Paste wirklich im
            # Zielfenster gelandet ist. Bei clipboard_only/failed waere ein
            # Enter/Delete im gerade fokussierten (falschen) Fenster destruktiv.
            if result.commands and status == inj.PASTE_OK:
                inj.press_keys(result.commands, target_hwnd=target_hwnd)
                log.info("Sprachbefehl(e) ausgefuehrt: %s", " ".join(result.commands))
            elif result.commands:
                log.info("Sprachbefehle unterdrueckt (Paste-Status: %s)", status)
            if result.final_text:
                self.pipeline.record_history(result, app=app_name, window_title=title,
                                             duration_s=duration,
                                             pasted=status == inj.PASTE_OK)
                log.info("Diktat [%s] %sms in %s (%s), %d Woerter", result.language,
                         int(result.total_ms), app_name, status,
                         len(result.final_text.split()))
            if status == inj.PASTE_CLIPBOARD_ONLY:
                self._set_overlay_if_current(session, "clipboard")
                self._notify("Zielfenster nicht fokussierbar",
                             "Der Text liegt im Clipboard - mit Strg+V einfuegen.")
                time.sleep(CLIPBOARD_HOLD_S)
            elif status == inj.PASTE_OK:
                # Completion-Feedback: Haken in der Pille, kein dritter Sound
                self._set_overlay_if_current(session, "done")
                time.sleep(DONE_HOLD_S)
            self._set_overlay_if_current(session, "hidden")
        except Exception as exc:
            log.exception("Verarbeitung fehlgeschlagen")
            if self.settings.get("play_sounds"):
                self.backends.sounds.play("error")
            self.overlay.set_error(_error_reason(exc))
            self._set_overlay_if_current(session, "error")
            time.sleep(ERROR_HOLD_S)
            self._set_overlay_if_current(session, "hidden")

    def begin_capture_pause(self):
        """PTT waehrend Hotkey-Capture unterdruecken (zaehl-basiert, damit
        ueberlappende Capture-Requests sich nicht stoeren)."""
        with self._capture_lock:
            self._capture_count += 1
            self.paused = True

    def end_capture_pause(self):
        with self._capture_lock:
            self._capture_count = max(0, self._capture_count - 1)
            if self._capture_count == 0:
                self.paused = self._user_paused

    def _notify(self, title: str, message: str):
        try:
            if self.tray is not None:
                self.tray.notify(message, title)
        except Exception:  # noqa: BLE001
            log.debug("Tray-Notification fehlgeschlagen", exc_info=True)

    # --- Tray ---

    def _run_tray(self):
        def open_dashboard(icon, item):
            webbrowser.open(f"http://127.0.0.1:{self.settings.get('dashboard_port')}")

        def toggle_pause(icon, item):
            self._user_paused = not self._user_paused
            with self._capture_lock:
                self.paused = self._user_paused or self._capture_count > 0
            self._update_tray_icon()

        def toggle_autostart(icon, item):
            set_autostart(not is_autostart_enabled())

        def toggle_fullscreen_pause(icon, item):
            enabled = not self.settings.get("pause_in_fullscreen")
            self.settings.set("pause_in_fullscreen", enabled)
            log.info("Im Spiel/Vollbild pausieren: %s", "an" if enabled else "aus")

        def quit_app(icon, item):
            # Sauber runterfahren: laufendes Diktat stoppen, System-Audio
            # restaurieren (sonst blieben Apps stumm), Hooks loesen.
            try:
                self._cancel_watchdog()
                if self.recorder.is_recording and self.controller:
                    self.controller.force_stop()
                if self.ptt:
                    self.ptt.stop()
                if self.ptt2:
                    self.ptt2.stop()
                self._remove_toggle()
                self.ducker.restore()
                time.sleep(0.7)  # Restore-Fade (bis ~0.3s get + 0.12s Fade) abschliessen
                self.recorder.close()
            except Exception:  # noqa: BLE001
                log.exception("Shutdown-Cleanup fehlgeschlagen")
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Dashboard öffnen", open_dashboard, default=True),
            pystray.MenuItem("Pausieren", toggle_pause,
                             checked=lambda item: self._user_paused),
            pystray.MenuItem("Im Spiel / Vollbild pausieren", toggle_fullscreen_pause,
                             checked=lambda item: bool(self.settings.get("pause_in_fullscreen"))),
            pystray.MenuItem("Mit Windows starten" if sys.platform == "win32"
                             else "Beim Anmelden starten", toggle_autostart,
                             checked=lambda item: is_autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"LocalFlow v{__version__}", None, enabled=False),
            pystray.MenuItem("Beenden", quit_app),
        )
        self.tray = pystray.Icon("LocalFlow", make_icon(), "LocalFlow", menu)
        self.tray.run()


# --- Autostart (Delegates; Implementierung im Plattform-Backend) ---
# Als Modul-Funktionen erhalten, weil web/app.py sie von hier importiert.

def is_autostart_enabled() -> bool:
    return get_backends().autostart.is_enabled()


def set_autostart(enabled: bool):
    get_backends().autostart.set_enabled(enabled)


def main():
    backends = get_backends()
    # Scharfe (nicht skaliert-verwaschene) Overlay-Darstellung auf High-DPI
    backends.integration.set_dpi_awareness()
    setup_logging()
    if not backends.integration.acquire_single_instance():
        # "Nochmal oeffnen" (z.B. Startmenue-Suche) soll sich wie Oeffnen
        # anfuehlen: Dashboard der laufenden Instanz zeigen statt eines
        # modalen "laeuft bereits"-Dialogs, dann leise beenden.
        log.info("LocalFlow laeuft bereits - oeffne Dashboard der laufenden Instanz")
        try:
            webbrowser.open(f"http://127.0.0.1:{Settings().get('dashboard_port')}")
        except Exception:  # noqa: BLE001
            log.exception("Dashboard-Oeffnen fehlgeschlagen")
        return
    log.info("LocalFlow v%s startet (cwd=%s)", __version__, os.getcwd())
    app = LocalFlowApp()
    app.start()


if __name__ == "__main__":
    main()
