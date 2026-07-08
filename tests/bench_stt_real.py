"""STT-Benchmark auf ECHTEN Diktaten (eigene Stimme, Focusrite-Mikro).

Vergleicht beam_size-Varianten gegen Wisprs Cloud-ASR-Referenz:
WER (wortbasiert, normalisiert) + Latenz. Ausserdem Sprachdetektion.
"""

import difflib
import io
import json
import os
import re
import statistics
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.stt import Transcriber

DIR = os.path.join(os.path.dirname(__file__), "real_audio")
manifest = json.load(open(os.path.join(DIR, "manifest.json"), encoding="utf-8"))


def norm(t: str) -> list[str]:
    t = t.lower()
    t = re.sub(r"[^\w\säöüß]", " ", t)
    return t.split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    sm = difflib.SequenceMatcher(None, r, h)
    errors = sum(max(a2 - a1, b2 - b1)
                 for op, a1, a2, b1, b2 in sm.get_opcodes() if op != "equal")
    return errors / len(r)


tr = Transcriber()
print(f"Whisper geladen: {tr.device}/{tr.compute_type}\n")

for beam in (1, 5):
    wers, lats, lang_ok = [], [], 0
    for m in manifest:
        path = os.path.join(DIR, m["id"] + ".wav")
        t0 = time.perf_counter()
        segments, info = tr.model.transcribe(path, beam_size=beam, vad_filter=True,
                                             vad_parameters={"min_silence_duration_ms": 500})
        text = " ".join(s.text.strip() for s in segments).strip()
        lat = (time.perf_counter() - t0) * 1000
        w = wer(m["asr"], text)
        wers.append(w)
        lats.append(lat)
        lang_ok += info.language == m["lang"]
        if beam == 5 and w > 0.15:
            print(f"  [worst @beam5] wer={w:.2f} lang={info.language}/{m['lang']} dur={m['duration']}s")
            print(f"    WISPR: {m['asr'][:150]}")
            print(f"    LOCAL: {text[:150]}")
    print(f"beam={beam}: WER mean={statistics.mean(wers)*100:.1f}% median={statistics.median(wers)*100:.1f}% "
          f"| Latenz median={statistics.median(lats):.0f}ms p95={sorted(lats)[-2]:.0f}ms "
          f"| Sprache korrekt {lang_ok}/{len(manifest)}\n")
