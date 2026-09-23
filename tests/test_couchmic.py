"""Unit-Tests: CouchMic-Erkennung (/api/stats) und Migration der alten glassmic_*-Settings."""

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow import couchmic
from localflow.settings import DEFAULTS, Settings


def serve(body: bytes):
    """Mini-HTTP-Server auf freiem Port, antwortet auf jede GET-Anfrage mit body."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


# --- active(): verbundenes iPad, kein iPad, kaputte Antwort ---
for clients, want in [(1, True), (2, True), (0, False)]:
    srv, url = serve(json.dumps({"clients": clients, "version": "0.1.0"}).encode())
    got = couchmic.active(url)
    srv.shutdown()
    assert got is want, f"clients={clients}: {got}, erwartet {want}"

srv, url = serve(b"kein json")
assert couchmic.active(url) is False
srv.shutdown()

srv, url = serve(b"{}")
assert couchmic.active(url + "/") is False   # fehlendes Feld, Slash am Ende
srv.shutdown()
print("active() OK")

# --- active(): nichts laeuft auf dem Port -> False, schnell ---
s = socket.socket()
s.bind(("127.0.0.1", 0))
free_port = s.getsockname()[1]
s.close()
t0 = time.perf_counter()
assert couchmic.active(f"http://127.0.0.1:{free_port}") is False
dt = time.perf_counter() - t0
assert dt < 1.0, f"Fallback dauerte {dt:.2f}s"
print(f"kein CouchMic OK ({dt * 1000:.0f} ms)")


# --- Settings-Migration glassmic_* -> couchmic_* ---
def load_with(stored: dict):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(stored, f)
    st = Settings(p)
    with open(p, encoding="utf-8") as f:
        on_disk = json.load(f)
    return st, on_disk


st, disk = load_with({"glassmic_enabled": False, "glassmic_url": "http://127.0.0.1:9999",
                      "glassmic_device": "Mein Kabel", "overlay_font_size": 20})
assert st.get("couchmic_enabled") is False
assert st.get("couchmic_url") == "http://127.0.0.1:9999"
assert st.get("couchmic_device") == "Mein Kabel"
assert disk["couchmic_enabled"] is False and disk["couchmic_device"] == "Mein Kabel"
assert not any(k.startswith("glassmic_") for k in disk), disk.keys()
assert disk["overlay_font_size"] == 20
print("Migration alte Schluessel OK")

# Neue Schluessel schon da: die gewinnen, alte werden trotzdem entfernt.
st, disk = load_with({"glassmic_enabled": False, "couchmic_enabled": True})
assert st.get("couchmic_enabled") is True
assert "glassmic_enabled" not in disk
print("Migration neue Schluessel gewinnen OK")

# Frische Config: Defaults, keine alten Schluessel.
st, disk = load_with({})
assert st.get("couchmic_enabled") is DEFAULTS["couchmic_enabled"] is True
assert st.get("couchmic_url") == couchmic.DEFAULT_URL
assert st.get("couchmic_device") == couchmic.DEFAULT_DEVICE
print("Defaults OK")

print("ALLE COUCHMIC-TESTS OK")
