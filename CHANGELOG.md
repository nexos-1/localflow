# Changelog

## Unreleased

### Changed
- **Glass Mic heisst jetzt CouchMic** (https://github.com/nexos-1/couchmic).
  Modul `localflow/couchmic.py`, Settings `couchmic_enabled`, `couchmic_url`
  und `couchmic_device`, Texte in Dashboard und Log. Die Erkennung bleibt
  gleich (Port 8321, `/api/stats`). Gespeicherte `glassmic_*`-Werte werden
  beim ersten Start automatisch uebernommen und die alten Schluessel aus der
  `config.json` entfernt.

### Fixed
- **macOS: Absturz beim Start (SIGABRT in HIToolbox, "Abort trap: 6")**
  direkt nach "Diktat-Hotkey aktiv (darwin)", reproduzierbar aus Terminal,
  LaunchAgent und App-Bundle. Ursache: pynputs Tastatur-Listener liest in
  seinem eigenen Thread das Tastatur-Layout ueber TIS/TSM, was neuere
  macOS-Versionen nur noch auf dem Main-Thread erlauben. LocalFlow liest
  das Layout jetzt einmal auf dem Main-Thread (beim Backend-Aufbau und bei
  jedem Hotkey-Setup im Main-Thread neu) und gibt pynputs Listenern nur
  noch den Cache; Fremd-Threads (Dashboard-Hotkey-Wechsel, Hotkey-Capture)
  fassen TIS nie mehr an. Gehaertet in Schichten: eigene Listener-Klassen
  ueberspringen pynputs TIS-Pfad ganz und lauschen ohne NSSystemDefined
  (kein NSEvent im Listener-Thread), ein Guard-Patch faengt jeden anderen
  pynput-Pfad ab, und eine Selbstpruefung der pynput-Interna deaktiviert im
  Zweifel nur den Tastatur-Hotkey, statt den Prozess abbrechen zu lassen.
  Neuer CI-Schritt startet das Hotkey-Backend real auf dem macOS-26-Runner,
  mit ungepatchtem pynput als Negativkontrolle.
- **macOS: Tray-Icon-Wechsel nur noch auf dem Main-Thread.** Seit 0.4.0
  wechselt das Icon bei Aufnahme und Pause; pystray setzt das Bild per
  AppKit im Aufrufer-Thread, der Wechsel kam aber aus Hotkey- und
  Worker-Threads. Laeuft jetzt ueber `integration.run_on_main`.

### Added
- **Position der Pille einstellbar**: unten oder oben, jeweils links, Mitte
  oder rechts, plus "Abstand zum Rand" in Pixeln (Standard 44). Beides im
  Dashboard unter "Pille (Overlay)", wirkt sofort, auch waehrend die Pille
  sichtbar ist. Oben verankert kommt die Pille von oben herein und die
  Bubble waechst nach unten. Windows und macOS.

### Changed
- **Glas-Optik eindeutig**: "aus" ist jetzt deckend (100 % oben, 97 % unten,
  vorher 94/90), "an" deutlich glasiger (68/52 statt 72/60). Der Schalter
  wechselt nur die Deckkraft der Pillenflaeche; ein Weichzeichnen des
  Hintergrunds gibt es fuer Layered Windows auf Windows nicht.

## 0.4.1 - 2026-09-15

### Added
- **Motion-Brief, letzte Punkte**: Die Pille materialisiert beim Einblenden
  (waechst von 86 % um ihre Unterkante, jetzt auch auf Windows), lehnt sich
  im Tipp-Fenster minimal zurueck, und die Bubble mit dem Live-Text klappt
  auch auf, wenn der Hotkey laenger als 1,5 s gehalten wird (nicht nur per
  Maus). Die Fehler-Pille nennt den Grund ("Fehler · Kein Mikrofon",
  "Modelle nicht geladen", "Ollama nicht erreichbar"). Im Dashboard gelten
  Schalter und Auswahlen sofort beim Umschalten; nur Hotkeys, Sprachbefehle
  und die Tipp-Laenge brauchen noch "Speichern". Die macOS-Pille zieht nach:
  Ring aus kreisenden Punkten statt Punkt und Waveform, Ring gleitet mit dem
  Text nach links.


## 0.4.0 - 2026-09-15

### Added
- **Pille als Layered Window mit Per-Pixel-Alpha** (Windows): overlay.py
  zeichnet nicht mehr mit Tk, sondern rendert jeden Frame mit PIL in 3-fachem
  Supersampling (geglaettete Stadion-Kanten, echte Transparenz, weicher
  Schatten, Lichtkante, FreeType-Text mit Segoe UI Semibold) und zeigt ihn per
  UpdateLayeredWindow. Neue Groesse und Optik nach Apples Status-Pille:
  54 px hoch, 14 px Segoe UI Semibold, Koerper als Verlauf von Dunkelgrau
  oben in fast transparentes Schwarz unten, weicher Schatten, breitere
  Waveform. Beim Sprechen kreisen links wenige grosse, leuchtende Punkte
  (Thinking-Orbs "working", eigenes Pillen-Preset mit Halo) statt des
  pulsierenden Punkts; Ring und Ringbogen legen sich um den Orb, Inhalte
  crossfaden wirklich. Gemessen: 60 fps stabil (Tk: ~43 fps). Pille
  skaliert mit der Monitor-DPI. Watchdog, Topmost-Nachdruck, virtuelle
  Desktops und Multi-Monitor-Positionierung unveraendert.
- **Pille auf Federn** (overlay_model.Spring, Apple-Parameter response +
  damping): Ein-/Ausblenden, Breite, Ring und Bubble sind jetzt Federn
  statt fester Easings. Ein Hide, das ein laufendes Show unterbricht,
  uebernimmt die Geschwindigkeit und bremst weich ab (gemessen: kein
  Alpha-Sprung ueber 40/255 pro Frame, 90 % Sichtbarkeit nach ~160 ms).
  Gilt fuer Windows (Tk) und den macOS-Port (AppKit) gleichermassen.
- **Tipp-Antizipation** im Modus "Halten + Doppeltipp": nach einem kurzen
  Tipp haelt der Punkt den Atem an und ein Ringbogen waechst auf ein
  Viertel - der zweite Tipp schliesst ihn mit sichtbarem Ueberschwingen
  zum Freisprech-Ring (neuer Overlay-Zustand `armed`, Controller-Callback
  `on_arm`). Bleibt der zweite Tipp aus, zieht sich der Bogen zurueck.
- **Abschluss-Haken**: nach erfolgreichem Einfuegen zeichnet sich in der
  Pille ein Haken (0,24 s), dann geht sie wie gekommen nach unten (neuer
  Zustand `done`). Vorher verschwand die Pille kommentarlos.
- **Thinking-Orb als Verarbeitungs-Indikator**: statt dreier wandernder
  Punkte laeuft der "working"-Orb (Partikel auf gekippten Bahnen) aus
  thinking-orbs (MIT, Jakub Antalik) - als Python-Port der Geometrie,
  numerisch identisch mit der Originalbibliothek (Golden-Vektor-Test,
  max. Abweichung 5e-7). Waechst beim Betreten aus der Pillenmitte.
- **Reduced Motion**: ist "Animationen anzeigen" (Windows) bzw. "Bewegung
  reduzieren" (macOS) aus, blendet die Pille per Crossfade ohne Slide, der
  Ring schwingt nicht ueber, der Orb steht als Standbild.
- **Dashboard: helles und dunkles Schema** folgen der Systemeinstellung
  (kein App-Schalter). Alle Farben als Tokens; jeder Text erreicht
  mindestens 4,5:1 (vorher: Navigation 3,5:1, Platzhalter 4,4:1).
  Sichtbarer Tastaturfokus auf allen Bedienelementen, Tabs als echte
  ARIA-Tabs mit Pfeiltasten, Tab-Wechsel per Crossfade, Toast mit Feder.
  `prefers-reduced-motion` und `prefers-reduced-transparency` werden
  beachtet.
- **Dashboard-Struktur**: Kopfleiste als schwebende Glas-Toolbar (einzige
  Glasflaeche, Inhalte scrollen darunter durch), Einstellungen in Gruppen
  (Diktat, Sprache und Audio, Text und Einfuegen, System, Pille, Import)
  mit Schaltern und Beschreibungszeile statt langer Checkbox-Saetze,
  App-Chip an jedem Verlaufseintrag, Status-Punkt wird grau, wenn die App
  offline ist.
- **Tray-Icon** neu aus gefuellten Formen (Kapsel, Kragen, Stiel, Fuss)
  mit Supersampling, drei Zustaende: orange (bereit), invertiert weiss
  (Aufnahme laeuft), grau (pausiert).

### Changed
- Helle Pille ist jetzt weiss mit dunkler Schrift (17:1) statt mittelgrau
  mit weisser Schrift, dunkle Pille dunkelgrau-schwarz mit Verlauf statt
  reinem Schwarz; Clipboard-Hinweis heisst "In der Zwischenablage ·
  Strg+V" mit Glyphe; Standzeiten: Zwischenablage 2,5 s, Fehler 2 s.
- Frame-Uhr der Pille wird nach dem Einblend-Setup neu verankert und die
  feine Timer-Aufloesung sofort aktiviert - der erste sichtbare Frame
  sprang vorher auf bis zu 80 % (gemessen 0 -> 107/255).

- **Im Spiel / Vollbild automatisch pausieren** (Option, Standard an; im
  Dashboard und per Haekchen im Tray-Menue schaltbar): laeuft vorne eine
  Vollbild-App (Spiel, randloses Fenster, F11-Vollbild), ignoriert LocalFlow
  die Diktat-Hotkeys - und die Maus-Seitentaste geht unverschluckt ans
  Spiel, statt ein Diktat zu starten. Ein bereits laufendes Diktat laesst
  sich weiterhin beenden. Die Erkennung wird nur beim Tastendruck abgefragt
  (Direct3D-Vollbild-Status + Fenstergeometrie, ~0,1 ms), kein Polling,
  kein Hintergrund-Thread.

### Fixed
- **Toggle-Modus ("Druecken startet / druecken stoppt") brach Aufnahmen
  sofort wieder ab**: Ein zweiter Druck 60-200 ms nach dem ersten (prellende
  Maus-Seitentaste oder der antrainierte Doppeltipp aus dem Halten-Modus)
  galt als Stopp - im Log standen 200-350 ms lange Aufnahmen, die wegen
  min_duration_s stillschweigend verworfen wurden. Umgekehrt startete ein
  Prellen beim Stopp-Druck gleich die naechste Aufnahme. Jetzt zaehlt im
  Toggle-Modus ein Druck erst 0,4 s nach dem letzten Start/Stopp; ignorierte
  Druecke stehen im Log. Der Doppeltipp im Modus "Halten + Doppeltipp"
  bleibt unveraendert.
- **Terminal-Fenster-Sturm beim Systemstart**: LocalFlow startete beim Boot
  seinen eigenen `ollama serve` (Run-Key-Eintraege laufen vor dem
  Autostart-Ordner) und belegte damit Port 11434. Ollamas eigene Tray-App
  konnte danach nie binden und versuchte es endlos neu - gemessen 160.111
  Fehlstarts in zwei Tagen, jeder ein kurzlebiges Konsolenfenster. Jetzt
  gilt: gehoert der Port Ollamas Tray-App, wartet LocalFlow (nach einem
  Systemstart bis zu 90 s) und startet nie einen eigenen Server; ist die
  Tray-App installiert aber nicht gestartet, wird sie selbst gestartet
  statt `ollama serve`. Der `serve`-Fallback bleibt nur fuer
  Installationen ohne Tray-App.
- Der Ollama-Warmup blockiert die Diktier-Bereitschaft nicht mehr (eigener
  Thread) - Spracherkennung ist sofort nutzbar, das Cleanup schaltet sich
  zu, sobald der Server da ist.

## 0.3.0 - 2026-07-08

First public release.

### Added
- Smart spacing: a leading space is inserted automatically when the paste
  would glue onto existing text (caret probe; skips selections and
  terminals; toggleable)
- Widget design: dark/light theme for the overlay pill (light = muted
  Apple-grey bubble with white text), switchable live in the dashboard
- Custom sounds: user WAVs in `data/sounds/` + `custom.txt` replace the
  generated chimes (incl. hands-free) and are never overwritten
- Dashboard stat "time saved vs. typing" (replaces the average-latency card)
- Dashboard restyled to the muted grey scheme (dark text on mid-grey,
  accent matches the pill; the blue accent is gone)
- One-click Windows setup: `install.bat` (bootstraps Python via winget,
  then runs install.ps1; `install.ps1` now also finds the `py` launcher)
- Experimental macOS backend (`localflow/platform/darwin/`): paste via
  NSPasteboard + Cmd+V, hotkeys via pynput, voice-command keys, sounds via
  afplay, LaunchAgent autostart, flock single-instance; no ducking.
  **Untested on real hardware** - see PORTING.md phase 3.
- macOS overlay: the animated pill as an AppKit NSPanel with the full
  Windows choreography (waveform, live transcript, hover expand, themes,
  glass) - the animation/layout core is now shared (`overlay_model.py`)
  so both platforms stay in sync; state cycle CI-tested on real macOS
  runners (`tests/test_darwin_overlay_ci.py`). Fixed a missing
  `set_theme` on the overlay contract that would have crashed the app at
  startup on macOS.
- `install.sh` (macOS), CI workflow (Windows + macOS runners) that
  smoke-tests the darwin backend on real macOS
- `tests/test_darwin_port.py`: platform-independent checks (plist,
  keymaps, combo translation, backend surface)
- Metal STT engine for Apple Silicon: `stt_mlx.py` (mlx-whisper) with the
  same interface as the faster-whisper engine, auto-selected via
  `stt_factory.py`; shared hallucination/prompt-echo guards extracted to
  `stt_quality.py`; functionally tested in CI on real Apple Silicon
  runners (`tests/test_stt_mlx_ci.py`, `mlx-bench` workflow; measured
  3.2-3.5 s warm for 16 s audio on the paravirtualized runner GPU vs.
  ~20 s on CPU)
- One-click uninstall: `uninstall.bat` (Windows) / `uninstall.sh` (macOS) -
  stops the app, removes autostart + Start Menu entry / LaunchAgent, and
  optionally deletes the Whisper model cache, the Ollama cleanup model and
  the whole folder (dictation history only after explicit confirmation)
- Clipboard hygiene: transient clipboard entries (dictation text, smart-
  spacing probe, restore) are excluded from the Windows clipboard history
  (Win+V) and cloud sync, and a previously empty clipboard is emptied
  again after the paste instead of keeping the dictation

### Changed
- App icon (tray + Start Menu shortcut) and the dashboard header dot are
  now orange (#ff9500) instead of blue; the paused tray state stays grey

### Fixed
- Dictation crashed on stop when sounds were enabled (two `sounds.play`
  call sites missed in the platform-layer refactor; the whole package is
  now verified with pyflakes)
- Audio ducking: a per-session volume restore that fails (e.g. the app's
  audio session expired mid-dictation) is no longer silently swallowed -
  it is logged and healed by restoring the fresh session of the same
  process, so no app can get stuck at the ducked volume anymore. Crash
  recovery gained the same process-name fallback.
- Dictionary replacements containing backslashes (e.g. Windows paths) no
  longer crash the dictation (`re` treated the replacement as a template)
- Settings API now validates value types; a bad value (e.g. a string in
  `min_duration_s`) is ignored instead of breaking every following
  dictation across restarts, and saving writes the config file once
  instead of once per key
- Input device list no longer shows duplicate entries per device (one
  entry per name, WASAPI variant preferred)
- Changing the dictation hotkey while a recording is running now stops
  the recording cleanly instead of letting it run into the watchdog
- The smart-spacing caret probe releases Shift even if it fails midway
  (no more stuck Shift key)
- Dashboard thread no longer dies silently when the port is taken
  (logged + tray notification)
- "Words today" stat no longer counts error rows or freshly imported
  entries; Wispr import cleans up its temp copy of the database
- `hotkey2` default is now empty as documented (existing configs are
  untouched)

## 0.2.0 - 2026-07-07

### Added
- Live transcript preview in the overlay pill while recording; hover the
  pill to expand the full text multi-line (auto-collapses for one-liners)
- Trailing voice commands: "press enter" / "press backspace" /
  "press escape" / "press delete" press the key instead of typing the
  phrase; trigger words editable in the dashboard
- Optional second dictation hotkey running in parallel
- Widget design panel: font family, font size, glass look - applied live
- Dashboard offline banner with automatic reconnect
- Mouse-hotkey click swallowing toggle (replace selected text without
  moving the caret)
- Startup breadcrumb log ("DB ready: N history entries in <path>")
- Platform guard + PORTING.md (macOS port plan), sys_platform markers in
  requirements

### Changed
- Data directory moved from `%APPDATA%\LocalFlow` to `<repo>/data`
  (independent of how the process is started; override with
  `LOCALFLOW_DATA_DIR`)
- A second app start now opens the dashboard instead of a message box
- Overlay rebuilt on time-based tweens: width morphing, sequential content
  fades, waveform collapse into the processing dots, sub-pixel waveform
  scroll, ~60 fps with fine timer resolution only while visible

### Fixed
- Voice commands no longer fire into the wrong window when the paste
  target cannot be focused
- Releasing a second hotkey no longer stops/cancels a recording held by
  the first
- Stale live-preview text no longer appears at the start of the next
  dictation
- No dictation plaintext in logs (hallucination/prompt-echo paths now log
  metadata only)
- Ollama is never double-spawned (login boot race + parallel warmups)
- Toggle hotkey no longer gets stuck after a failed start while paused
- Hover expand no longer opens a near-empty large pill for one-line texts

## 0.1.0 - 2026-07-03

Initial local release: push-to-talk dictation, hands-free mode, AI cleanup
via Ollama, system audio ducking, animated overlay, dashboard (history,
dictionary, settings), Wispr Flow import, hardened localhost API.
