"""Mikrofonaufnahme: 16 kHz mono float32, Push-to-Talk.

Der Mikrofon-Stream wird NUR fuer die Dauer der Aufnahme geoeffnet
(Nutzerwunsch: die Windows-Anzeige "Mikrofon wird verwendet" soll nur beim
Diktieren leuchten). Das Oeffnen kostet einmalig ~50-200 ms beim Tastendruck;
der Ringpuffer (Pre-Roll) wirkt daher nur innerhalb einer offenen Session.
"""

import logging
import math
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger("localflow.audio")

SAMPLE_RATE = 16000
BLOCKSIZE = 1024  # ~64 ms pro Callback


class LevelMeter:
    """Adaptiver Pegel 0..1 fuer die Waveform-Anzeige.

    Statt fester dB-Grenzen wird der laufende Sprech-Peak getrackt und der
    Pegel relativ dazu skaliert (Auto-Gain). So schlagen die Balken auch bei
    leise eingestelltem Mikrofon voll aus, und bei lautem uebersteuern sie
    nicht. Der Peak faellt langsam ab, damit sich die Skala nach einer
    lauten Passage wieder erholt.
    """

    SILENCE_DB = -55.0     # darunter gilt: Stille
    SPAN_DB = 16.0         # angezeigte Dynamik unterhalb des Peaks
    PEAK_DECAY = 0.25      # dB Abfall des Peaks pro Frame (~4 dB/s bei 16 fps)
    PEAK_INIT = -34.0

    def __init__(self):
        self.peak_db = self.PEAK_INIT

    def level(self, rms: float) -> float:
        db = 20 * math.log10(rms + 1e-9)
        if db <= self.SILENCE_DB:
            self.peak_db = max(self.peak_db - self.PEAK_DECAY, self.PEAK_INIT)
            return 0.0
        self.peak_db = max(db, self.peak_db - self.PEAK_DECAY, self.PEAK_INIT)
        lvl = (db - (self.peak_db - self.SPAN_DB)) / self.SPAN_DB
        return min(1.0, max(0.0, lvl))


class Recorder:
    """Haelt einen InputStream offen (geringe Startlatenz) und sammelt Frames
    zwischen start() und stop()."""

    def __init__(self, device: int | str | None = None, level_callback=None):
        self.device = device
        self.level_callback = level_callback
        self._meter = LevelMeter()
        self._lock = threading.Lock()          # schuetzt Chunks/Recording-Flag
        self._stream_lock = threading.Lock()   # serialisiert open()/close()
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._stream: sd.InputStream | None = None

    def open(self):
        # Stream nur waehrend der Aufnahme offen (Windows-"Mikrofon aktiv"-
        # Anzeige nur beim Diktieren). open/close koennen aus Diktat- UND
        # Flask-Thread kommen -> unter Stream-Lock serialisieren.
        with self._stream_lock:
            if self._stream is not None:
                return
            import time
            t0 = time.perf_counter()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self.device,
                blocksize=BLOCKSIZE,
                callback=self._callback,
            )
            self._stream.start()
            log.info("Audio-Stream offen in %.0f ms (Geraet: %s)",
                     (time.perf_counter() - t0) * 1000, self.device or "default")

    def close(self):
        with self._stream_lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                log.info("Audio-Stream geschlossen (Mikrofon frei)")

    @property
    def stream_open(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("Audio-Status: %s", status)
        mono = indata[:, 0].copy()
        with self._lock:
            if self._recording:
                self._chunks.append(mono)
        if self._recording and self.level_callback is not None:
            rms = float(np.sqrt(np.mean(mono ** 2)))
            self.level_callback(self._meter.level(rms))

    def start(self):
        self.open()  # Stream nur waehrend der Aufnahme offen (Mikro-Anzeige)
        with self._lock:
            self._chunks = []
            self._recording = True

    def snapshot(self, max_samples: int | None = None) -> np.ndarray:
        """Bisher aufgenommenes Audio zurueckgeben, OHNE zu stoppen -
        fuer die Live-Vorschau waehrend der Aufnahme. max_samples begrenzt
        auf die letzten N Samples: so kopiert ein Preview-Poll bei langen
        Aufnahmen nicht die komplette Aufnahme unter dem Callback-Lock."""
        with self._lock:
            if not self._recording or not self._chunks:
                return np.zeros(0, dtype=np.float32)
            if max_samples is None:
                return np.concatenate(self._chunks)
            take, total = [], 0
            for chunk in reversed(self._chunks):
                take.append(chunk)
                total += len(chunk)
                if total >= max_samples:
                    break
            take.reverse()
        audio = np.concatenate(take)
        return audio[-max_samples:]

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            if not self._chunks:
                audio = np.zeros(0, dtype=np.float32)
            else:
                audio = np.concatenate(self._chunks)
                self._chunks = []
        self.close()
        return audio

    @property
    def is_recording(self) -> bool:
        return self._recording


def list_input_devices() -> list[dict]:
    """Eingabegeraete, dedupliziert auf die WASAPI-Variante je Name."""
    devices = []
    seen = set()
    try:
        default_idx = sd.default.device[0]
    except Exception:  # noqa: BLE001
        default_idx = -1
    hostapis = sd.query_hostapis()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        api = hostapis[d["hostapi"]]["name"]
        key = d["name"].strip()
        if key in seen and api != "Windows WASAPI":
            continue
        seen.add(key)
        devices.append({"index": i, "name": d["name"], "hostapi": api,
                        "default": i == default_idx})
    return devices
