"""Speech-to-Text mit faster-whisper auf CUDA (Fallback: CPU).

Tuning basiert auf Benchmark mit 20 echten Diktaten (tests/bench_stt_real.py):
- beam_size=1 schlaegt beam_size=5 auf dieser Stimme (WER 3.0% vs 6.1% median)
  und ist schneller.
- Sprachdetektion wird auf die Nutzersprachen eingeschraenkt (ein 0.6s-Clip
  wurde sonst als Russisch transkribiert).
- Segmente mit hoher No-Speech-Wahrscheinlichkeit und schlechtem Logprob
  werden verworfen (klassische Whisper-Halluzinationen bei Stille/Rauschen).
"""

import logging
import os
import sys
import time

from .stt_quality import drop_low_quality, strip_prompt_echo

log = logging.getLogger("localflow.stt")


def _add_nvidia_dll_dirs():
    """Die pip-Wheels nvidia-cublas-cu12 / nvidia-cudnn-cu12 legen ihre DLLs in
    site-packages/nvidia/*/bin ab. ctranslate2 findet sie nur, wenn die
    Verzeichnisse als DLL-Suchpfade registriert sind."""
    for base in sys.path:
        nvidia = os.path.join(base, "nvidia")
        if not os.path.isdir(nvidia):
            continue
        for sub in os.listdir(nvidia):
            bin_dir = os.path.join(nvidia, sub, "bin")
            if os.path.isdir(bin_dir):
                try:
                    os.add_dll_directory(bin_dir)
                except OSError:
                    pass
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()

from faster_whisper import WhisperModel  # noqa: E402

VAD_PARAMS = {"min_silence_duration_ms": 500}


class Transcriber:
    """Laedt das Whisper-Modell einmal und haelt es im Speicher."""

    FALLBACK_CHAIN = [
        ("cuda", "float16"),
        ("cuda", "int8_float16"),
        ("cpu", "int8"),
    ]

    def __init__(self, model_name: str = "large-v3-turbo", device: str = "auto"):
        self.model_name = model_name
        self.model = None
        self.device = None
        self.compute_type = None
        chain = self.FALLBACK_CHAIN if device == "auto" else [(device, "float16" if device == "cuda" else "int8")]
        last_err = None
        for dev, ctype in chain:
            # Erst aus dem lokalen Cache laden (schneller, funktioniert offline);
            # nur wenn das Modell noch nie geladen wurde, den Download erlauben.
            for local_only in (True, False):
                try:
                    t0 = time.perf_counter()
                    self.model = WhisperModel(model_name, device=dev, compute_type=ctype,
                                              local_files_only=local_only)
                    self.device, self.compute_type = dev, ctype
                    log.info("Whisper %s geladen auf %s/%s in %.1fs%s", model_name, dev,
                             ctype, time.perf_counter() - t0,
                             " (Cache)" if local_only else " (Download)")
                    break
                except Exception as e:  # noqa: BLE001 - jede Stufe darf scheitern
                    last_err = e
                    if not local_only:
                        log.warning("Whisper auf %s/%s fehlgeschlagen: %s", dev, ctype, e)
            if self.model is not None:
                break
        if self.model is None:
            raise RuntimeError(f"Whisper konnte nicht geladen werden: {last_err}")

    def _run(self, audio, language, initial_prompt, beam_size):
        segments, info = self.model.transcribe(
            audio,
            language=language,
            initial_prompt=initial_prompt,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=VAD_PARAMS,
            condition_on_previous_text=False,  # verhindert Fehler-Fortpflanzung/Loops
        )
        return list(segments), info

    def transcribe(self, audio, language: str | None = None,
                   initial_prompt: str | None = None,
                   allowed_languages: list[str] | None = None,
                   beam_size: int = 1):
        """audio: Pfad oder float32-NumPy-Array (16 kHz mono).
        Gibt (text, detected_language, info) zurueck; text ist "" wenn nur
        Stille/Halluzination erkannt wurde."""
        segments, info = self._run(audio, language, initial_prompt, beam_size)

        # Detektierte Sprache ausserhalb der Nutzersprachen? Mit der besten
        # erlaubten Sprache erneut transkribieren.
        if language is None and allowed_languages and info.language not in allowed_languages:
            best = None
            for code, prob in (info.all_language_probs or []):
                if code in allowed_languages:
                    best = code
                    break  # all_language_probs ist absteigend sortiert
            best = best or allowed_languages[0]
            log.info("Sprache %s nicht erlaubt, retranskribiere als %s", info.language, best)
            segments, info = self._run(audio, best, initial_prompt, beam_size)

        # Qualitaets-Filter (Stille-Halluzinationen + Prompt-Echo), geteilt
        # mit der mlx-Engine - siehe stt_quality.py
        kept = drop_low_quality([(s.text, s.avg_logprob, s.no_speech_prob)
                                 for s in segments])
        text = " ".join(t.strip() for t, _, _ in kept).strip()
        if kept:
            avg_lp = sum(lp for _, lp, _ in kept) / len(kept)
            text = strip_prompt_echo(text, initial_prompt, avg_lp)

        return text, info.language, info
