"""AI-Cleanup des Roh-Transkripts via Ollama (lokal).

Verhalten kalibriert auf Wispr Flows "light" AI-Formatting, beobachtet an
echten Vorher/Nachher-Paaren: Satzzeichen und Gross-/Kleinschreibung fixen,
Fuellwoerter glaetten, Zahlwoerter zu Ziffern, Bedeutung strikt erhalten.
Der Text ist oft eine Anweisung oder Frage an eine andere KI - sie darf auf
keinen Fall beantwortet werden, nur bereinigt.
"""

import logging
import subprocess
import sys
import threading
import time

import requests

log = logging.getLogger("localflow.cleanup")

SYSTEM_PROMPT = """You are a dictation post-processor. The user dictated text with speech recognition. Your ONLY job is to lightly clean up the raw transcript.

Rules:
- Fix punctuation, capitalization and sentence boundaries.
- Remove filler words (um, uh, aeh, aehm, halt, sozusagen) ONLY when they carry no meaning; keep the wording otherwise.
- Convert spelled-out numbers to digits where a writer would ("zwanzig Punkte" -> "20 Punkte", "point two" -> "point 2").
- Each user message starts with a language tag like [de] or [en]. Your output MUST be entirely in that language. NEVER translate. The tag itself is never part of the output.
- Keep the meaning, tone and person EXACTLY as dictated. Casual stays casual.
- The text is often a question or an instruction addressed to someone else. NEVER answer it, NEVER add anything, NEVER comment. You are not the addressee.
- Output ONLY the cleaned text. No quotes, no explanations, no markdown fences."""

FEW_SHOT = [
    ("[de] plane den echten live Umbau so wie du ihn jetzt gerade gedacht hast plane den Umbau und plane wie es wieder sinnvoll geloest werden kann",
     "Plane den Umbau so, wie du ihn jetzt gerade gedacht hast. Plane den Umbau und plane, wie es wieder sinnvoll geloest werden kann."),
    ("[de] Bei Fuenfzehn aber bitte sehr genau aufpassen, dass alles gut verdrahtet und verlinkt ist und nichts kaputt gemacht wird. Bitte ganz genau sein.",
     "Bei 15 aber bitte sehr genau aufpassen, dass alles gut verdrahtet und verlinkt ist und nichts kaputt gemacht wird. Bitte ganz genau sein."),
    ("[en] um so can you check the login page i think theres something broken with the uh redirect",
     "So can you check the login page? I think there's something broken with the redirect."),
    ("[en] Hey what do you think about the new dashboard is it good enough to ship or should we polish it more",
     "Hey, what do you think about the new dashboard? Is it good enough to ship, or should we polish it more?"),
]


class Cleaner:
    BOOT_WAIT_S = 10.0   # so lange auf einen fremden/frischen Server warten

    def __init__(self, model: str = "gemma3:4b", base_url: str = "http://127.0.0.1:11434",
                 timeout: float = 15.0, keep_alive: str = "30m"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._start_lock = threading.Lock()

    def is_healthy(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/version", timeout=1.5).ok
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _ollama_process_running() -> bool:
        """Existiert bereits irgendein Ollama-Prozess (Tray-App/Server)?
        Direkt nach dem Windows-Login bootet der Ollama-Autostart oft noch,
        waehrend der Port schon/noch nicht antwortet - dann darf LocalFlow
        keinen ZWEITEN Server spawnen, sondern muss nur warten."""
        try:
            import psutil
            for p in psutil.process_iter(["name"]):
                if (p.info.get("name") or "").lower().startswith("ollama"):
                    return True
        except Exception:  # noqa: BLE001
            pass  # ohne psutil-Antwort lieber wie frueher: notfalls spawnen
        return False

    def _wait_healthy(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if self.is_healthy():
                return True
        return False

    def ensure_running(self) -> bool:
        """Ollama-Server pruefen und bei Bedarf starten - garantiert ohne
        Doppelstart: parallele Aufrufe (z.B. App-Warmup + Settings-Save)
        serialisiert ein Lock, und existiert schon ein Ollama-Prozess,
        wird nur auf dessen Server gewartet statt einen zweiten zu spawnen.
        (Ein zweiter Server waere auch OS-seitig chancenlos - Port 11434
        kann nur einmal gebunden werden - aber der Versuch unterbleibt.)"""
        if self.is_healthy():
            return True
        with self._start_lock:
            if self.is_healthy():  # ein paralleler Aufruf war schneller
                return True
            if self._ollama_process_running():
                log.info("Ollama-Prozess existiert schon - warte auf den Server "
                         "statt einen zweiten zu starten...")
                if self._wait_healthy(self.BOOT_WAIT_S):
                    log.info("Ollama-Server bereit")
                    return True
                log.warning("Laufender Ollama-Prozess antwortet nicht - "
                            "versuche eigenen Serverstart")
            else:
                log.info("Ollama nicht erreichbar, versuche Start...")
            try:
                kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if sys.platform == "win32":
                    kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                               | subprocess.DETACHED_PROCESS)
                else:  # POSIX: vom eigenen Prozess entkoppeln
                    kwargs["start_new_session"] = True
                subprocess.Popen(["ollama", "serve"], **kwargs)
            except FileNotFoundError:
                log.error("ollama.exe nicht im PATH - AI-Cleanup nicht verfuegbar")
                return False
            if self._wait_healthy(self.BOOT_WAIT_S):
                log.info("Ollama gestartet")
                return True
            log.error("Ollama-Start fehlgeschlagen (Timeout)")
            return False

    def warmup(self):
        """Modell in den VRAM laden, damit das erste Diktat nicht wartet."""
        try:
            self.ensure_running()
            self.clean("hallo test")
        except Exception as e:  # noqa: BLE001
            log.warning("Ollama-Warmup fehlgeschlagen: %s", e)

    def clean(self, text: str, language: str | None = None) -> str:
        """Gibt bereinigten Text zurueck; bei jedem Fehler den Rohtext (nie blockieren)."""
        text = text.strip()
        if not text:
            return text
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for raw, cleaned in FEW_SHOT:
            messages.append({"role": "user", "content": raw})
            messages.append({"role": "assistant", "content": cleaned})
        tag = f"[{language}] " if language else ""
        messages.append({"role": "user", "content": tag + text})
        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": self.keep_alive,
                    "options": {"temperature": 0.1, "num_predict": 2048},
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            out = r.json()["message"]["content"].strip()
            out = _strip_wrapping(out)
            if not out or not _plausible(text, out):
                # Kein Diktat-Klartext ins Log (Datenschutz) - nur Laengen.
                log.warning("Cleanup-Ausgabe unplausibel (%d->%d Zeichen), nutze Rohtext",
                            len(text), len(out))
                return text
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("Cleanup fehlgeschlagen (%s), nutze Rohtext", e)
            return text


def _strip_wrapping(out: str) -> str:
    """Anfuehrungszeichen/Codefences entfernen, falls das Modell den Text einpackt."""
    if out.startswith("```") and out.endswith("```"):
        out = out.strip("`").strip()
        if out.startswith("text\n"):
            out = out[5:]
    if len(out) > 1 and out[0] in "\"'„“" and out[-1] in "\"'“”":
        out = out[1:-1]
    return out.strip()


def _plausible(raw: str, out: str) -> bool:
    """Schutz dagegen, dass das Modell antwortet statt bereinigt:
    Die Laenge muss in der Naehe des Originals bleiben."""
    rw, ow = len(raw.split()), len(out.split())
    if rw == 0:
        return True
    ratio = ow / rw
    return 0.4 <= ratio <= 1.8
