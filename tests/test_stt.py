"""Smoke-Test: Whisper large-v3-turbo auf CUDA, transkribiert die TTS-WAVs."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from localflow.stt import Transcriber

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")

t0 = time.perf_counter()
tr = Transcriber()
print(f"MODEL LOADED: device={tr.device} compute={tr.compute_type} in {time.perf_counter()-t0:.1f}s")

for name, lang in [("test_de.wav", "de"), ("test_en.wav", "en")]:
    path = os.path.join(AUDIO_DIR, name)
    t0 = time.perf_counter()
    text, detected, info = tr.transcribe(path)
    dt = time.perf_counter() - t0
    print(f"\n{name}: detected={detected} (expected {lang}), {dt*1000:.0f} ms")
    print("  TEXT:", text)
    assert detected == lang, f"Spracherkennung falsch: {detected} != {lang}"
    assert len(text) > 20, "Transkript zu kurz"

print("\nSTT SMOKE TEST PASSED")
