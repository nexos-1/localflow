"""Pipeline-Test ohne Mikrofon: TTS-WAVs durch STT + Cleanup + Dictionary."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from localflow.db import Database
from localflow.pipeline import Pipeline
from localflow.settings import Settings

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")

tmp = tempfile.mkdtemp()
settings = Settings(path=os.path.join(tmp, "config.json"))
db = Database(path=os.path.join(tmp, "test.sqlite"))

# Dictionary-Testdaten: Snippet + Replacement
db.add_dictionary("meine E-Mail-Adresse", "test@example.com", is_snippet=True)
db.add_dictionary("btw", "by the way")
db.add_dictionary("Ada Lovelace")  # Bias-Wort

pipe = Pipeline(settings, db)
print("Lade Modelle...")
pipe.load()
print(f"Whisper: {pipe.transcriber.device}/{pipe.transcriber.compute_type}")

for name in ["test_de.wav", "test_en.wav"]:
    r = pipe.process(os.path.join(AUDIO_DIR, name))
    print(f"\n{name} [{r.language}] status={r.status} "
          f"stt={r.stt_ms:.0f}ms cleanup={r.cleanup_ms:.0f}ms total={r.total_ms:.0f}ms")
    print("  ASR  :", r.asr_text)
    print("  FINAL:", r.final_text)
    assert r.status == "ok"
    assert len(r.final_text) > 20
    pipe.record_history(r, app="test", duration_s=10)

# Dictionary-Anwendung direkt testen
from localflow.pipeline import PipelineResult
res = PipelineResult()
entries = db.get_dictionary()
out = pipe._apply_dictionary("Schick das an meine E-Mail-Adresse, btw danke!", entries, res)
print("\nDictionary-Test:", out)
assert "test@example.com" in out, out
assert "by the way" in out, out

hist = db.get_history()
assert len(hist) == 2
stats = db.get_stats()
print(f"History: {len(hist)} Eintraege, Stats: {stats['total_words']} Woerter, "
      f"avg {stats['avg_latency_ms']:.0f}ms")

print("\nPIPELINE TEST PASSED")
