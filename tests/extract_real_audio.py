"""Extrahiert echte Diktat-WAVs aus der Wispr-DB-Kopie fuer Benchmarks.

Legt tests/real_audio/<id>.wav + manifest.json (Referenztexte) an.
Die WAVs bleiben lokal auf dieser Maschine (eigene Stimme des Nutzers).
"""

import json
import os
import sqlite3
import sys

OUT = os.path.join(os.path.dirname(__file__), "real_audio")
os.makedirs(OUT, exist_ok=True)

con = sqlite3.connect(os.path.expandvars(r"%TEMP%\wisprdb\flow.sqlite"))
con.row_factory = sqlite3.Row

# Diverse Auswahl: kurz/mittel/lang, de + en
rows = con.execute("""
    SELECT transcriptEntityId id, audio, asrText, formattedText, detectedLanguage lang,
           duration
    FROM History
    WHERE audio IS NOT NULL AND asrText IS NOT NULL AND LENGTH(asrText) > 5
    ORDER BY timestamp DESC
""").fetchall()

de = [r for r in rows if r["lang"] == "de"]
en = [r for r in rows if r["lang"] == "en"]
print(f"verfuegbar: {len(de)} de, {len(en)} en")

def pick_diverse(items, n):
    if len(items) <= n:
        return list(items)
    by_dur = sorted(items, key=lambda r: r["duration"] or 0)
    step = len(by_dur) / n
    return [by_dur[int(i * step)] for i in range(n)]

selected = pick_diverse(de, 12) + pick_diverse(en, 8)
manifest = []
for r in selected:
    path = os.path.join(OUT, f"{r['id']}.wav")
    with open(path, "wb") as f:
        f.write(r["audio"])
    manifest.append({"id": r["id"], "lang": r["lang"], "duration": r["duration"],
                     "asr": r["asrText"], "formatted": r["formattedText"]})

with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
print(f"{len(manifest)} WAVs extrahiert nach {OUT}")
