"""E2E auf echtem macOS (CI, macos-latest = Apple Silicon): die per
install.sh installierte App starten, mit `say` gesprochene Diktate durch
/api/debug/dictate schicken (mlx-whisper -> llama.cpp-Cleanup -> Woerterbuch,
ohne Paste) und pruefen, dass das Cleanup im eigenen llama-server auf Metal
laeuft. Danach LocalFlow hart beenden (SIGKILL) und neu starten: der
verwaiste Server muss beim naechsten Start aufgeraeumt werden.

Voraussetzung: `bash install.sh` ist gelaufen. Mikrofon und Hotkeys sind auf
dem Runner nicht testbar (keine Freigaben) - das bleibt ein Test am echten Mac.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
import time

import psutil
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.environ.get("LOCALFLOW_DATA_DIR") or os.path.join(ROOT, "data")
LOGS = os.path.join(DATA, "logs")
APP_LOG = os.path.join(LOGS, "localflow.log")
SERVER_LOG = os.path.join(LOGS, "llama-server.log")
SERVER_EXE = os.path.realpath(os.path.join(DATA, "llamacpp", "bin", "llama-server"))
API = "http://127.0.0.1:5111"
HDR = {"X-LocalFlow": "1"}
FILLER = re.compile(r"(?<![\wäöüß])(äh|ähm)(?![\wäöüß])", re.I)

assert sys.platform == "darwin", "nur fuer macOS"
assert os.path.isfile(SERVER_EXE), f"llama-server fehlt ({SERVER_EXE}) - install.sh gelaufen?"


def voice_for(lang: str) -> str:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})", line)
        if m and m.group(2).startswith(lang + "_"):
            return m.group(1).strip()
    raise RuntimeError(f"keine {lang}-Stimme installiert")


def make_wav(text: str, lang: str) -> str:
    path = os.path.join(tempfile.mkdtemp(), f"diktat-{lang}.wav")
    subprocess.run(["say", "-v", voice_for(lang), "-o", path, "--file-format=WAVE",
                    "--data-format=LEI16@16000", text], check=True)
    return path


def log_text() -> str:
    try:
        with open(APP_LOG, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def start_app() -> subprocess.Popen:
    env = dict(os.environ, LOCALFLOW_DEBUG="1")
    out = open(os.path.join(tempfile.gettempdir(), "localflow-stdout.log"), "a")
    return subprocess.Popen([os.path.join(ROOT, ".venv", "bin", "python"), "run.py"],
                            cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)


def wait_for(cond, seconds: float, what: str, app: subprocess.Popen):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if app.poll() is not None:
            raise AssertionError(f"LocalFlow beendet (Code {app.returncode}) waehrend: {what}")
        try:
            if cond():
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    raise AssertionError(f"Timeout ({seconds:.0f}s): {what}")


def our_servers() -> list[psutil.Process]:
    found = []
    for p in psutil.process_iter(["exe"]):
        exe = p.info.get("exe")
        if exe and os.path.realpath(exe) == SERVER_EXE:
            found.append(p)
    return found


def dictate(wav: str) -> dict:
    r = requests.post(f"{API}/api/debug/dictate", json={"wav": wav, "paste": False},
                      headers=HDR, timeout=300)
    r.raise_for_status()
    return r.json()


def boot(label: str) -> subprocess.Popen:
    log_before = len(log_text())
    app = start_app()
    wait_for(lambda: requests.get(f"{API}/api/debug/state", headers=HDR,
                                  timeout=2).json().get("models_ready"),
             1200, f"{label}: Modelle bereit (Whisper-Download beim ersten Start)", app)
    # Metal-Init auf dem CI-Runner ~40s (Diagnose 2026-10-08), Reserve 4x
    wait_for(lambda: "llama-server bereit" in log_text()[log_before:], 240,
             f"{label}: llama-server bereit", app)
    print(f"{label}: App + llama-server bereit")
    return app


wav_de = make_wav("Ähm, also das Meeting ist morgen um zehn Uhr und nicht um neun. "
                  "Kannst du bitte allen Bescheid sagen?", "de")
wav_en = make_wav("um so can you check the login page i think there is something "
                  "broken with the redirect", "en")

# --- 1. Erster Start: Diktate laufen ueber den eigenen llama-server ---
app = boot("Start 1")
try:
    servers = our_servers()
    assert len(servers) == 1, f"erwartet 1 llama-server, gefunden {len(servers)}"
    server = servers[0]
    app_tree = {app.pid} | {c.pid for c in psutil.Process(app.pid).children(recursive=True)}
    assert server.pid in app_tree, "llama-server ist kein Kind von LocalFlow"

    res = dictate(wav_de)
    print("DE:", res)
    assert res["status"] == "ok", res
    assert res["language"] == "de", res
    assert "Meeting" in res["final"], res
    assert not FILLER.search(res["final"]), f"Fuellwort uebrig: {res['final']!r}"
    assert res["cleanup_ms"] > 0, "Cleanup lief nicht"

    res = dictate(wav_en)
    print("EN:", res)
    assert res["status"] == "ok" and res["language"] == "en", res
    assert res["cleanup_ms"] > 0, "Cleanup lief nicht"

    with open(SERVER_LOG, encoding="utf-8", errors="replace") as f:
        slog = f.read()
    assert re.search(r"metal", slog, re.I), "kein Metal im llama-server-Log"
    offload = re.search(r"offloaded (\d+)/(\d+) layers to GPU", slog)
    print("Metal-Offload:", offload.group(0) if offload else "keine Angabe")
    assert offload and int(offload.group(1)) > 0, "keine Schicht auf der GPU"
    assert slog.count("print_timing") > 0, "llama-server hat nichts berechnet"
    log = log_text()
    assert "Cleanup ueber Ollama" not in log and "laeuft ueber Ollama" not in log, \
        "Ollama-Fallback statt llama.cpp"
    print("1. Diktate (de+en) ueber eigenen llama-server auf Metal OK")

    # --- 2. Harter Kill: auf macOS bleibt der Server als Waise stehen ---
    old_pid = server.pid
    app.send_signal(signal.SIGKILL)
    app.wait()
    time.sleep(1)
    print("Nach SIGKILL noch laufend:", [p.pid for p in our_servers()])
finally:
    if app.poll() is None:
        app.send_signal(signal.SIGKILL)
        app.wait()

# --- 3. Neustart raeumt die Waise auf und startet genau einen neuen Server ---
app = boot("Start 2")
try:
    assert not psutil.pid_exists(old_pid) or psutil.Process(old_pid).status() == "zombie", \
        f"verwaister llama-server {old_pid} laeuft noch"
    servers = our_servers()
    assert len(servers) == 1, f"erwartet 1 llama-server, gefunden {[p.pid for p in servers]}"
    res = dictate(wav_de)
    assert res["status"] == "ok" and res["cleanup_ms"] > 0, res
    print("2. Neustart nach SIGKILL: Waise beendet, genau 1 Server, Diktat OK")
finally:
    app.send_signal(signal.SIGKILL)
    app.wait()
    for p in our_servers():
        p.kill()

print("\nMAC E2E PASSED")
