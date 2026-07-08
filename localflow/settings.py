"""JSON-Settings in <projekt>/data/config.json (siehe APP_DIR unten)."""

import json
import logging
import os
import threading

from .commands import DEFAULT_COMMANDS

log = logging.getLogger("localflow.settings")

# Datenordner NEBEN dem Code (Projektwurzel/data), bewusst NICHT in %APPDATA%.
# Grund: Wird die App aus einer Sandbox heraus gestartet (z.B. von einem
# Tool, dessen Prozesse in einem App-Container laufen), leitet Windows
# %APPDATA% transparent auf einen anderen Ordner um - die App zeigte dann je
# nach Start-Kontext auf einen anderen, leeren Datenstand ("alles resettet").
# Ein Pfad neben dem Code ist fuer JEDEN Start-Weg identisch (Autostart,
# Startmenue, Terminal, Sandbox) und ueberlebt Crashes/Neustarts zuverlaessig.
# LOCALFLOW_DATA_DIR kann den Ort bei Bedarf explizit ueberschreiben.
APP_DIR = os.environ.get("LOCALFLOW_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

DEFAULTS = {
    "hotkey": "ctrl+win",          # Push-to-Talk: halten zum Aufnehmen
    # Optionaler ZWEITER Diktat-Hotkey - laeuft parallel zum ersten, gleiches
    # Verhalten (halten/Doppeltipp je nach ptt_mode). Leer = deaktiviert.
    "hotkey2": "",
    # "hold" = nur halten | "both" = halten + Doppeltipp-Freisprechen |
    # "toggle" = jeder Druck startet/stoppt
    "ptt_mode": "both",
    # False (wie Wispr): Maus-Seitentaste laeuft parallel weiter (Browser
    # navigiert vor/zurueck UND LocalFlow reagiert). True: Taste wird
    # systemweit verschluckt und ist exklusiv fuers Diktieren.
    "swallow_mouse_hotkey": False,
    # Darf die PTT-Kombination NICHT enthalten, sonst feuert beim Toggle erst
    # der Halte-Hook und beide Modi kollidieren.
    "toggle_hotkey": "ctrl+alt+space",  # einmal druecken = Start, nochmal = Stop
    "language": "auto",             # "auto" | "de" | "en" | ...
    "allowed_languages": ["de", "en"],  # bei auto: Detektion auf diese beschraenken
    "whisper_model": "large-v3-turbo",
    "beam_size": 1,                 # Benchmark auf echter Stimme: beam1 > beam5
    "ollama_model": "gemma3:4b",
    "ollama_url": "http://127.0.0.1:11434",  # 127.0.0.1 statt localhost: spart ~2s IPv6-Fallback
    "ai_cleanup": True,
    "audio_device": None,           # None = Windows-Default
    "play_sounds": True,
    "duck_audio": True,             # andere Apps (YouTube etc.) waehrend Aufnahme stummschalten
    "duck_volume": 0.0,             # Restlautstaerke waehrend der Aufnahme (0 = komplett stumm)
    "min_duration_s": 0.4,          # kuerzere Aufnahmen verwerfen (versehentlicher Tastendruck)
    "max_duration_s": 300,          # Auto-Stopp (vergessenes Freisprechen)
    "dashboard_port": 5111,
    "paste_restore_delay": 1.0,
    "cleanup_timeout_s": 8.0,
    "cleanup_min_words": 4,         # kuerzere Texte nicht durchs LLM (Whisper punktiert selbst)
    "tail_ms": 150,                 # Audio nach dem Loslassen mitnehmen (letzte Silbe)
    # Sprachbefehle: am Ende gesprochene Phrasen ("press enter") loesen einen
    # Tastendruck statt Text aus. Liste ist im Dashboard erweiterbar.
    "voice_commands_enabled": True,
    "voice_commands": DEFAULT_COMMANDS,
    # Live-Vorschau: waehrend der Aufnahme laeuft Whisper wiederholt ueber das
    # bisher Gesprochene und zeigt den Zwischenstand in der Overlay-Pille. Der
    # finale, bereinigte Text wird wie gehabt erst beim Loslassen eingefuegt.
    "live_preview": True,
    # Glas-Optik: Overlay-Pille durchscheinend (Desktop schimmert durch).
    "glass_pill": False,
    # Widget-Design (Overlay-Pille): Schriftart + -groesse, live umschaltbar.
    "overlay_font": "Segoe UI",
    "overlay_font_size": 11,
    # "dark" = schwarze Pille (Standard) | "light" = mittelgraue Pille,
    # weisser Text (auf hellen Desktops/Apps angenehmer).
    "overlay_theme": "dark",
    # Smart Spacing: klebt das Diktat sonst direkt an bestehenden Text
    # (Satzende, Wortmitte), wird automatisch ein Leerzeichen vorangestellt.
    # In Terminals automatisch deaktiviert (Sonde nutzt Strg+C).
    "smart_spacing": True,
}


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(APP_DIR, "config.json")
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                stored = json.load(f)
            self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except FileNotFoundError:
            self.save()
        except Exception as e:  # noqa: BLE001
            log.warning("Settings kaputt (%s), nutze Defaults", e)

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self.data[key] = value
        self.save()

    def update(self, values: dict):
        """Mehrere Keys mit EINEM Save setzen (statt einer Datei-Schreibung
        pro Key, wie es set() in einer Schleife taete)."""
        for k in values:
            if k not in DEFAULTS:
                raise KeyError(k)
        self.data.update(values)
        self.save()
