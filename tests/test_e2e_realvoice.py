"""E2E mit ECHTER Stimme durch die LIVE-App: 5 reale Diktate (de+en) durch
/api/debug/dictate (ohne Paste), Ergebnis gegen Wisprs Referenz geprueft.
"""

import io
import json
import os
import re
import statistics
import sys

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API = "http://127.0.0.1:5111"
DIR = os.path.join(os.path.dirname(__file__), "real_audio")
manifest = json.load(open(os.path.join(DIR, "manifest.json"), encoding="utf-8"))


def norm_words(t):
    return re.sub(r"[^\w\säöüß]", " ", t.lower()).split()


# 5 mittellange Clips (dort ist die Referenz stabil)
clips = [m for m in manifest if 4 <= (m["duration"] or 0) <= 30][:5]
assert len(clips) >= 3, "zu wenige Clips"

totals = []
for m in clips:
    r = requests.post(f"{API}/api/debug/dictate",
                      json={"wav": os.path.join(DIR, m["id"] + ".wav"), "paste": False},
                      headers={"X-LocalFlow": "1"}, timeout=300)
    r.raise_for_status()
    res = r.json()
    ref, hyp = set(norm_words(m["asr"])), set(norm_words(res["final"]))
    overlap = len(ref & hyp) / max(1, len(ref))
    totals.append(res["total_ms"])
    print(f"[{res['language']}|{m['lang']}] {res['total_ms']:.0f}ms "
          f"(stt {res['stt_ms']:.0f} + cleanup {res['cleanup_ms']:.0f}) "
          f"overlap={overlap:.2f} dur={m['duration']}s")
    print("   ", res["final"][:120])
    assert res["status"] == "ok"
    assert res["language"] == m["lang"], f"Sprache {res['language']} != {m['lang']}"
    assert overlap >= 0.75, f"Wort-Ueberlappung nur {overlap:.2f}\nREF: {m['asr']}\nHYP: {res['final']}"

print(f"\nMedian-Latenz auf echter Stimme: {statistics.median(totals):.0f} ms")
print("REAL-VOICE E2E PASSED")
