"""System-Audio waehrend der Aufnahme stummschalten - schnell und robust.

Architektur: EIN dedizierter Worker-Thread besitzt alle COM-Zugriffe und
arbeitet Kommandos (duck/restore) seriell aus einer Queue ab - keine
Thread-Races auf den Session-Interfaces.

- Mute: sehr schneller Fade (~45 ms) auf duck_volume (Default 0 = stumm).
- mute_complete_ts (time.monotonic) wird gesetzt, sobald alles stumm ist -
  damit schneidet die Aufnahme den Anfang weg, in dem z.B. YouTube noch
  hoerbar war (siehe main._process).
- Waechter: Sessions, die waehrend der Aufnahme Audio starten, werden sofort
  gemutet.
- Crash-Schutz: Originalpegel liegen waehrend des Mutes in einer State-Datei;
  beim naechsten App-Start werden verwaiste Pegel wiederhergestellt.
- Schnelle Folge duck->restore->duck ist sicher: Original-Pegel bleiben
  erhalten, ein laufender Restore-Fade wird abgebrochen und neu gemutet.
"""

import json
import logging
import os
import queue
import threading
import time

from .settings import APP_DIR

log = logging.getLogger("localflow.ducking")

STATE_FILE = os.path.join(APP_DIR, "ducked_volumes.json")

FADE_DOWN_STEPS, FADE_DOWN_S = 3, 0.045
FADE_UP_STEPS, FADE_UP_S = 5, 0.12
WATCH_INTERVAL_S = 0.3


def _session_key(s) -> str:
    try:
        from pycaw.pycaw import IAudioSessionControl2
        ident = s._ctl.QueryInterface(IAudioSessionControl2).GetSessionInstanceIdentifier()  # noqa: SLF001
        if ident:
            return ident
    except Exception:  # noqa: BLE001
        pass
    return f"pid:{s.Process.pid if s.Process else '?'}"


def _proc_name(s) -> str:
    """Prozessname (lowercase) der Session - fuer das Wiederfinden, wenn die
    Session-Instanz stirbt (Windows persistiert Pegel pro App, eine tote
    Instanz liesse die App sonst dauerhaft auf duck_volume)."""
    try:
        return (s.Process.name() or "").lower() if s.Process else ""
    except Exception:  # noqa: BLE001
        return ""


