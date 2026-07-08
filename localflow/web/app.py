"""Dashboard: History, Dictionary, Settings auf http://127.0.0.1:<port>."""

import logging
import os

from flask import Flask, jsonify, render_template, request

log = logging.getLogger("localflow.web")

EDITABLE_SETTINGS = [
    "hotkey", "hotkey2", "toggle_hotkey", "ptt_mode", "language", "ollama_model", "ai_cleanup",
    "play_sounds", "min_duration_s", "paste_restore_delay", "cleanup_timeout_s",
    "audio_device", "beam_size", "cleanup_min_words", "tail_ms",
    "duck_audio", "duck_volume", "swallow_mouse_hotkey", "max_duration_s",
    "voice_commands_enabled", "voice_commands", "live_preview", "glass_pill",
    "overlay_font", "overlay_font_size", "overlay_theme", "smart_spacing",
]


def _sanitize_voice_commands(v):
    """Nur gueltige {key, phrases}-Eintraege durchlassen (Schutz vor kaputten
    oder boesartigen Werten aus dem Request)."""
    from ..commands import VALID_KEYS
    out = []
    if isinstance(v, list):
        for c in v:
            if not isinstance(c, dict):
                continue
            key = str(c.get("key", "")).strip().lower()
            if key not in VALID_KEYS:
                continue
            phrases = [str(p).strip().lower() for p in (c.get("phrases") or [])
                       if isinstance(p, str) and str(p).strip()]
            if phrases:
                out.append({"key": key, "phrases": phrases})
    return out


def _apply_runtime_changes(main_app, settings, changed: set):
    """Geaenderte Settings sofort auf die laufende App anwenden (kein Neustart)."""
    import threading
    if {"hotkey", "hotkey2", "ptt_mode", "swallow_mouse_hotkey"} & changed:
        try:
            main_app._install_hotkey()  # stoppt die alten Hooks selbst
        except Exception:
            log.exception("Hotkey-Neustart fehlgeschlagen")
    if "toggle_hotkey" in changed:
        try:
            main_app._install_toggle()
        except Exception:
            log.exception("Toggle-Neustart fehlgeschlagen")
    if "audio_device" in changed:
        # Nur Geraet umstellen - NICHT open(): der Stream oeffnet sich erst
        # beim naechsten Diktat (Mikro-Anzeige nur waehrend Aufnahme).
        try:
            main_app.recorder.close()
            main_app.recorder.device = settings.get("audio_device")
        except Exception:
            log.exception("Audio-Geraetewechsel fehlgeschlagen")
    if "glass_pill" in changed:
        try:
            main_app.overlay.set_glass(settings.get("glass_pill"))
        except Exception:
            log.exception("Glas-Optik-Umschalten fehlgeschlagen")
    if {"overlay_font", "overlay_font_size"} & changed:
        try:
            main_app.overlay.set_style(settings.get("overlay_font"),
                                       settings.get("overlay_font_size"))
        except Exception:
            log.exception("Schrift-Umstellung fehlgeschlagen")
    if "overlay_theme" in changed:
        try:
            main_app.overlay.set_theme(settings.get("overlay_theme"))
        except Exception:
            log.exception("Theme-Umschalten fehlgeschlagen")
    if "duck_volume" in changed:
        try:
            main_app.ducker.duck_volume = max(0.0, min(1.0, float(settings.get("duck_volume") or 0.0)))
        except (TypeError, ValueError):
            log.exception("duck_volume-Uebernahme fehlgeschlagen")
    if "cleanup_timeout_s" in changed and main_app.pipeline.cleaner:
        main_app.pipeline.cleaner.timeout = settings.get("cleanup_timeout_s")
    if "ollama_model" in changed and main_app.pipeline.cleaner:
        try:
            main_app.pipeline.cleaner.model = settings.get("ollama_model")
            threading.Thread(target=main_app.pipeline.cleaner.warmup, daemon=True).start()
        except Exception:
            log.exception("Cleaner-Wechsel fehlgeschlagen")


