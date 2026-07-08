"""Funktionaler Test der mlx-whisper-Engine (stt_mlx) auf Apple Silicon.

Laeuft in CI auf echten macOS-Runnern (mlx-bench-Workflow) - prueft, dass
die Factory auf dem Mac die Metal-Engine waehlt und dass Transkription,
Stille-Guards und Sprachrestriktion durch die gemeinsame Schnittstelle
funktionieren. Audio kommt aus der macOS-TTS (wie bench_stt_ci).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if sys.platform != "darwin":
    sys.exit("Dieser Test braucht macOS (mlx/Metal).")

import numpy as np  # noqa: E402
from bench_stt_ci import make_audio  # noqa: E402


def main():
    from localflow.stt_factory import make_transcriber
    from localflow.stt_mlx import MlxTranscriber

    # 1. Factory waehlt auf dem Mac die Metal-Engine
    tr = make_transcriber("large-v3-turbo")
    assert isinstance(tr, MlxTranscriber), f"Factory waehlte {type(tr).__name__}"
    assert tr.device == "metal" and tr.compute_type == "mlx"
    print(f"Engine: {type(tr).__name__} auf {tr.device}/{tr.compute_type} ({tr.repo})")

    # 2. Echte Transkription (TTS-Audio, bekannter englischer Text)
    tmp = tempfile.mkdtemp()
    audio = make_audio(os.path.join(tmp, "bench.wav"))
    text, lang, info = tr.transcribe(audio, allowed_languages=["en", "de"])
    print(f"Transkript ({lang}): {text[:90]!r}")
    assert lang == "en", f"Sprache {lang} statt en"
    low = text.lower()
    assert "latency" in low and "dictation" in low, f"Kerntext fehlt: {text!r}"
    assert info.language == "en"

    # 3. Stille -> muss leer sein (Guards greifen auch auf der mlx-Engine)
    silence = np.zeros(16000 * 2, dtype=np.float32)
    text, _, _ = tr.transcribe(silence, allowed_languages=["en", "de"])
    print(f"Stille: text={text!r}")
    assert text == "", f"Stille ergab Text: {text!r}"

    # 4. Leises Rauschen -> keine bekannte Halluzination
    rng = np.random.default_rng(42)
    noise = (rng.standard_normal(16000 * 3) * 0.008).astype(np.float32)
    text, _, _ = tr.transcribe(noise, allowed_languages=["en", "de"])
    print(f"Rauschen: text={text!r}")
    assert text.strip().lower().rstrip(".!?") not in (
        "vielen dank", "untertitelung des zdf", "thank you"), text

    # 5. Sprachrestriktion: en-Audio, aber nur "de" erlaubt -> Retranskription
    #    mit erzwungener Sprache (Inhalt ist dann egal, nur der Pfad zaehlt)
    _, lang, _ = tr.transcribe(audio, allowed_languages=["de"])
    print(f"Restriktion auf de: lang={lang}")
    assert lang == "de", f"Restriktion griff nicht: {lang}"

    print("\nMLX STT TESTS PASSED")


if __name__ == "__main__":
    main()
