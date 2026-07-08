# LocalFlow

Vollstaendig lokaler Wispr-Flow-Ersatz fuer Windows. Hotkey halten, sprechen,
loslassen - der formatierte Text landet in der aktiven App. Kein Cloud-Dienst,
kein Abo: Whisper (STT) und Ollama (AI-Cleanup) laufen auf der eigenen Maschine.

> **Windows ist erstklassig unterstuetzt, macOS experimentell**: Ein
> Darwin-Backend existiert (Paste, Hotkeys, Sprachbefehle, Sounds,
> Metal-STT-Engine, AppKit-Overlay-Pill) und laeuft in der CI auf echten
> macOS-Runnern - interaktiv auf einem Mac wurde die App aber noch nie
> benutzt. Status und Plan in [PORTING.md](PORTING.md).

## Bedienung

| Aktion | Standard |
|---|---|
| Diktieren (halten) | `Ctrl + Win` halten, loslassen = fertig |
| Freisprechen | Hotkey doppelt tippen, erneut druecken = Stop |
| Zusaetzlicher Toggle-Hotkey | `Ctrl + Alt + Space` |
| Taste per Sprache druecken | am Diktat-Ende "... press enter" sagen |
| Live-Transkript ausklappen | waehrend der Aufnahme mit der Maus ueber die Pill fahren |
| Dashboard | Tray-Icon anklicken oder http://127.0.0.1:5111 |

Modus (nur Halten / Halten+Doppeltipp / Toggle) und Hotkeys sind in den
Einstellungen aenderbar - inkl. "⌨ Aufnehmen"-Button, der die naechste
gedrueckte Kombination uebernimmt. Auch die Maus-Seitentasten funktionieren
als Diktier-Taste ("maus4"/"maus5", einzeln oder kombiniert wie
"ctrl+maus5"), und ein **optionaler zweiter Diktat-Hotkey** laeuft parallel
(z.B. Maus5 UND Ctrl+Win). Standardmaessig behaelt die Maustaste dabei ihre
normale Funktion (Browser-Vor/Zurueck laeuft parallel weiter); wer sie
exklusiv fuers Diktieren will - z.B. damit ein Diktat markierten Text
ersetzt, statt den Cursor zu versetzen - aktiviert "Maus-Hotkey verschluckt
den Klick" in den Einstellungen. Sprache wird automatisch erkannt
(Deutsch/Englisch gemischt kein Problem).

**Sprachbefehle:** Ein Diktat, das auf "press enter", "press backspace",
"press escape" oder "press delete" endet, tippt die Phrase nicht, sondern
drueckt die Taste (nach dem Einfuegen des restlichen Texts). Die
Ausloese-Woerter sind im Dashboard frei editierbar.

**Smart Spacing:** Steht der Cursor beim Einfuegen direkt an bestehendem
Text (Satzende, Wortmitte), wird automatisch ein Leerzeichen vorangestellt.
Markierungen bleiben unangetastet (Ersetzen-Workflow), Terminals sind
ausgenommen. Abschaltbar in den Einstellungen.

**Live-Vorschau:** Waehrend des Sprechens erscheint das Transkript live in
der Overlay-Pill (die Pill waechst mit); Hover klappt den gesamten Text
mehrzeilig aus. Eingefuegt wird erst beim Loslassen - der finale, vom
AI-Cleanup bereinigte Text. Abschaltbar in den Einstellungen.

Die Flow-Bar (kleine schwarze Pill unten in der Bildschirmmitte, monochrom)
zeigt: pulsierender Punkt + live Waveform bzw. Live-Transkript = Aufnahme
(Pegel adaptiv - die Balken skalieren sich automatisch auf die tatsaechliche
Mikrofonlautstaerke), Ring statt Punkt = Freisprechen, drei wandernde
Punkte = Verarbeitung. Alle Uebergaenge sind animiert. Optik (Design-Thema
Dunkel/Hell, Schriftart, Schriftgroesse, Glas-Look) ist im Dashboard unter
"Widget-Design" live einstellbar. Eigene Sounds: WAVs nach `data/sounds/`
legen (start/stop/lock/error.wav) und die Namen in `custom.txt` eintragen -
sie werden nie von der Generierung ueberschrieben.

Waehrend der Aufnahme wird System-Audio anderer Apps (YouTube, Spotify ...)
in ~100 ms KOMPLETT stummgeschaltet (0%) und danach exakt restauriert.
Der Aufnahme-Anfang, in dem das Audio noch hoerbar war, wird automatisch
weggeschnitten - fremde Sprache (YouTube) landet nicht im Diktat.
Robustheit: dedizierter Worker-Thread (keine Volume-Races bei schnellen
Diktat-Folgen), Waechter mutet mittendrin startende Sessions, Crash-Recovery
stellt Pegel beim naechsten Start wieder her (ducked_volumes.json).
Abschaltbar in den Einstellungen, Restpegel ueber `duck_volume`.
Start/Stop/Freisprechen haben weiche Marimba-Chimes (abschaltbar).

## Installation