def create_app(settings, db, main_app=None):
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    port = settings.get("dashboard_port")
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.before_request
    def _guard():
        """Zwei-Schichten-Schutz. Diese API steuert synthetische Tastendruecke,
        Clipboard und das komplette Diktat-Archiv - Bind auf 127.0.0.1 allein
        reicht nicht, weil der BROWSER des Nutzers sie angreifen koennte.

        1. Host-Allowlist gegen DNS-Rebinding: eine rebindete Angreifer-Domain
           schickt ihren eigenen Hostnamen im Host-Header -> abgelehnt.
        2. Custom-Header gegen CSRF fuer ALLE state-aendernden Methoden:
           - Ein Cross-Origin-<form>-POST (der klassische CSRF-Vektor, kommt
             ohne Origin/Referer aus) kann KEINE Custom-Header setzen -> 403.
           - Ein Cross-Origin-fetch mit Custom-Header loest CORS-Preflight aus;
             der scheitert (wir senden keine CORS-Header) -> Browser blockt.
           - Same-Origin-Dashboard und lokale Clients setzen ihn problemlos."""
        if request.host not in allowed_hosts:
            return jsonify({"error": "forbidden host"}), 403
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("X-LocalFlow") != "1":
                return jsonify({"error": "forbidden"}), 403

    def body() -> dict:
        """JSON-Body ohne force=True: fremde Simple-Requests (text/plain, kein
        Content-Type) liefern None -> {} statt heimlich geparst zu werden."""
        return request.get_json(silent=True) or {}

    def int_arg(name: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/stats")
    def stats():
        return jsonify(db.get_stats())

    @app.get("/api/history")
    def history():
        return jsonify(db.get_history(
            limit=int_arg("limit", 100, 1, 500),
            offset=int_arg("offset", 0, 0, 10_000_000),
            search=request.args.get("search") or None))

    @app.delete("/api/history/<hid>")
    def history_delete(hid):
        db.delete_history(hid)
        return jsonify({"ok": True})

    @app.get("/api/devices")
    def devices():
        from ..audio import list_input_devices
        return jsonify(list_input_devices())

    @app.get("/api/models")
    def models():
        """Installierte Ollama-Modelle (fuer das Cleanup-Dropdown)."""
        import requests as rq
        try:
            r = rq.get(f"{settings.get('ollama_url')}/api/tags", timeout=3)
            names = [m["name"] for m in r.json().get("models", [])
                     if "embed" not in m["name"]]
            return jsonify(names)
        except Exception:  # noqa: BLE001
            return jsonify([])

    @app.get("/api/dictionary")
    def dictionary_list():
        return jsonify(db.get_dictionary())

    @app.post("/api/dictionary")
    def dictionary_add():
        data = body()
        phrase = (data.get("phrase") or "").strip()
        if not phrase:
            return jsonify({"error": "phrase fehlt"}), 400
        did = db.add_dictionary(phrase, (data.get("replacement") or "").strip() or None,
                                bool(data.get("is_snippet")))
        return jsonify({"id": did})

    @app.delete("/api/dictionary/<did>")
    def dictionary_delete(did):
        db.update_dictionary(did, is_deleted=1)
        return jsonify({"ok": True})

    @app.get("/api/settings")
    def settings_get():
        data = {k: settings.get(k) for k in EDITABLE_SETTINGS}
        try:
            from ..main import is_autostart_enabled
            data["autostart"] = is_autostart_enabled()
        except Exception:  # noqa: BLE001
            data["autostart"] = False
        return jsonify(data)

    @app.post("/api/settings")
    def settings_set():
        data = body()
        changed = []
        if "autostart" in data:
            try:
                from ..main import set_autostart
                set_autostart(bool(data["autostart"]))
                changed.append("autostart")
            except Exception:
                log.exception("Autostart-Umschalten fehlgeschlagen")
        if "voice_commands" in data:
            data["voice_commands"] = _sanitize_voice_commands(data["voice_commands"])
        if "overlay_theme" in data and data["overlay_theme"] not in ("dark", "light"):
            data["overlay_theme"] = "dark"
        for k, v in data.items():
            # Nur echte Aenderungen anwenden - sonst wuerde z.B. jeder
            # Speichern-Klick den Hotkey-Hook grundlos neu installieren.
            if k in EDITABLE_SETTINGS and settings.get(k) != v:
                settings.set(k, v)
                changed.append(k)
        if main_app is not None and changed:
            _apply_runtime_changes(main_app, settings, set(changed))
        return jsonify({"changed": changed})

    @app.post("/api/hotkey/capture")
    def hotkey_capture():
        """Naechste Tastenkombination aufzeichnen (fuer die Settings-UI).
        Blockiert bis zur Eingabe oder Timeout (10s)."""
        if main_app is not None:
            capture = main_app.backends.capture_combo
        else:  # Fallback ohne App-Kontext (z.B. isolierte Tests)
            from ..platform import get_backends
            capture = get_backends().capture_combo
        # Zaehl-basiertes Pausieren (nicht bool): ueberlappende Capture-Requests
        # duerfen sich nicht gegenseitig den Pause-Zustand zerschiessen.
        if main_app is not None:
            main_app.begin_capture_pause()
        try:
            combo = capture(timeout=10.0)
        finally:
            if main_app is not None:
                main_app.end_capture_pause()
        if not combo:
            return jsonify({"error": "Timeout - keine Eingabe erkannt"}), 408
        return jsonify({"combo": combo})

    # Die maechtigen Debug-Routen (Overlay treiben, beliebige WAV verarbeiten
    # UND in ein beliebiges Fenster pasten) sind reine Test-Werkzeuge und
    # werden in normalen Laeufen GAR NICHT registriert. Nur mit
    # LOCALFLOW_DEBUG=1 (Tests) sind sie vorhanden - so existiert die
    # Paste-in-fremdes-Fenster-Faehigkeit im Alltag nicht als Angriffsflaeche.
    if os.environ.get("LOCALFLOW_DEBUG") == "1":

        @app.post("/api/debug/overlay")
        def debug_overlay():
            if main_app is None:
                return jsonify({"error": "kein App-Kontext"}), 400
            data = body()
            main_app.overlay.set_state(data.get("state", "hidden"))
            if data.get("level_ramp"):
                import math
                import threading
                import time as _t
                def ramp():
                    t0 = _t.perf_counter()
                    while _t.perf_counter() - t0 < float(data.get("seconds", 4)):
                        x = _t.perf_counter() - t0
                        lvl = 0.5 + 0.45 * math.sin(x * 6) * math.sin(x * 1.3)
                        main_app.overlay.set_level(max(0.05, lvl))
                        _t.sleep(0.03)
                    main_app.overlay.set_state("hidden")
                threading.Thread(target=ramp, daemon=True).start()
            return jsonify({"ok": True})

        @app.post("/api/debug/dictate")
        def debug_dictate():
            if main_app is None:
                return jsonify({"error": "kein App-Kontext"}), 400
            data = body()
            wav = data.get("wav")
            if not wav or not os.path.exists(wav):
                return jsonify({"error": f"WAV nicht gefunden: {wav}"}), 404
            if not main_app.models_ready.wait(timeout=180):
                return jsonify({"error": "Modelle nicht geladen"}), 503
            from ..inject import PASTE_OK, get_active_app, paste_text
            result = main_app.pipeline.process(wav)
            paste_status = "skipped"
            if result.status == "ok" and result.final_text and data.get("paste", True):
                app_name, title = get_active_app()
                paste_status = paste_text(result.final_text, target_hwnd=data.get("hwnd"))
                main_app.pipeline.record_history(result, app=app_name, window_title=title,
                                                 pasted=paste_status == PASTE_OK)
            return jsonify({"status": result.status, "asr": result.asr_text,
                            "final": result.final_text, "language": result.language,
                            "stt_ms": result.stt_ms, "cleanup_ms": result.cleanup_ms,
                            "total_ms": result.total_ms,
                            "pasted": paste_status == PASTE_OK,
                            "paste_status": paste_status})

    @app.get("/api/debug/state")
    def debug_state():
        if main_app is None:
            return jsonify({"error": "kein App-Kontext"}), 400
        return jsonify({"models_ready": main_app.models_ready.is_set(),
                        "paused": main_app.paused,
                        "recording": main_app.recorder.is_recording,
                        "mic_stream_open": main_app.recorder.stream_open,
                        "controller_state": getattr(main_app.controller, "state", "?"),
                        "last_level": main_app.last_level})

    @app.post("/api/import-wispr")
    def import_wispr():
        from ..importer import import_wispr_data
        try:
            result = import_wispr_data(db, include_history=bool(
                body().get("history", True)))
            return jsonify(result)
        except FileNotFoundError as e:
            return jsonify({"error": str(e)}), 404

    return app
