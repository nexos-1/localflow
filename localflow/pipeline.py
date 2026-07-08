"""Kern-Pipeline: Audio -> STT -> Dictionary/Snippets -> AI-Cleanup -> Ergebnis.

Von der Live-App und von Tests gleichermassen nutzbar (Audio kommt als
NumPy-Array oder Dateipfad rein, Ergebnis kommt als PipelineResult raus).
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field

from .cleanup import Cleaner
from .db import Database
from .settings import Settings
from .stt_factory import make_transcriber

log = logging.getLogger("localflow.pipeline")


@dataclass
class PipelineResult:
    asr_text: str = ""
    final_text: str = ""
    language: str | None = None
    stt_ms: float = 0.0
    cleanup_ms: float = 0.0
    total_ms: float = 0.0
    status: str = "ok"          # ok | empty | error
    used_dictionary_ids: list = field(default_factory=list)
    commands: list = field(default_factory=list)  # erkannte Tasten (Sprech-Reihenfolge)


class Pipeline:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        # Engine haengt von der Plattform ab (stt_factory): faster-whisper
        # auf Windows (CUDA/CPU), mlx-whisper (Metal) auf Apple Silicon.
        self.transcriber = None
        self.cleaner: Cleaner | None = None
        # Serialisiert die GPU-Inferenz: zwei parallele Diktate wuerden sonst
        # gleichzeitig auf der GPU laufen (kann selbst erst das CUDA-OOM
        # ausloesen) und beide gleichzeitig ein CPU-Modell nachladen.
        self._infer_lock = threading.Lock()

    def load(self):
        """Modelle laden (blockiert; beim App-Start im Hintergrund aufrufen)."""
        self.transcriber = make_transcriber(self.settings.get("whisper_model"))
        self.cleaner = Cleaner(
            model=self.settings.get("ollama_model"),
            base_url=self.settings.get("ollama_url"),
            timeout=self.settings.get("cleanup_timeout_s"),
        )
        self.cleaner.warmup()

    def _initial_prompt(self, entries: list[dict]) -> str | None:
        """Bias-Woerter (Eigennamen etc.) als Whisper-Hinweis.
        Bewusst OHNE Label wie "Glossar:" - Whisper echot den Prompt bei
        kurzen/leisen Aufnahmen, und das Label wurde dem Nutzer als Text
        eingefuegt. Der Echo-Filter sitzt in stt.transcribe()."""
        words = [e["phrase"] for e in entries if not e["replacement"] and not e["is_snippet"]]
        if not words:
            return None
        return ", ".join(words[:40])

    def _apply_dictionary(self, text: str, entries: list[dict], result: PipelineResult) -> str:
        """Snippets expandieren und Ersetzungen anwenden (case-insensitive, Wortgrenzen)."""
        for e in entries:
            if not e["replacement"]:
                continue
            pattern = re.compile(r"\b" + re.escape(e["phrase"]) + r"\b", re.IGNORECASE)
            # Replacement als Funktion, nicht als String: re wuerde einen
            # String als Template parsen und bei Backslashes (z.B. Windows-
            # Pfade wie C:\Users) mit "bad escape" jedes Diktat crashen.
            new_text, n = pattern.subn(lambda m, r=e["replacement"]: r, text)
            if n:
                text = new_text
                result.used_dictionary_ids.append(e["id"])
        return text

    def _transcribe_resilient(self, audio, language, initial_prompt):
        """Transkribieren mit Notfall-Fallback: stirbt CUDA zur Laufzeit
        (z.B. VRAM von anderer App belegt), wird einmalig auf CPU neu geladen
        statt jedes Diktat mit "Fehler" zu quittieren."""
        kwargs = dict(language=language, initial_prompt=initial_prompt,
                      allowed_languages=self.settings.get("allowed_languages"),
                      beam_size=self.settings.get("beam_size"))
        with self._infer_lock:
            try:
                return self.transcriber.transcribe(audio, **kwargs)
            except Exception as e:  # noqa: BLE001
                if self.transcriber.device != "cuda":
                    raise
                log.warning("CUDA-Transkription fehlgeschlagen (%s) - lade CPU-Fallback", e)
                self.transcriber = make_transcriber(self.settings.get("whisper_model"),
                                                    device="cpu")
                return self.transcriber.transcribe(audio, **kwargs)

    def transcribe_preview(self, audio) -> str:
        """Schneller Roh-Transkript-Durchlauf fuer die Live-Vorschau: nur STT,
        KEIN Cleanup/Dictionary. Teilt sich den GPU-Lock mit dem finalen Lauf:
        ein beim Loslassen noch laufender Preview-Durchlauf kann process()
        daher kurz verzoegern - der Lock stellt sicher, dass sich beide nie
        ueberlappen."""
        if self.transcriber is None:
            return ""
        lang = self.settings.get("language")
        language = None if lang == "auto" else lang
        try:
            with self._infer_lock:
                text, _lang, _info = self.transcriber.transcribe(
                    audio, language=language,
                    allowed_languages=self.settings.get("allowed_languages"),
                    beam_size=self.settings.get("beam_size"))
            return text
        except Exception:  # noqa: BLE001 - Vorschau darf nie das Diktat stoeren
            log.debug("Preview-Transkription fehlgeschlagen", exc_info=True)
            return ""

    def process(self, audio, duration_s: float | None = None) -> PipelineResult:
        """audio: NumPy float32 16kHz mono oder Dateipfad."""
        assert self.transcriber is not None, "Pipeline.load() zuerst aufrufen"
        result = PipelineResult()
        t_start = time.perf_counter()
        entries = self.db.get_dictionary()

        lang_setting = self.settings.get("language")
        language = None if lang_setting == "auto" else lang_setting

        t0 = time.perf_counter()
        try:
            text, detected, _info = self._transcribe_resilient(
                audio, language=language,
                initial_prompt=self._initial_prompt(entries))
        except Exception as e:  # noqa: BLE001
            log.error("STT fehlgeschlagen: %s", e)
            result.status = "error"
            return result
        result.stt_ms = (time.perf_counter() - t0) * 1000
        result.asr_text = text
        result.language = detected

        # Sprachbefehle am Ende erkennen und abschneiden - auf dem ROH-Text
        # vor dem Cleanup, sonst formatiert das LLM die Befehlsphrase um.
        if self.settings.get("voice_commands_enabled"):
            from .commands import extract_trailing_commands
            text, result.commands = extract_trailing_commands(
                text, self.settings.get("voice_commands"))

        if not text.strip():
            # Reiner Befehl ("press enter") ist ok - nur bei WEDER Text NOCH
            # Befehl ist es ein leeres Diktat.
            result.status = "ok" if result.commands else "empty"
            result.total_ms = (time.perf_counter() - t_start) * 1000
            return result

        min_words = self.settings.get("cleanup_min_words") or 0
        if (self.settings.get("ai_cleanup") and self.cleaner is not None
                and len(text.split()) >= min_words):
            t0 = time.perf_counter()
            text = self.cleaner.clean(text, detected)
            result.cleanup_ms = (time.perf_counter() - t0) * 1000

        text = self._apply_dictionary(text, entries, result)

        result.final_text = text
        result.total_ms = (time.perf_counter() - t_start) * 1000
        for did in result.used_dictionary_ids:
            self.db.mark_dictionary_used(did)
        return result

    def record_history(self, result: PipelineResult, app: str = "", window_title: str = "",
                       duration_s: float | None = None, pasted: bool = True):
        self.db.add_history(
            asr_text=result.asr_text,
            formatted_text=result.final_text,
            # pasted_text speichert nicht den ganzen Text nochmal (nie gelesen);
            # nur ein Marker, ob eingefuegt wurde.
            pasted_text="1" if pasted else None,
            language=result.language,
            app=app,
            window_title=window_title,
            duration_s=duration_s,
            latency_ms=result.total_ms,
            stt_ms=result.stt_ms,
            cleanup_ms=result.cleanup_ms,
            num_words=len(result.final_text.split()),
            status=result.status,
        )