class AudioDucker:
    def __init__(self, duck_volume: float = 0.0):
        self.duck_volume = max(0.0, min(1.0, duck_volume or 0.0))
        self._q: queue.Queue = queue.Queue()
        self._muted = False
        # Oeffentlich lesbar (nur vom Worker geschrieben):
        self.is_muted = False
        self.mute_complete_ts = 0.0     # time.monotonic, wann alles stumm war
        self.did_mute_sessions = 0      # wie viele Sessions beim letzten duck() stumm wurden
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="localflow-ducker")
        self._worker.start()

    # ---------- oeffentliche API (thread-sicher, nicht blockierend) ----------

    def duck(self):
        self._q.put("duck")

    def restore(self):
        self._q.put("restore")

    # ---------- Worker ----------

    def _run(self):
        import comtypes
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        self._restore_leftovers()
        saved: dict[str, tuple] = {}   # key -> (vol_iface, original, prozessname)

        while True:
            try:
                cmd = self._q.get(timeout=WATCH_INTERVAL_S if self._muted else None)
            except queue.Empty:
                cmd = None

            if cmd == "duck":
                t0 = time.monotonic()
                for key, vol, orig, pname in self._collect(exclude=saved):
                    saved[key] = (vol, orig, pname)
                self._write_state(saved)
                self._fade([(v, o) for v, o, _ in saved.values()], down=True,
                           steps=FADE_DOWN_STEPS, dur=FADE_DOWN_S)
                self._muted = True
                self.is_muted = True
                self.did_mute_sessions = len(saved)
                self.mute_complete_ts = time.monotonic()
                if saved:
                    log.info("Audio stumm in %.0f ms (%d Sessions)",
                             (self.mute_complete_ts - t0) * 1000, len(saved))

            elif cmd == "restore" and self._muted:
                completed = self._fade([(v, o) for v, o, _ in saved.values()],
                                       down=False,
                                       steps=FADE_UP_STEPS, dur=FADE_UP_S,
                                       abort_on_cmd=True)
                if completed:
                    dead = []
                    for vol, orig, pname in saved.values():
                        try:
                            vol.SetMasterVolume(orig, None)
                        except Exception as e:  # noqa: BLE001
                            # NICHT still schlucken: eine tote Session liesse
                            # die App dauerhaft leise (Windows merkt sich den
                            # Pegel pro App) - unten via Prozessname heilen.
                            dead.append((orig, pname, e))
                    healed = self._heal_dead_sessions(dead) if dead else 0
                    log.info("Audio restauriert (%d Sessions%s)", len(saved),
                             f", {len(dead)} tot, {healed} geheilt" if dead else "")
                    saved = {}
                    self._muted = False
                    self.is_muted = False
                    self._clear_state()
                # abgebrochen -> naechstes Kommando (duck) mutet wieder;
                # Original-Pegel bleiben in `saved` erhalten.

            elif cmd is None and self._muted:
                # Waechter: mittendrin startende Sessions sofort muten
                fresh = self._collect(exclude=saved)
                for key, vol, orig, pname in fresh:
                    saved[key] = (vol, orig, pname)
                    try:
                        vol.SetMasterVolume(orig * self.duck_volume, None)
                    except Exception:  # noqa: BLE001
                        pass
                if fresh:
                    self._write_state(saved)
                    log.info("%d neue Session(s) waehrend Aufnahme gemutet", len(fresh))

    def _collect(self, exclude: dict) -> list[tuple]:
        """Alle fremden hoerbaren Sessions, die noch nicht getrackt sind."""
        from pycaw.pycaw import AudioUtilities
        own_pid = os.getpid()
        out = []
        try:
            for s in AudioUtilities.GetAllSessions():
                if s.Process is not None and s.Process.pid == own_pid:
                    continue
                vol = s.SimpleAudioVolume
                if vol is None:
                    continue
                key = _session_key(s)
                if key in exclude:
                    continue
                try:
                    orig = vol.GetMasterVolume()
                except Exception:  # noqa: BLE001
                    continue
                if orig > 0.01:
                    out.append((key, vol, orig))
        except Exception as e:  # noqa: BLE001
            log.warning("Audio-Sessions nicht lesbar: %s", e)
        return out

    def _fade(self, entries: list[tuple], down: bool, steps: int, dur: float,
              abort_on_cmd: bool = False) -> bool:
        """Von der AKTUELLEN Lautstaerke zum Ziel faden (nicht vom Original -
        wichtig fuer abgebrochene Fades). True, wenn vollstaendig."""
        starts = []
        for vol, orig in entries:
            try:
                starts.append(vol.GetMasterVolume())
            except Exception:  # noqa: BLE001
                starts.append(orig if not down else orig * self.duck_volume)
        for step in range(1, steps + 1):
            if abort_on_cmd and not self._q.empty():
                return False
            t = step / steps
            for (vol, orig), start in zip(entries, starts):
                goal = orig * self.duck_volume if down else orig
                try:
                    vol.SetMasterVolume(start + (goal - start) * t, None)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(dur / steps)
        return True

    # ---------- Crash-Schutz ----------

    def _write_state(self, saved: dict):
        try:
            data = {key: orig for key, (vol, orig) in saved.items()}
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:  # noqa: BLE001
            log.debug("State-Datei nicht schreibbar", exc_info=True)

    def _clear_state(self):
        try:
            os.remove(STATE_FILE)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            pass

    def _restore_leftovers(self):
        """Nach einem Crash waehrend des Mutes: verwaiste 0%-Pegel reparieren."""
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception:  # noqa: BLE001
            self._clear_state()
            return
        restored = 0
        try:
            from pycaw.pycaw import AudioUtilities
            for s in AudioUtilities.GetAllSessions():
                if s.SimpleAudioVolume is None:
                    continue
                key = _session_key(s)
                if key in data:
                    try:
                        s.SimpleAudioVolume.SetMasterVolume(float(data[key]), None)
                        restored += 1
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
        self._clear_state()
        if restored:
            log.info("Crash-Recovery: %d Session-Pegel wiederhergestellt", restored)
