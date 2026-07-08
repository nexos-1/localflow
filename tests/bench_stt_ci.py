"""STT-Latenz-Benchmark fuer CI auf echtem Apple Silicon (PORTING.md 3.9):
Reicht die CPU fuer Diktat + Live-Vorschau? Erzeugt Sprach-Audio mit dem
macOS-eigenen TTS (`say`), transkribiert mit faster-whisper (CPU-Kette)
und misst Modell-Load, Voll-Transkription und Preview-artige Paesse ueber
wachsende Puffer. Laeuft auch lokal auf einem Mac; auf anderen OS bricht
er mit Hinweis ab."""

import contextlib
import os
import statistics
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if sys.platform != "darwin":
    sys.exit("Dieser Benchmark braucht macOS (`say`/`afconvert`).")

import numpy as np  # noqa: E402

TEXT = ("This is a latency benchmark for local voice dictation. "
        "We measure how quickly the model transcribes growing audio buffers, "
        "similar to the live preview loop that runs while a user keeps "
        "speaking into the microphone. The final pass mirrors a complete "
        "dictation of roughly ten to fifteen seconds of natural speech.")


def make_audio(path_wav: str) -> np.ndarray:
    aiff = path_wav + ".aiff"
    subprocess.run(["say", "-o", aiff, TEXT], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                    aiff, path_wav], check=True)
    with contextlib.closing(wave.open(path_wav, "rb")) as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def main():
    tmp = tempfile.mkdtemp()
    audio = make_audio(os.path.join(tmp, "bench.wav"))
    dur = len(audio) / 16000
    print(f"TTS-Audio: {dur:.1f}s @16kHz mono")

    from localflow.stt import Transcriber
    t0 = time.perf_counter()
    tr = Transcriber("large-v3-turbo")
    print(f"Modell geladen: {time.perf_counter() - t0:.1f}s "
          f"auf {tr.device}/{tr.compute_type}")

    # Voll-Transkription (3 Laeufe, Median) - entspricht dem finalen Pass
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        text, lang, _ = tr.transcribe(audio, allowed_languages=["en", "de"])
        times.append(time.perf_counter() - t0)
    full_ms = statistics.median(times) * 1000
    print(f"\nVOLL ({dur:.1f}s Audio): median {full_ms:.0f} ms  [{lang}]")
    print(f"  Erkannt: {text[:90]!r}")

    # Preview-Simulation: wachsende Puffer wie die Live-Vorschau
    print("\nPREVIEW-Paesse (wachsender Puffer):")
    preview = []
    step = 2.0
    t_audio = step
    while t_audio <= dur:
        chunk = audio[:int(t_audio * 16000)]
        t0 = time.perf_counter()
        tr.transcribe(chunk, allowed_languages=["en", "de"])
        ms = (time.perf_counter() - t0) * 1000
        preview.append(ms)
        print(f"  @{t_audio:4.1f}s -> {ms:6.0f} ms")
        t_audio += step

    worst = max(preview)
    print(f"\nFAZIT: Voll={full_ms:.0f} ms | Preview max={worst:.0f} ms")
    if worst <= 700:
        print("-> CPU reicht fuer die Live-Vorschau im heutigen Takt (~0.4s).")
    elif worst <= 1500:
        print("-> Grenzwertig: Vorschau-Intervall auf Mac strecken oder "
              "mlx-whisper/whisper.cpp einplanen (PORTING.md 3.9).")
    else:
        print("-> CPU zu langsam fuer Live-Vorschau: auf Mac Vorschau "
              "deaktivieren oder Apple-Silicon-Engine (mlx-whisper) noetig.")


if __name__ == "__main__":
    main()
