"""Engine-unabhaengige Qualitaetsfilter fuer Whisper-Ausgaben.

Geteilt von stt.py (faster-whisper) und stt_mlx.py (mlx-whisper). Arbeitet
auf einfachen (text, avg_logprob, no_speech_prob)-Tupeln, damit keine der
beiden Engines importiert werden muss.
"""

import logging
import re

log = logging.getLogger("localflow.stt")

# Bekannte Whisper-Halluzinationen auf Stille (nur verworfen, wenn zusaetzlich
# die Qualitaetssignale schlecht sind - siehe _is_hallucination)
HALLUCINATION_PHRASES = {
    "vielen dank", "danke", "thank you", "thanks for watching",
    "untertitelung des zdf", "untertitel im auftrag des zdf",
    "untertitel der amara.org-community", "copyright wdr",
    "das war's", "bis zum naechsten mal", "tschuess", "glossar",
}


def _is_hallucination(segs: list[tuple[str, float, float]]) -> bool:
    """Gesamttext als Halluzination einstufen, wenn er einer bekannten
    Stille-Phrase entspricht UND die Modell-Signale schwach sind."""
    if not segs:
        return False
    text = " ".join(t.strip() for t, _, _ in segs).strip().lower().rstrip(".!?")
    avg_lp = sum(lp for _, lp, _ in segs) / len(segs)
    max_nsp = max(nsp for _, _, nsp in segs)
    return text in HALLUCINATION_PHRASES and (avg_lp < -0.5 or max_nsp > 0.5)


def drop_low_quality(segs: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    """Segmente mit hoher No-Speech-Wahrscheinlichkeit und schlechtem Logprob
    verwerfen (klassische Whisper-Halluzinationen bei Stille/Rauschen); ist
    der Rest insgesamt eine bekannte Stille-Phrase, alles verwerfen."""
    kept = [s for s in segs if not (s[2] > 0.6 and s[1] < -1.0)]
    if _is_hallucination(kept):
        # Kein Klartext ins Log (Projektpolicy) - nur Metadaten.
        log.info("Halluzination verworfen (%d Segmente)", len(kept))
        kept = []
    return kept


def strip_prompt_echo(text: str, initial_prompt: str | None, avg_logprob: float) -> str:
    """Prompt-Echo-Filter: Whisper gibt bei kurzen/leisen Aufnahmen gern den
    initial_prompt (Woerterbuch-Bias) wieder aus - das wurde dem Nutzer live
    als Text eingefuegt ("Glossar"-Bug). Besteht die Ausgabe NUR aus
    Prompt-Woertern und sind die Modell-Signale schwach, verwerfen."""
    if not (text and initial_prompt):
        return text
    prompt_words = set(re.findall(r"\w+", initial_prompt.lower()))
    text_words = set(re.findall(r"\w+", text.lower()))
    if text_words and text_words <= prompt_words and avg_logprob < -0.4:
        # Kein Klartext ins Log (Projektpolicy) - nur Metadaten.
        log.info("Prompt-Echo verworfen (logprob %.2f, %d Woerter)",
                 avg_logprob, len(text.split()))
        return ""
    return text
