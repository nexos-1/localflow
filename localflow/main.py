"""LocalFlow - Hauptprogramm: Tray-App mit Push-to-Talk-Diktat.

Start:  .venv\\Scripts\\pythonw.exe -m localflow.main
"""

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
from .pipeline import Pipeline
from .platform import get_backends
from .settings import APP_DIR, Settings

log = logging.getLogger("localflow")


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
        self.tray: pystray.Icon | None = None

    # --- Lebenszyklus ---

    def start(self):
        self.backends.sounds.ensure_sounds()
        threading.Thread(target=self._ensure_shortcut, daemon=True).start()
        self.overlay.start()
        self.overlay.set_glass(self.settings.get("glass_pill"))
        self.overlay.set_style(self.settings.get("overlay_font"),
                               self.settings.get("overlay_font_size"))
        self.overlay.set_theme(self.settings.get("overlay_theme"))
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
                locked = self.controller and self.controller.state == "locked"
                self._set_overlay_state("locked" if locked else "recording")
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
                                              swallow_mouse=swallow)
            self.ptt.start()
        # Zweiter Hotkey nur, wenn gesetzt UND nicht identisch zum ersten
        # (sonst wuerden zwei Hooks dieselbe Kombination doppelt melden).
        second = (self.settings.get("hotkey2") or "").strip()
        if second and (not primary or normalize_combo(second) != normalize_combo(primary)):
            self.ptt2 = self.backends.make_ptt(second, self.controller,
                                               swallow_mouse=swallow)
            self.ptt2.start()

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
            self.recorder.start()
            self._arm_max_duration_watchdog(self._record_session)
            if self.settings.get("play_sounds"):
                self.backends.sounds.play("start")
            # Preview-Text des VORIGEN Diktats loeschen, bevor die Pille
            # wieder auf recording geht (Queue ist geordnet: text vor state).
            self.overlay.set_text("")
            self._set_overlay_state("recording" if self.models_ready.is_set() else "loading")
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

    def _on_dictate_lock(self):
        """Doppeltipp: Freisprechen aktiv, Aufnahme laeuft weiter."""
        if not self.recorder.is_recording:
            return  # z.B. pausiert oder Start fehlgeschlagen - nicht "locked" zeigen
        if self.settings.get("play_sounds"):
            self.backends.sounds.play("lock")
        self._set_overlay_state("locked")

    def _on_dictate_cancel(self):
        """Versehentlicher Einzeltipp: verwerfen ohne Verarbeitung."""
        self._abort_recording()

    def _on_dictate_stop(self):
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
        else:
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
                time.sleep(2.5)
            self._set_overlay_if_current(session, "hidden")
        except Exception:
            log.exception("Verarbeitung fehlgeschlagen")
            if self.settings.get("play_sounds"):
                self.backends.sounds.play("error")
            self._set_overlay_if_current(session, "error")
            time.sleep(1.5)
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
            icon.icon = make_icon("#9a9a9a" if self._user_paused else "#ff9500")

        def toggle_autostart(icon, item):
            set_autostart(not is_autostart_enabled())

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
