"""Speech-to-Text mit mlx-whisper (Metal) fuer Apple Silicon.

Gleiche Schnittstelle wie stt.Transcriber, damit die Pipeline die Engine
nicht kennt. Warum eine zweite Engine: ctranslate2 hat auf macOS kein
Metal-Backend, und large-v3-turbo auf CPU ist unbenutzbar langsam
(gemessen ~20 s fuer 16 s Audio, PORTING.md 3.9). mlx-whisper (Metal) auf
demselben GitHub-Runner mit paravirtualisierter GPU: 3.5 s - echte
M-Serie-Hardware ist deutlich schneller. Benchmarks: tests/bench_mlx_ci.py.

Unterschiede zu faster-whisper, die hier ausgeglichen werden:
- Ausgabe sind Segment-Dicts statt Objekte; kein all_language_probs, daher
  faellt die Sprachrestriktion auf die erste erlaubte Sprache zurueck.
- Kein beam_size (mlx-whisper dekodiert greedy) - Parameter wird ignoriert.
- Kein VAD-Filter; die internen no_speech/logprob-Schwellen von mlx-whisper
  plus unsere geteilten Filter (stt_quality) uebernehmen die Stille-Abwehr.
- Audio muss als float32-Array (16 kHz mono) kommen; Dateipfade wuerden
  ffmpeg brauchen. Die App liefert ohnehin nur Puffer.
"""

import logging
import time
from types import SimpleNamespace

from .stt_quality import drop_low_quality, strip_prompt_echo

log = logging.getLogger("localflow.stt")

# faster-whisper-Modellnamen -> mlx-community-Repos. Nur large-v3-turbo ist
# CI-verifiziert (tests/bench_mlx_ci.py); explizite HF-Repos ("org/name")
# werden unveraendert durchgereicht.
_MLX_REPOS = {
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny",
}


class MlxTranscriber:
    """Laedt das Whisper-Modell einmal (mlx-whisper cached intern pro Repo)
    und haelt es fuer die Prozess-Lebensdauer im Speicher."""

    def __init__(self, model_name: str = "large-v3-turbo"):
        import mlx.core as mx
        import numpy as np

        if not (getattr(mx, "metal", None) and mx.metal.is_available()):
            # Ohne Metal (Intel-Mac) waere mlx auf CPU sinnlos - der Aufrufer
            # (stt_factory) faellt dann auf faster-whisper zurueck.
            raise RuntimeError("Metal nicht verfuegbar")

        self.model_name = model_name
        self.repo = (model_name if "/" in model_name
                     else _MLX_REPOS.get(model_name, _MLX_REPOS["large-v3-turbo"]))
        self.device = "metal"
        self.compute_type = "mlx"

        # Warmup mit 0.5 s Stille: zieht Download+Load an den App-Start statt
        # ins erste Diktat (mlx_whisper laedt das Modell beim ersten Aufruf).
        t0 = time.perf_counter()
        self._transcribe_raw(np.zeros(8000, dtype=np.float32), None, None)
        log.info("mlx-whisper %s geladen (Metal) in %.1fs",
                 self.repo, time.perf_counter() - t0)

    def _transcribe_raw(self, audio, language, initial_prompt):
        import mlx_whisper
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.repo,
            language=language,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,  # verhindert Fehler-Fortpflanzung/Loops
        )
        segs = [(s.get("text", ""), s.get("avg_logprob", 0.0),
                 s.get("no_speech_prob", 0.0)) for s in result.get("segments", [])]
        return result.get("language"), segs

    def transcribe(self, audio, language: str | None = None,
                   initial_prompt: str | None = None,
                   allowed_languages: list[str] | None = None,
                   beam_size: int = 1):
        """audio: float32-NumPy-Array (16 kHz mono).
        Gibt (text, detected_language, info) zurueck; text ist "" wenn nur
        Stille/Halluzination erkannt wurde. beam_size wird ignoriert (greedy)."""
        import numpy as np

        # Energie-Gate: mlx-whisper hat keinen VAD-Filter und halluziniert
        # auf digitaler Stille (z.B. gemutetes Mikrofon) "Thank you." MIT
        # guten Signalwerten - die logprob/no-speech-Filter greifen dann
        # nicht (CI-verifiziert). Unter der Hoerbarkeitsschwelle gar nicht
        # erst dekodieren. Echte leise Sprache liegt weit darueber.
        if isinstance(audio, np.ndarray) and (
                audio.size == 0 or float(np.abs(audio).max()) < 1e-3):
            lang = language or (allowed_languages[0] if allowed_languages else None)
            return "", lang, SimpleNamespace(language=lang, all_language_probs=None)

        detected, segs = self._transcribe_raw(audio, language, initial_prompt)

        # Detektierte Sprache ausserhalb der Nutzersprachen? mlx-whisper
        # liefert keine Wahrscheinlichkeits-Liste, also mit der ersten
        # erlaubten Sprache erneut transkribieren.
        if language is None and allowed_languages and detected not in allowed_languages:
            best = allowed_languages[0]
            log.info("Sprache %s nicht erlaubt, retranskribiere als %s", detected, best)
            detected, segs = self._transcribe_raw(audio, best, initial_prompt)

        kept = drop_low_quality(segs)
        text = " ".join(t.strip() for t, _, _ in kept).strip()
        if kept:
            avg_lp = sum(lp for _, lp, _ in kept) / len(kept)
            text = strip_prompt_echo(text, initial_prompt, avg_lp)

        info = SimpleNamespace(language=detected, all_language_probs=None)
        return text, detected, info
