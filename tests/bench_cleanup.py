"""Benchmark: welches Ollama-Modell repliziert Wisprs AI-Formatting am besten?

Nimmt echte (asrText, formattedText)-Paare aus der Wispr-DB-Kopie und misst
Aehnlichkeit zur Wispr-Ausgabe (difflib) + Latenz pro Modell.
"""

import difflib
import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.cleanup import Cleaner

MODELS = ["gemma3:4b", "gemma4:12b", "qwen2.5:14b"]
DB = os.path.expandvars(r"%TEMP%\wisprdb\flow.sqlite")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
pairs = con.execute("""
    SELECT asrText, formattedText, detectedLanguage FROM History
    WHERE asrText IS NOT NULL AND formattedText IS NOT NULL
      AND numWords BETWEEN 10 AND 50 AND formattedText NOT LIKE '%<%'
      AND detectedLanguage IN ('de','en')
    ORDER BY timestamp DESC LIMIT 10
""").fetchall()
print(f"{len(pairs)} Testpaare geladen "
      f"({sum(1 for p in pairs if p['detectedLanguage']=='de')} de, "
      f"{sum(1 for p in pairs if p['detectedLanguage']=='en')} en)\n")

results = {}
for model in MODELS:
    cleaner = Cleaner(model=model, timeout=60)
    cleaner.warmup()
    sims, lats = [], []
    for p in pairs:
        t0 = time.perf_counter()
        out = cleaner.clean(p["asrText"], p["detectedLanguage"])
        lat = (time.perf_counter() - t0) * 1000
        sim = difflib.SequenceMatcher(None, out, p["formattedText"]).ratio()
        sims.append(sim)
        lats.append(lat)
    results[model] = (statistics.mean(sims), statistics.median(lats), max(lats))
    print(f"{model:14} similarity={statistics.mean(sims):.3f}  "
          f"median={statistics.median(lats):.0f}ms  max={max(lats):.0f}ms")

best = max(results, key=lambda m: results[m][0] - results[m][1] / 20000)
print(f"\nBEST: {best}")

# Beispielausgaben des besten Modells zeigen
print("\n--- Beispiele (bestes Modell) ---")
cleaner = Cleaner(model=best, timeout=60)
for p in pairs[:3]:
    out = cleaner.clean(p["asrText"], p["detectedLanguage"])
    print("\nASR  :", p["asrText"][:250])
    print("WISPR:", p["formattedText"][:250])
    print("LOCAL:", out[:250])
