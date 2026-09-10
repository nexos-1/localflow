"""Glass Mic: iPad-Mikrofon als Eingang.

Glass Mic (glass-mic.exe, Port 8321) spielt das iPad-Mikrofon auf VB-CABLE. Solange ein
iPad verbunden ist, meldet /api/stats clients >= 1. Dann nimmt LocalFlow von
"CABLE Output" auf statt vom konfigurierten Mikrofon.

Warum nicht ueber das Windows-Standardmikrofon: PortAudio loest den Default beim
Prozessstart einmalig auf und bekommt spaetere Wechsel nicht mit. Und VB-CABLEs
MME/DirectSound-Wrapper liefern Stille; nur WASAPI traegt das Signal. WASAPI kann
16 kHz Mono nur mit PortAudio-Auto-Convert (sd.WasapiSettings(auto_convert=True)).

Der Check kostet lokal 2-5 ms pro Diktat-Start und faellt bei jedem Fehler still auf
das normale Mikrofon zurueck.
"""

import json
import logging
import urllib.request

log = logging.getLogger("localflow.glassmic")

DEFAULT_URL = "http://127.0.0.1:8321"
DEFAULT_DEVICE = "CABLE Output (VB-Audio Virtual Cable), Windows WASAPI"


def active(url: str = DEFAULT_URL, timeout_s: float = 0.15) -> bool:
    """True, wenn Glass Mic laeuft und mindestens ein iPad verbunden ist."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/stats", timeout=timeout_s) as r:
            stats = json.loads(r.read().decode("utf-8"))
        return int(stats.get("clients", 0)) > 0
    except Exception as e:  # nicht erreichbar, kein Glass Mic: normales Mikrofon
        log.debug("glassmic nicht aktiv: %s", e)
        return False
