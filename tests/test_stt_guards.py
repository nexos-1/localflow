"""Tests fuer die STT-Qualitaets-Guards: Sprachrestriktion + Halluzinationsfilter."""

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from localflow.stt import Transcriber

DIR = os.path.join(os.path.dirname(__file__), "real_audio")
manifest = json.load(open(os.path.join(DIR, "manifest.json"), encoding="utf-8"))

tr = Transcriber()
print(f"Whisper: {tr.device}/{tr.compute_type}\n")

# 1. Der 0.6s-Clip, der ohne Restriktion als Russisch halluziniert wurde
short = min(manifest, key=lambda m: m["duration"])
path = os.path.join(DIR, short["id"] + ".wav")
text, lang, _ = tr.transcribe(path, allowed_languages=["de", "en"], beam_size=1)
print(f"Kurz-Clip ({short['duration']}s): lang={lang} text={text!r} (Referenz: {short['asr']!r})")
assert lang in ("de", "en"), f"Sprache {lang} trotz Restriktion"

# 2. Stille -> muss leer sein
silence = np.zeros(16000 * 2, dtype=np.float32)
text, lang, _ = tr.transcribe(silence, allowed_languages=["de", "en"], beam_size=1)
print(f"Stille: text={text!r}")
assert text == "", f"Stille ergab Text: {text!r}"

# 3. Leises Rauschen -> muss leer sein oder zumindest keine bekannte Halluzination
rng = np.random.default_rng(42)
noise = (rng.standard_normal(16000 * 3) * 0.008).astype(np.float32)
text, lang, _ = tr.transcribe(noise, allowed_languages=["de", "en"], beam_size=1)
print(f"Rauschen: text={text!r}")
assert text.strip().lower().rstrip(".!?") not in ("vielen dank", "untertitelung des zdf", "thank you"), text

# 4. Normale Clips duerfen NICHT leer werden (Guard-Kollateralschaden pruefen)
ok, empty = 0, 0
for m in manifest:
    t, lg, _ = tr.transcribe(os.path.join(DIR, m["id"] + ".wav"),
                             allowed_languages=["de", "en"], beam_size=1)
    if t.strip():
        ok += 1
    else:
        empty += 1
        print(f"  LEER: {m['id']} dur={m['duration']}s ref={m['asr'][:60]!r}")
print(f"\nEchte Clips mit Text: {ok}/{len(manifest)}")
assert empty == 0, f"{empty} echte Diktate wurden faelschlich verworfen"

print("\nSTT GUARD TESTS PASSED")
