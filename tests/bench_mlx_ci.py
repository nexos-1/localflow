"""mlx-whisper-Benchmark fuer CI auf Apple Silicon (PORTING.md 3.9):
Beantwortet zwei Fragen: (1) Exponieren die GitHub-macOS-Runner Metal?
(2) Wie schnell ist mlx-whisper (large-v3-turbo) im Vergleich zur
gemessenen CPU-Katastrophe (~20s fuer 16s Audio)?
Nutzt dieselbe TTS-Audio-Erzeugung wie bench_stt_ci."""

import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))

if sys.platform != "darwin":
    sys.exit("Dieser Benchmark braucht macOS.")

import numpy as np  # noqa: E402
from bench_stt_ci import make_audio  # noqa: E402

MODEL = "mlx-community/whisper-large-v3-turbo"


def main():
    import mlx.core as mx
    metal = bool(getattr(mx, "metal", None) and mx.metal.is_available())
    print(f"Metal verfuegbar auf diesem Runner: {metal}")
    if metal:
        try:
            info = mx.metal.device_info()
            print(f"  Geraet: {info.get('device_name', '?')}, "
                  f"RAM {info.get('memory_size', 0) / 2**30:.0f} GB")
        except Exception:  # noqa: BLE001
            pass

    tmp = tempfile.mkdtemp()
    wav_path = os.path.join(tmp, "bench.wav")
    audio = make_audio(wav_path)
    dur = len(audio) / 16000
    print(f"TTS-Audio: {dur:.1f}s @16kHz mono")

    import mlx_whisper

    # Audio als float32-Array uebergeben (kein ffmpeg auf den Runnern;
    # LocalFlow transkribiert in Produktion ohnehin Puffer, keine Dateien)
    audio = audio.astype(np.float32)

    # Kaltstart (inkl. Modell-Download+Load)
    t0 = time.perf_counter()
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=MODEL)
    cold = time.perf_counter() - t0
    print(f"\nKALTSTART (Download+Load+Transkription): {cold:.1f}s")
    print(f"  Sprache: {result.get('language')}  "
          f"Text: {result.get('text', '')[:80]!r}")

    # Warm: Voll-Transkription (3 Laeufe, Median)
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        mlx_whisper.transcribe(audio, path_or_hf_repo=MODEL)
        times.append(time.perf_counter() - t0)
    full_ms = statistics.median(times) * 1000
    print(f"\nVOLL warm ({dur:.1f}s Audio): median {full_ms:.0f} ms")

    # Preview-Simulation: wachsende Puffer
    print("\nPREVIEW-Paesse (wachsender Puffer):")
    preview = []
    t_audio = 2.0
    while t_audio <= dur:
        chunk = audio[:int(t_audio * 16000)]
        t0 = time.perf_counter()
        mlx_whisper.transcribe(chunk, path_or_hf_repo=MODEL)
        ms = (time.perf_counter() - t0) * 1000
        preview.append(ms)
        print(f"  @{t_audio:4.1f}s -> {ms:6.0f} ms")
        t_audio += 2.0

    worst = max(preview)
    print(f"\nFAZIT: Metal={metal} | Voll={full_ms:.0f} ms | "
          f"Preview max={worst:.0f} ms")
    print("Referenz CPU/int8 (stt-bench): Voll ~20000 ms, Preview 18-28s")
    if worst <= 700:
        print("-> mlx-whisper traegt Diktat UND Live-Vorschau auf dem Mac.")
    elif full_ms <= 3000:
        print("-> mlx-whisper traegt das Diktat; Vorschau-Intervall strecken "
              "oder auf echter (unvirtualisierter) Hardware nachmessen.")
    else:
        print("-> Auch mlx zu langsam AUF DIESEM RUNNER - auf echter Hardware "
              "nachmessen (Runner-VMs drosseln die GPU ggf. stark).")


if __name__ == "__main__":
    main()
