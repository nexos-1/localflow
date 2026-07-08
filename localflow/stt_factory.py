"""Engine-Wahl fuer STT: faster-whisper (CUDA/CPU) auf Windows, mlx-whisper
(Metal) auf Apple Silicon. Beide Engines werden lazy importiert - keine wird
geladen, bevor sie gebraucht wird (faster-whisper zieht sonst auch auf dem
Mac ctranslate2 hoch)."""

import logging
import sys

log = logging.getLogger("localflow.stt")


def make_transcriber(model_name: str, device: str = "auto"):
    """Gibt einen Transcriber mit einheitlicher Schnittstelle zurueck:
    .transcribe(audio, language, initial_prompt, allowed_languages, beam_size)
    -> (text, detected_language, info) sowie .device/.compute_type/.model_name.

    device="auto" waehlt die beste Engine der Plattform; ein explizites
    device ("cpu"/"cuda") erzwingt faster-whisper (Notfall-Fallbacks)."""
    if sys.platform == "darwin" and device == "auto":
        try:
            from .stt_mlx import MlxTranscriber
            return MlxTranscriber(model_name)
        except Exception as e:  # noqa: BLE001 - Intel-Mac oder mlx fehlt
            log.warning("mlx-whisper nicht nutzbar (%s) - Fallback auf "
                        "faster-whisper CPU (fuer Diktat zu langsam, "
                        "siehe PORTING.md 3.9)", e)
    from .stt import Transcriber
    return Transcriber(model_name, device=device)
