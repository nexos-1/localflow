"""Sicherungskopien langer Diktate als WAV (16 kHz mono, 16 bit).

Ein langes Diktat ist viel Arbeit; geht danach etwas schief (STT-Fehler,
Einfuegen ins falsche Fenster, Absturz), soll das Gesagte nicht verloren sein.
Der Text steht nach Erfolg ohnehin im Verlauf; diese Kopie ist fuer den Fall,
dass es gar keinen Text gibt. Gespeichert wird lokal im Datenordner
(data/recordings), nie hochgeladen; es bleiben nur die neuesten KEEP Dateien.
"""

import logging
import os
import time
import wave

import numpy as np

log = logging.getLogger("localflow.recordings")

# Ab dieser Laenge wird gesichert (kurze Diktate tippt man schnell neu).
SAVE_RECORDING_MIN_S = 60
# So viele Sicherungen bleiben liegen (eine Stunde Ton sind etwa 115 MB).
KEEP = 5
SAMPLE_RATE = 16000


def save_recording(audio, folder: str, keep: int = KEEP, now: float | None = None) -> str | None:
    """audio (float32 -1..1) als WAV in folder schreiben, aeltere ueber `keep`
    hinaus loeschen. Gibt den Pfad zurueck; ein Fehler wird nur geloggt, denn
    die Sicherung darf das Diktat nie aufhalten."""
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        path = os.path.join(folder, f"diktat-{stamp}.wav")
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, f"diktat-{stamp}-{n}.wav")
        pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
        tmp = path + ".part"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        os.replace(tmp, path)
        log.info("Langes Diktat gesichert: %s (%.0f s)", os.path.basename(path), len(pcm) / SAMPLE_RATE)
        _prune(folder, keep)
        return path
    except Exception:  # noqa: BLE001
        log.warning("Sicherung des Diktats fehlgeschlagen", exc_info=True)
        return None


def _prune(folder: str, keep: int):
    files = sorted(
        (os.path.join(folder, f) for f in os.listdir(folder)
         if f.startswith("diktat-") and f.endswith(".wav")),
        key=os.path.getmtime, reverse=True)
    for old in files[keep:]:
        try:
            os.remove(old)
        except OSError:
            log.debug("Alte Sicherung nicht loeschbar: %s", old, exc_info=True)
