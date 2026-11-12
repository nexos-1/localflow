"""Unit-Tests fuer lange Diktate (Feldbefund 2026-11-12: nach 300 s abgeschnitten,
624 Woerter, Cleanup-Timeout, Rohtext):
- das Limit ist jetzt eine Stunde; eine Config mit dem alten Standard wird gehoben,
  eine bewusst andere Wahl bleibt;
- bis 600 Woerter in einem Stueck mit laengerem Timeout, darueber abschnittsweise,
  ohne ein Wort zu verlieren;
- eine Bereinigung, die einen ganzen Satz verschluckt, faellt auf den Rohtext zurueck;
- lange Aufnahmen werden als WAV gesichert, nur die neuesten bleiben liegen.
Ohne Modelle, Mikrofon oder GPU."""

import json
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from localflow.cleanup import (CHUNK_WORDS, _plausible, clean_long, dropped_content,  # noqa: E402
                               split_for_cleanup, timeout_for)
from localflow.recordings import save_recording  # noqa: E402
from localflow.settings import DEFAULTS, Settings  # noqa: E402

failures = 0


def check(name, ok, detail=""):
    global failures
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures += 1


# --- Limit und Migration -------------------------------------------------------
check("Standard-Limit ist eine Stunde", DEFAULTS["max_duration_s"] == 3600, DEFAULTS["max_duration_s"])
for stored, want in [(300, 3600), (600, 600), (0, 0), (7200, 7200)]:
    d = tempfile.mkdtemp()
    path = os.path.join(d, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"max_duration_s": stored, "hotkey": "maus5"}, f)
    s = Settings(path=path)
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f).get("max_duration_s")
    check(f"gespeichert {stored} -> {want}", s.get("max_duration_s") == want and on_disk == want,
          f"geladen {s.get('max_duration_s')}, Datei {on_disk}")
    check(f"andere Werte bleiben ({stored})", s.get("hotkey") == "maus5")

# --- Abschnitte ----------------------------------------------------------------
# Wie das echte Diktat: lange Strecken ohne Punkt, einzelne Saetze, Kommas.
sentence = "Das ist ein Satz mit genau zehn Woertern fuer den Test."
runon = " ".join(f"wort{i}" + ("," if i % 37 == 36 else "") for i in range(450))
text = " ".join([sentence] * 30) + " " + runon + " " + " ".join([sentence] * 5)
SMALL = 200   # kleinere Abschnitte, damit der Test wenig Text braucht
parts = split_for_cleanup(text, SMALL)
words = text.split()
check("kein Wort geht verloren, Reihenfolge bleibt", " ".join(parts).split() == words)
check("jeder Abschnitt hoechstens max_words Woerter",
      all(len(p.split()) <= SMALL for p in parts), [len(p.split()) for p in parts])
check("mehrere Abschnitte", len(parts) >= 4, len(parts))
check("Satzteil endet an einem Satzende", parts[0].endswith("."), parts[0][-30:])
runon_parts = [p for p in parts if "wort" in p and not p.endswith(".")]
check("Satz ohne Punkt wird an einem Komma geteilt",
      bool(runon_parts) and all(p.endswith(",") for p in runon_parts[:-1]),
      [p[-12:] for p in runon_parts])
check("kurzer Text bleibt ein Stueck", split_for_cleanup("Hallo Welt.") == ["Hallo Welt."])
check("leerer Text", split_for_cleanup("   ") == [])
hard = " ".join(f"w{i}" for i in range(450))           # weder Punkt noch Komma
check("ohne Punkt und Komma hart geteilt",
      [len(p.split()) for p in split_for_cleanup(hard, SMALL)] == [200, 200, 50])
check("das echte Diktat (624 Woerter) geht in einem Stueck durch",
      CHUNK_WORDS >= 624 and len(split_for_cleanup(" ".join(["wort"] * 624))) == 1, CHUNK_WORDS)


class FakeCleaner:
    def __init__(self, fail_on=None, timeout=None):
        self.calls = []
        self.timeouts = []
        self.fail_on = fail_on
        if timeout is not None:
            self.timeout = timeout

    def clean(self, text, language=None, timeout=None):
        self.calls.append(text)
        self.timeouts.append(timeout)
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            return text                                    # Rohtext-Rueckfall
        return text.upper()


