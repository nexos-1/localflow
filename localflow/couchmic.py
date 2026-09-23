"""CouchMic: iPad-Mikrofon als Eingang (https://github.com/nexos-1/couchmic).

CouchMic (couchmic.exe, Port 8321, frueher "Glass Mic") spielt das iPad-Mikrofon auf
VB-CABLE. Solange ein iPad verbunden ist, meldet /api/stats clients >= 1. Dann nimmt
LocalFlow von "CABLE Output" auf statt vom konfigurierten Mikrofon.

Warum nicht ueber das Windows-Standardmikrofon, obwohl CouchMic es beim Verbinden auf
CABLE Output umschaltet: PortAudio loest den Default beim Prozessstart einmalig auf und
bekommt spaetere Wechsel nicht mit. Und VB-CABLEs
MME/DirectSound-Wrapper liefern Stille; nur WASAPI traegt das Signal. WASAPI kann
16 kHz Mono nur mit PortAudio-Auto-Convert (sd.WasapiSettings(auto_convert=True)).

Der Check kostet lokal 2-5 ms pro Diktat-Start und faellt bei jedem Fehler still auf
das normale Mikrofon zurueck.
"""

import json
import logging
import urllib.request

log = logging.getLogger("localflow.couchmic")

DEFAULT_URL = "http://127.0.0.1:8321"
DEFAULT_DEVICE = "CABLE Output (VB-Audio Virtual Cable), Windows WASAPI"


def active(url: str = DEFAULT_URL, timeout_s: float = 0.15) -> bool:
    """True, wenn CouchMic laeuft und mindestens ein iPad verbunden ist."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/stats", timeout=timeout_s) as r:
            stats = json.loads(r.read().decode("utf-8"))
        return int(stats.get("clients", 0)) > 0
    except Exception as e:  # nicht erreichbar, kein CouchMic: normales Mikrofon
        log.debug("couchmic nicht aktiv: %s", e)
        return False
