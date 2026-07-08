"""E2E: WAV -> Live-App-Pipeline -> gezieltes Paste in echtes Notepad -> Text
per WM_GETTEXT zurueckgelesen (keine synthetischen Tastendruecke im Test selbst).

Erwartet, dass die App laeuft (run.py) und Modelle geladen sind.
Das Paste-Ziel wird per hwnd an die App uebergeben - genau wie im Live-Betrieb,
wo das Fenster beim Diktieren erfasst wird.
"""

import ctypes
import os
import subprocess
import sys
import time

import requests
import win32con
import win32gui
import win32process

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WAV = os.path.join(os.path.dirname(__file__), "audio", "test_de.wav")
API = "http://127.0.0.1:5111"
EXPECTED_WORDS = ["Punkte", "Verbesserungen", "20"]


def find_notepad_windows():
    found = []
    def cb(h, acc):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "Notepad":
            acc.append(h)
    win32gui.EnumWindows(cb, found)
    return found


def get_edit_text(hwnd) -> str:
    texts = []
    def cb(h, acc):
        cls = win32gui.GetClassName(h)
        if cls in ("RichEditD2DPT", "Edit", "RICHEDIT50W"):
            n = win32gui.SendMessage(h, win32con.WM_GETTEXTLENGTH, 0, 0) + 1
            buf = ctypes.create_unicode_buffer(n)
            ctypes.windll.user32.SendMessageW(h, win32con.WM_GETTEXT, n, buf)
            if buf.value:
                acc.append(buf.value)
    win32gui.EnumChildWindows(hwnd, cb, texts)
    return "\n".join(texts)


# 1. Notepad starten (Fokus muss NICHT beim Test bleiben - die App fokussiert selbst)
before = set(find_notepad_windows())
subprocess.Popen(["notepad.exe"])
hwnd = None
for _ in range(50):
    time.sleep(0.2)
    new = [h for h in find_notepad_windows() if h not in before]
    if new:
        hwnd = new[0]
        break
assert hwnd, "Notepad-Fenster nicht gefunden"
time.sleep(1.0)  # Notepad initialisieren lassen
print("Notepad hwnd:", hwnd)

# 2. Diktat durch die Live-App, Paste-Ziel = unser Notepad
# Debug-Routen brauchen LOCALFLOW_DEBUG=1 beim App-Start + den CSRF-Header.
r = requests.post(f"{API}/api/debug/dictate", json={"wav": WAV, "hwnd": hwnd},
                  headers={"X-LocalFlow": "1"}, timeout=180)
r.raise_for_status()
res = r.json()
print(f"Pipeline: status={res['status']} lang={res['language']} "
      f"stt={res['stt_ms']:.0f}ms cleanup={res['cleanup_ms']:.0f}ms "
      f"total={res['total_ms']:.0f}ms pasted={res['pasted']}")
print("FINAL:", res["final"])
assert res["status"] == "ok", res
assert res["pasted"], "Paste wurde abgebrochen (Zielfenster nicht fokussierbar?)"

# 3. Text direkt aus dem Notepad-Edit-Control lesen
time.sleep(1.0)
notepad_text = get_edit_text(hwnd).strip()
print("NOTEPAD:", notepad_text)

# 4. Aufraeumen: NUR unser Fenster schliessen (WM_CLOSE). Kein taskkill -
# Win11-Notepad teilt sich einen Prozess ueber alle Fenster/Tabs, ein Kill
# wuerde auch offene Fenster/Tabs des Nutzers beenden.
win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

assert notepad_text, "Notepad war leer - Paste kam nicht an"
for w in EXPECTED_WORDS:
    assert w in notepad_text, f"'{w}' fehlt im Notepad-Text"
# Containment statt Gleichheit: das Fenster kann weitere (Nutzer-)Tabs enthalten
assert res["final"].strip() in notepad_text, "Pipeline-Ausgabe nicht im Notepad-Text"

print("\nE2E INJECTION TEST PASSED")
