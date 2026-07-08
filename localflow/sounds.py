"""Start/Stop-Sounds: warme, weiche Zweiklang-Chimes (marimba-artig).

Design: Sinus-Grundton mit leisen geradzahligen Obertoenen, sanfter Attack
(12 ms), exponentielles Ausklingen, leichte Verstimmung fuer Waerme - keine
harten Kanten, nichts Schrilles. Aufsteigend = Start, absteigend = Stop.
Wird beim ersten Start generiert; SOUND_VERSION erzwingt Neugenerierung,
wenn sich das Klangdesign aendert.
"""

import os
import sys
import wave

import numpy as np

from .settings import APP_DIR

SOUND_DIR = os.path.join(APP_DIR, "sounds")
SOUND_VERSION = "2"
RATE = 44100


def _note(freq: float, dur: float, amp: float = 0.22) -> np.ndarray:
    """Weicher glockiger Einzelton."""
    n = int(RATE * dur)
    t = np.arange(n) / RATE
    # Grundton + dezente Obertoene, minimal verstimmter zweiter Oszillator (Waerme)
    tone = (np.sin(2 * np.pi * freq * t)
            + 0.28 * np.sin(2 * np.pi * freq * 2.001 * t)
            + 0.08 * np.sin(2 * np.pi * freq * 3.0 * t)
            + 0.35 * np.sin(2 * np.pi * (freq * 1.003) * t))
    tone /= 1.71
    attack = np.minimum(1.0, t / 0.012)
    decay = np.exp(-t / (dur * 0.38))
    fade_out = np.minimum(1.0, (dur - t) / 0.02)
    return (amp * tone * attack * decay * fade_out).astype(np.float32)


def _chime(freqs: list[float], gap_s: float = 0.085, dur: float = 0.42) -> np.ndarray:
    """Mehrere Noten leicht ueberlappend schichten."""
    total = int(RATE * (dur + gap_s * (len(freqs) - 1))) + 1
    out = np.zeros(total, dtype=np.float32)
    for i, f in enumerate(freqs):
        start = int(RATE * gap_s * i)
        note = _note(f, dur)
        out[start:start + len(note)] += note
    peak = np.max(np.abs(out))
    if peak > 0.9:
        out *= 0.9 / peak
    return out


def _write_wav(path: str, samples: np.ndarray):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def _custom_names() -> set[str]:
    """Namen (start/stop/...), die der Nutzer durch EIGENE WAVs ersetzt hat -
    stehen in sounds/custom.txt (eine Zeile pro Name) und werden von der
    Generierung NIE ueberschrieben, auch nicht bei einem Versions-Bump."""
    try:
        with open(os.path.join(SOUND_DIR, "custom.txt"), encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def ensure_sounds():
    os.makedirs(SOUND_DIR, exist_ok=True)
    version_file = os.path.join(SOUND_DIR, "version.txt")
    try:
        with open(version_file, encoding="utf-8") as f:
            if f.read().strip() == SOUND_VERSION:
                return
    except FileNotFoundError:
        pass
    custom = _custom_names()
    # G4 -> C5: freundlich aufsteigend; Stop: gespiegelt; Error: tiefer Einzelton
    generated = {
        "start": lambda: _chime([392.0, 523.25]),
        "stop": lambda: _chime([523.25, 392.0]),
        "lock": lambda: _chime([392.0, 523.25, 659.25]),
        "error": lambda: _chime([220.0, 174.6], gap_s=0.12, dur=0.5),
    }
    for name, make in generated.items():
        if name in custom:
            continue  # Nutzer-Sound bleibt unangetastet
        _write_wav(os.path.join(SOUND_DIR, f"{name}.wav"), make())
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(SOUND_VERSION)


def play(name: str):
    """Asynchrones Abspielen. Die Synthese oben ist plattformneutral; nur
    dieses Playback ist Windows-spezifisch (lazy Import, damit das Modul
    ueberall importierbar bleibt - darwin bekommt ein eigenes Backend)."""
    path = os.path.join(SOUND_DIR, f"{name}.wav")
    if os.path.exists(path) and sys.platform == "win32":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