**Windows, am einfachsten**: Repo als ZIP laden, entpacken,
**`install.bat` doppelklicken** - installiert bei Bedarf Python (winget),
richtet alles ein und startet die App. Kein Terminal noetig.
Alternativ im Terminal: `powershell -ExecutionPolicy Bypass -File install.ps1`.

**macOS (experimentell)**: `bash install.sh`, dann
`.venv/bin/python run.py`. Beim ersten Start Mikrofon- und
Bedienungshilfen-Permission erteilen. Interaktiv ungetestet, kein
Audio-Ducking. Overlay-Pill und Metal-STT-Engine (mlx-whisper) sind
enthalten und werden in der CI auf echten Apple-Silicon-Runnern
funktional getestet; Intel-Macs fallen auf CPU-Whisper zurueck, das zum
Diktieren zu langsam ist (gemessen ~20 s fuer 16 s Audio). Siehe PORTING.md.
Test auf echter Hardware: Anleitung in
[docs/TESTING-MACOS.md](docs/TESTING-MACOS.md).

## Deinstallation

**Windows**: **`uninstall.bat` doppelklicken** - beendet die App, entfernt
Autostart-Eintrag und Startmenue-Verknuepfung und bietet an: Whisper-
Modell-Cache (~1,6 GB), Ollama-Cleanup-Modell und zum Schluss den ganzen
Ordner loeschen. Die Diktat-History (`data/localflow.sqlite`) wird nur
nach ausdruecklicher Bestaetigung geloescht.

**macOS**: `bash uninstall.sh` (gleicher Ablauf; entfernt auch den
LaunchAgent).

## Start (Windows)

```powershell
# sichtbar (mit Konsole/Logs):
.venv\Scripts\python.exe run.py
# unsichtbar (Hintergrund, wie eine richtige App):
.venv\Scripts\pythonw.exe run.py
```

Beim allerersten Start laedt Whisper `large-v3-turbo` (~1,6 GB) herunter;
danach kommt das Modell in wenigen Sekunden aus dem Cache. Ollama wird beim
Start automatisch mitgestartet, falls es nicht laeuft (ohne Doppelstart,
wenn es schon laeuft).

Das Mikrofon wird NUR waehrend einer Aufnahme geoeffnet (Windows-Anzeige
"Mikrofon wird verwendet" leuchtet nur beim Diktieren; Stream-Open kostet
~20 ms beim Tastendruck).

## Wispr Flow abloesen

1. LocalFlow testen (paar Diktate in echten Apps).
2. Autostart aktivieren (Settings-Checkbox "Mit Windows starten" oder Tray-Menue).
3. Wispr Flow beenden und dessen Autostart deaktivieren
   (Task-Manager -> Autostart -> Wispr Flow -> Deaktivieren),
   oder deinstallieren. Beide gleichzeitig geht nicht gut - beide lauschen
   auf `Ctrl + Win`.
4. Optional Wispr-Daten uebernehmen: Dashboard -> Einstellungen ->
   "Wispr Flow Import" liest Woerterbuch und History aus der lokalen
   `flow.sqlite` der installierten Wispr-App (importer.py).

## Architektur

```
localflow/
  main.py        Tray-App, Orchestrierung, Autostart (HKCU Run-Key), Live-Preview-Loop
  controller.py  plattformneutrale Diktat-Zustandsmaschine (Halten/Doppeltipp/Toggle)
  hotkey.py      Win32-Low-Level-Hooks (Tastatur/Maus), fuettern den Controller
  audio.py       Mikrofon 16 kHz mono (sounddevice), adaptiver Pegelmesser
  stt.py         faster-whisper large-v3-turbo, CUDA float16, Fallback CPU;
                 stt_mlx.py: mlx-whisper (Metal, Apple Silicon),
                 stt_factory.py waehlt die Engine, stt_quality.py teilt
                 die Qualitaets-Guards
  cleanup.py     Ollama gemma3:4b, Prompt kalibriert auf Light-Formatting
  commands.py    Sprachbefehle am Diktat-Ende ("press enter" -> Taste)
  pipeline.py    STT -> Sprachbefehle -> Cleanup -> Woerterbuch/Snippets -> History
  inject.py      Clipboard setzen -> Ctrl+V -> Clipboard restaurieren,
                 Paste nur ins beim Diktat fokussierte Fenster (target_hwnd),
                 Tasten-Sender fuer Sprachbefehle
  db.py          SQLite: history + dictionary
  settings.py    JSON-Config
  overlay.py     Animierte Overlay-Pill (Tk): Waveform, Live-Transkript,
                 Hover-Ausklappen, Glas-Optik; overlay_model.py teilt die
                 Choreografie mit der macOS-Pill (AppKit)
  sounds.py      Start/Stop-Chimes (generiert)
  importer.py    Import aus Wisprs flow.sqlite (Dashboard-Button)
  web/           Flask-Dashboard (History, Woerterbuch, Settings, Import)
  platform/      Backend-Vertraege + win32- und darwin-Implementierung
```