fake = FakeCleaner()
out = clean_long(fake, text, "de", max_words=SMALL)
check("ein Aufruf pro Abschnitt", len(fake.calls) == len(parts), len(fake.calls))
check("Ergebnis ist die Folge der bereinigten Abschnitte", out == " ".join(p.upper() for p in parts))
fake = FakeCleaner(fail_on=2)
out = clean_long(fake, text, "de", max_words=SMALL)
check("ein gescheiterter Abschnitt bleibt roh, die anderen bereinigt",
      out.split(" ")[: len(parts[0].split())] == parts[0].upper().split(" ")
      and parts[1] in out)
fake = FakeCleaner()
check("kurzer Text geht unveraendert an clean()", clean_long(fake, "kurz und gut", "de") == "KURZ UND GUT"
      and fake.calls == ["kurz und gut"])

# --- Timeout waechst mit der Laenge ---------------------------------------------
check("Timeout bis 150 Woerter wie eingestellt", timeout_for(40, 8.0) == 8.0 and timeout_for(150, 8.0) == 8.0)
check("624 Woerter bekommen gut 33 s", abs(timeout_for(624, 8.0) - 33.28) < 0.01, timeout_for(624, 8.0))
fake = FakeCleaner(timeout=8.0)
clean_long(fake, " ".join(["wort"] * 300), "de")
check("clean_long reicht den laengeren Timeout weiter", fake.timeouts == [16.0], fake.timeouts)
fake = FakeCleaner()
clean_long(fake, "kurz und gut", "de")
check("Cleaner ohne Timeout-Attribut bekommt keinen", fake.timeouts == [None], fake.timeouts)

# --- Verschluckter Satz --------------------------------------------------------
raw = (
    "Also ich gebe dir jetzt mal Feedback auf die Seite und gehe von oben nach unten durch. "
    "Ich finde die Google Rezensionen sehr gut, aber da fehlen irgendwie Sterne. "
    "Dann gefaellt mir sehr gut bei Palmenboot, bei den Weltcategories, dass Palmenboot per Scroll "
    "Liquid sich veraendert. Das passiert nur bei Palmenboot, bei den weiteren Headlines nicht.")
ok_out = raw.replace("Also ich gebe", "Ich gebe").replace("irgendwie ", "")
dropped = raw.replace("Dann gefaellt mir sehr gut bei Palmenboot, bei den Weltcategories, dass Palmenboot "
                      "per Scroll Liquid sich veraendert. ", "")
check("normales Bereinigen verliert keinen Satz", dropped_content(raw, ok_out) < 8 and _plausible(raw, ok_out),
      dropped_content(raw, ok_out))
check("ein verschluckter Satz wird erkannt", dropped_content(raw, dropped) >= 8 and not _plausible(raw, dropped),
      dropped_content(raw, dropped))
check("Umformulieren zaehlt nicht als Verlust",
      dropped_content(raw, raw.replace("sich veraendert", "sich wandelt").replace("weiteren", "anderen")) < 8)
check("kurze Texte werden nicht geprueft", dropped_content("Hallo du da", "") == 0)

# --- Sicherung ----------------------------------------------------------------
folder = os.path.join(tempfile.mkdtemp(), "recordings")
tone = (0.5 * np.sin(np.linspace(0, 2 * np.pi * 440, 16000 * 3))).astype(np.float32)
path = save_recording(tone, folder, keep=2, now=1_700_000_000)
with wave.open(path, "rb") as w:
    ok = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 48000)
check("WAV 16 kHz mono 16 bit mit allen Samples", ok)
second = save_recording(tone, folder, keep=2, now=1_700_000_000)
check("gleiche Sekunde ueberschreibt nicht", second != path and os.path.exists(path) and os.path.exists(second))
os.utime(path, (1, 1))
os.utime(second, (2, 2))
save_recording(tone, folder, keep=2, now=1_700_000_100)
left = sorted(os.listdir(folder))
check("nur die neuesten zwei bleiben", len(left) == 2 and os.path.basename(path) not in left, left)
check("keine .part-Datei bleibt liegen", not any(f.endswith(".part") for f in left))
# Ein Ordnerpfad unter einer (noch vorhandenen) Datei laesst sich nicht anlegen.
blocker = os.path.join(folder, left[0])
check("ein Fehler wird gemeldet, nicht geworfen",
      save_recording(tone, os.path.join(blocker, "kein-ordner")) is None)

print(f"\n{failures} Fehler")
sys.exit(1 if failures else 0)
