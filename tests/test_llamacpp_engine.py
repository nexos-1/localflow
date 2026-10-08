"""Tests: llama.cpp-Cleanup-Engine (LlamaCppCleaner + make_cleaner).

Abgedeckt: (1-3) Engine-Auswahl inkl. Ollama-Fallback bei fehlenden Dateien,
(4) nicht startbarer Server -> Ollama uebernimmt, Neustart-Sperre greift,
(5-7) ECHTER llama-server aus data/llamacpp (uebersprungen, wenn nicht
vorhanden): Start, Cleanup, Beenden; Absturz-Schutz per Job-Objekt (Eltern-
prozess wird hart beendet -> Server stirbt mit).
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import localflow.settings as settings_mod  # noqa: E402
from localflow.cleanup import Cleaner, LlamaCppCleaner, make_cleaner  # noqa: E402


class _Settings(dict):
    def get(self, key):
        return super().get(key, settings_mod.DEFAULTS.get(key))


# 1. Engine "ollama" -> reiner Ollama-Cleaner
c = make_cleaner(_Settings(cleanup_engine="ollama"))
assert type(c) is Cleaner
print("1. cleanup_engine=ollama -> Ollama OK")

# 2. llamacpp, aber Dateien fehlen -> Ollama
with tempfile.TemporaryDirectory() as d, mock.patch.object(settings_mod, "APP_DIR", d):
    c = make_cleaner(_Settings(cleanup_engine="llamacpp"))
    assert type(c) is Cleaner
print("2. llamacpp ohne Server/Modell -> Ollama OK")

# 3. llamacpp mit Dateien -> LlamaCppCleaner mit Ollama-Fallback, Standardpfade
with tempfile.TemporaryDirectory() as d, mock.patch.object(settings_mod, "APP_DIR", d):
    exe = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for rel in (("llamacpp", "bin", exe),
                ("llamacpp", "models", "gemma-3-4b-it-Q4_K_M.gguf")):
        os.makedirs(os.path.join(d, *rel[:-1]), exist_ok=True)
        open(os.path.join(d, *rel), "w").close()
    c = make_cleaner(_Settings(cleanup_engine="llamacpp", ollama_model="gemma3:4b"))
    assert isinstance(c, LlamaCppCleaner) and isinstance(c.fallback, Cleaner)
    assert c.server_path.endswith(exe) and c.idle_s == 7200
    c.timeout = 3.0
    c.model = "x:1b"  # Dashboard-Setter wirken auf den Fallback
    assert c.fallback.timeout == 3.0 and c.fallback.model == "x:1b"
print("3. llamacpp mit Dateien -> LlamaCppCleaner + Fallback OK")

# 4. Server nicht startbar -> Ollama-Fallback, kein Startversuch bei jedem Diktat
fb = mock.Mock(spec=Cleaner)
fb.clean.side_effect = lambda t, lang=None: "FALLBACK:" + t
c = LlamaCppCleaner(os.path.join(tempfile.gettempdir(), "gibt-es-nicht.exe"),
                    "egal.gguf", fallback=fb)
starts = []
orig_start = c._start
c._start = lambda: starts.append(1) or orig_start()
assert c.clean("eins zwei drei vier") == "FALLBACK:eins zwei drei vier"
assert c.clean("fuenf sechs sieben acht") == "FALLBACK:fuenf sechs sieben acht"
assert len(starts) == 1, starts
c.warmup()
fb.warmup.assert_called_once()
print("4. Server fehlt -> Ollama uebernimmt, nur 1 Startversuch OK")

# --- Echter Server ---
DATA = os.path.join(ROOT, "data", "llamacpp")
SERVER = os.path.join(DATA, "bin", "llama-server.exe")
MODEL = os.path.join(DATA, "models", "gemma-3-4b-it-Q4_K_M.gguf")
if sys.platform != "win32" or not (os.path.isfile(SERVER) and os.path.isfile(MODEL)):
    print("5-7 uebersprungen (kein llama-server/Modell in data/llamacpp)")
    sys.exit(0)

import psutil  # noqa: E402

# 5. Start + Cleanup + Beenden
fb = mock.Mock(spec=Cleaner)
c = LlamaCppCleaner(SERVER, MODEL, timeout=30, fallback=fb)
t0 = time.perf_counter()
assert c.ensure_running(), "llama-server startet nicht"
start_s = time.perf_counter() - t0
pid = c._proc.pid
out = c.clean("ähm also das meeting ist morgen um zehn und nicht um neun", "de")
assert "Meeting" in out and ("10" in out or "zehn" in out), out
ts = []
for _ in range(5):
    t0 = time.perf_counter()
    c.clean("okay schreib dem team dass wir den release auf donnerstag verschieben", "de")
    ts.append(time.perf_counter() - t0)
fb.clean.assert_not_called()
print(f"5. echter Server: Start {start_s:.1f}s, warm median "
      f"{sorted(ts)[2] * 1000:.0f}ms, Ausgabe: {out!r} OK")

c.close()
time.sleep(0.5)
assert not psutil.pid_exists(pid), "llama-server laeuft nach close() weiter"
print("6. close() beendet den Server OK")

# 7. Elternprozess hart killen -> Job-Objekt nimmt den Server mit
child = textwrap.dedent(f"""
    import sys, time
    sys.path.insert(0, {ROOT!r})
    from localflow.cleanup import LlamaCppCleaner
    c = LlamaCppCleaner({SERVER!r}, {MODEL!r})
    assert c.ensure_running()
    print(c._proc.pid, flush=True)
    time.sleep(120)
""")
parent = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True)
server_pid = int(parent.stdout.readline())
assert psutil.pid_exists(server_pid)
parent.kill()  # TerminateProcess: kein atexit, kein close()
parent.wait()
deadline = time.monotonic() + 5
while psutil.pid_exists(server_pid) and time.monotonic() < deadline:
    time.sleep(0.2)
assert not psutil.pid_exists(server_pid), "verwaister llama-server nach hartem Kill"
print("7. harter Kill von LocalFlow nimmt den Server mit OK")

# 8. Waisen-Aufraeumer laesst Server eines LEBENDEN Elternprozesses in Ruhe
#    (Feldbefund 2026-10-08: ein Test-Cleaner hat den Server der laufenden
#    App mit beendet, solange nur die Programmdatei verglichen wurde)
parent = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True)
other_pid = int(parent.stdout.readline())
c = LlamaCppCleaner(SERVER, MODEL, timeout=30)
try:
    assert c.ensure_running()
    assert psutil.pid_exists(other_pid), "fremder llama-server mit lebendem Besitzer beendet"
    print("8. Server einer anderen lebenden Instanz bleibt unangetastet OK")
finally:
    c.close()
    parent.kill()
    parent.wait()