Daten: `<projekt>\data\` (config.json, localflow.sqlite, logs\, sounds\) -
bewusst NEBEN dem Code, damit der Ort unabhaengig vom Start-Weg ist;
ueberschreibbar per Umgebungsvariable `LOCALFLOW_DATA_DIR`. Der Ordner ist
git-ignoriert. Logs enthalten keinen Diktat-Klartext.

Mehr Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Gemessene Latenz und Qualitaet (RTX 5080, echte Stimme)

Benchmark auf 20 echten Diktaten (eigene Stimme, Focusrite):

- End-to-End (STT + Cleanup) median **~800 ms**; Wispr-Cloud-Referenz: Ø 930 ms.
- Whisper beam_size=1 schlaegt beam_size=5 auf dieser Stimme (WER 3,0% vs
  6,1% median) und ist schneller - deshalb Default 1.
- AI-Cleanup (gemma3:4b): 0,95 Aehnlichkeit zur Wispr-Formatierung, ~465 ms.
- Live-Vorschau: inkrementelle Re-Transkription alle ~0,4 s waehrend der Aufnahme.

## Robustheit (eingebaut und getestet)

- Sprachdetektion auf de/en beschraenkt (0,6s-Clips wurden sonst z.B. als
  Russisch halluziniert); Halluzinations-Filter fuer Stille/Rauschen
  (no_speech_prob + Logprob + Phrasen-Blacklist).
- Paste ist an das Fenster gebunden, in dem diktiert wurde; ist es nicht
  fokussierbar, bleibt der Text im Clipboard + Tray-Notification.
- Clipboard-Erhaltung fuer Text, Bilder (CF_DIB) und Datei-Kopien (CF_HDROP).
- Clipboard-Hygiene: transiente Eintraege (Diktat, Smart-Spacing-Sonde,
  Restore) sind vom Zwischenablage-Verlauf (Win+V) und Cloud-Sync
  ausgenommen; ein vorher leeres Clipboard ist nach dem Paste wieder leer.
- Nachlauf 150 ms (`tail_ms`): die letzte Silbe wird nicht abgeschnitten.
- Ollama-Healthcheck mit Autostart (`ollama serve`) und
  Doppelstart-Schutz; Cleanup-Ausfall degradiert zu Rohtext statt zu blockieren.
- Single-Instance-Mutex (ein zweiter Start oeffnet einfach das Dashboard).
- Watchdog stoppt vergessenes Freisprechen nach `max_duration_s` (Default 300 s).
- Dashboard zeigt einen klaren Banner, wenn die App nicht laeuft, und
  verbindet sich automatisch neu.

## Tests

```powershell
.venv\Scripts\python.exe tests\test_stt.py             # Whisper/CUDA Smoke-Test
.venv\Scripts\python.exe tests\test_stt_guards.py      # Sprachrestriktion + Halluzinationsfilter
.venv\Scripts\python.exe tests\test_pipeline.py        # Pipeline offline (TTS-WAVs)
.venv\Scripts\python.exe tests\test_dictation_modes.py # Diktat-Zustandsmaschine
.venv\Scripts\python.exe tests\test_second_hotkey.py   # Zweiter Hotkey
.venv\Scripts\python.exe tests\test_commands.py        # Sprachbefehl-Erkennung
.venv\Scripts\python.exe tests\test_cleanup_start.py   # Ollama-Doppelstart-Schutz
.venv\Scripts\python.exe tests\test_levelmeter.py      # adaptiver Pegelmesser
.venv\Scripts\python.exe tests\test_smart_spacing.py   # Smart-Spacing-Entscheidungslogik
.venv\Scripts\python.exe tests\test_darwin_port.py     # macOS-Backend (portable Pruefungen)
.venv\Scripts\python.exe tests\test_clipboard.py       # Clipboard-Erhaltung (Text + Dateien)
.venv\Scripts\python.exe tests\test_e2e_inject.py      # E2E in echtes Notepad (App muss laufen)
.venv\Scripts\python.exe tests\test_e2e_realvoice.py   # E2E mit echter Stimme (App muss laufen)
```

Die hardwarefreien Suiten laufen zusaetzlich in der CI auf Windows und
echten macOS-Runnern ([.github/workflows/ci.yml](.github/workflows/ci.yml)).
Die `test_e2e_*`-Tests tippen und pasten in echte Fenster - vor dem
Ausfuehren lesen. `tests\extract_real_audio.py` baut einen persoenlichen
STT-Benchmark aus einer lokalen Wispr-DB; die extrahierten WAVs bleiben auf
der Maschine und sind git-ignoriert.

## Bekannte Grenzen

- Sehr kurze Diktate (unter ~1 s) sind fuer Whisper inhaerent schwer;
  Sprache stimmt jetzt immer, aber einzelne Woerter koennen abweichen.
- AI-Cleanup-Prompt ist auf Deutsch/Englisch kalibriert; weitere Sprachen
  transkribieren, werden aber ggf. schwaecher bereinigt.
- Kein Meeting-Notetaker, kein Polish-selektierter-Text (bewusst, siehe
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Lizenz

[MIT](LICENSE). Abhaengigkeiten stehen unter ihren eigenen Lizenzen
(Hinweis: `pystray` ist LGPL-3.0, wird als normale pip-Dependency genutzt).
