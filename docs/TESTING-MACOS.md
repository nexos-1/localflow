# LocalFlow auf dem Mac testen - Anleitung fuer Tester

Danke, dass du testest! LocalFlow ist eine lokale Diktier-App: Hotkey
halten, sprechen, loslassen - der Text landet formatiert in der aktiven
App. Alles laeuft auf deinem Mac, nichts geht in die Cloud.

Der macOS-Port ist **auf echter Hardware noch nie gelaufen**. Alle Teile
sind einzeln in CI auf macOS-Runnern getestet - aber du bist der erste
Mensch, der die App interaktiv auf einem Mac benutzt. Genau deshalb ist
dieser Test so wertvoll. Erwartung: Es kann haken. Bitte alles notieren.

## Voraussetzungen

- **Apple-Silicon-Mac** (M1 oder neuer). Auf Intel-Macs ist die
  Spracherkennung zu langsam - bitte nicht auf Intel testen.
- Python 3.11 oder neuer: `python3 --version` (sonst: `brew install python`)
- ~4 GB freier Speicher (Spracherkennungs-Modell ~1,5 GB + Umgebung)
- Optional fuer die Text-Nachbearbeitung (Zeichensetzung, Fuellwoerter):
  [Ollama](https://ollama.com/download) installieren - ohne Ollama kommt
  der rohe Transkript-Text, das ist fuer den Test auch okay.
- Das GitHub-Repo ist privat: entweder wurdest du eingeladen
  (`git clone https://github.com/nexos-1/localflow.git`) oder du hast
  ein ZIP bekommen - dann einfach entpacken.

## Installation

```bash
cd localflow          # bzw. der entpackte Ordner
bash install.sh
.venv/bin/python run.py
```

Beim **allerersten Start** laedt die App das Whisper-Modell (~1,5 GB von
HuggingFace) herunter - das dauert je nach Leitung ein paar Minuten. Im
Terminal siehst du danach eine Zeile wie `mlx-whisper ... geladen (Metal)
in Xs`. Bitte das Terminal offen lassen: die Log-Ausgaben sind fuer uns
Gold wert.

## Berechtigungen (der heikelste Teil)

macOS vergibt Berechtigungen an die App, die Python gestartet hat - also
an dein **Terminal** (bzw. iTerm). Beim ersten Start bzw. Diktat fragt
macOS nacheinander:

1. **Mikrofon** - erlauben (Prompt kommt automatisch beim ersten Diktat).
2. **Bedienungshilfen** (Accessibility): Systemeinstellungen ->
   Datenschutz & Sicherheit -> Bedienungshilfen -> dein Terminal
   aktivieren. Ohne das kann die App nicht einfuegen (Cmd+V senden).
3. **Eingabemonitoring** (Input Monitoring), falls gefragt: ebenfalls das
   Terminal aktivieren. Ohne das hoert die App den Hotkey nicht.

Nach dem Erteilen von 2./3. das **Terminal komplett beenden und neu
starten**, dann LocalFlow wieder starten - macOS wendet die Grants oft
erst dann an.

## Bedienung in Kurzform

| Aktion | Taste |
|---|---|
| Diktieren | `Ctrl + Cmd` **halten**, sprechen, loslassen |
| Freisprechen | `Ctrl + Cmd` doppelt tippen, nochmal druecken = Stop |
| Toggle-Alternative | `Ctrl + Alt + Space` |
| Taste per Sprache | am Ende sagen: "... press enter" |
| Dashboard | Menueleisten-Icon -> "Dashboard öffnen" (oder http://127.0.0.1:5111) |

(Auf Windows heisst der Hotkey "Ctrl+Win" - die Windows-Taste ist auf dem
Mac Cmd. Im Dashboard laesst sich alles umkonfigurieren.)

## Test-Checkliste

Bitte der Reihe nach; ✅ / ❌ / Notiz pro Punkt reicht.

### A - Start
- [ ] App startet ohne Traceback im Terminal (die Warnung "macOS-Backend
      ist EXPERIMENTELL" ist normal)
- [ ] Oranges Icon erscheint in der Menueleiste, Menue oeffnet sich
- [ ] Dashboard laedt im Browser (http://127.0.0.1:5111)

### B - Basis-Diktat (in TextEdit)
- [ ] `Ctrl + Cmd` halten: kleine schwarze Pill erscheint unten in der
      Bildschirmmitte, pulsierender Punkt + Waveform bewegt sich beim Sprechen
- [ ] Waehrend des Sprechens erscheint das Transkript **live** in der Pill
- [ ] Bei laengerem Text: mit der Maus ueber die Pill fahren -> klappt
      mehrzeilig nach oben aus (weich animiert), Maus weg -> klappt ein
- [ ] Loslassen: drei wandernde Punkte (Verarbeitung), dann steht der Text
      in TextEdit
- [ ] Deutsch und Englisch diktieren - beide korrekt erkannt

### C - Modi
- [ ] Doppeltipp `Ctrl + Cmd`: Punkt wird zum **Ring** (Freisprechen),
      Aufnahme laeuft ohne Halten weiter; nochmal druecken = Stop + Paste
- [ ] `Ctrl + Alt + Space` einmal = Start, nochmal = Stop
- [ ] Ganz kurzer Einzeltipp: Aufnahme wird verworfen (kein Paste, Pill
      verschwindet)

### D - Ziel-Apps (Paste-Matrix)
Jeweils ein kurzes Diktat hinein:
- [ ] TextEdit
- [ ] Browser (Safari oder Chrome, z.B. Suchfeld)
- [ ] Terminal
- [ ] Notes, Slack oder Discord (was du hast)
- [ ] Clipboard-Erhalt: erst etwas Eigenes kopieren, dann diktieren, dann
      `Cmd + V`: dein alter Clipboard-Inhalt ist wieder da

### E - Sprachbefehle
- [ ] In einem Chat-/Suchfeld diktieren und mit "... press enter" enden:
      der Text wird eingefuegt UND abgeschickt (Enter), die Phrase selbst
      erscheint nicht

### F - Overlay-Optik (bitte Screenshots!)
- [ ] Position: unten mittig, knapp ueber dem Dock-Bereich, richtiger Monitor
- [ ] Pill faengt keine Klicks ab (durch die - unsichtbare wie sichtbare -
      Pill hindurchklicken funktioniert)
- [ ] Dashboard -> Einstellungen -> Widget-Design: Thema Hell/Dunkel,
      Glas-Look, Schriftgroesse - wirken sofort auf die Pill
- [ ] Screenshots: Pill eingeklappt (Waveform), mit Live-Text, ausgeklappt
      (Hover), im hellen Thema

### G - Sounds, Dashboard, History
- [ ] Start-/Stop-Chimes hoerbar (an/aus ueber Dashboard-Einstellungen)
- [ ] Dashboard-History: Diktate erscheinen mit Sprache/App/Dauer
- [ ] Statistik-Karten zaehlen hoch

### H - Autostart, Beenden, Deinstallation (zum Schluss)
- [ ] Menueleisten-Menue -> "Beim Anmelden starten" aktivieren, ab- und
      wieder anmelden: LocalFlow laeuft wieder (Icon da)
- [ ] "Beenden" ueber das Menue: Prozess endet sauber
- [ ] `bash uninstall.sh` laeuft durch (Fragen kannst du mit "N"
      beantworten, wenn du weitertesten willst)

### I - Latenz (wichtig fuer uns!)
- [ ] Gefuehlt: Wie lange vom Loslassen bis der Text dasteht? (Ziel < 2 s)
- [ ] Dashboard-Statistik: Latenz-Wert notieren
- [ ] Benchmark laufen lassen und die KOMPLETTE Ausgabe kopieren:
      `.venv/bin/python tests/bench_mlx_ci.py`
      (misst die Spracherkennungs-Geschwindigkeit auf deinem Chip)

## Bekannte Luecken - bitte NICHT als Bug melden

- **Kein Audio-Ducking**: YouTube/Spotify werden waehrend des Diktats
  nicht stummgeschaltet (auf Windows schon; macOS hat kein passendes API).
- **Smart Spacing** (automatisches Leerzeichen vor angeklebtem Text) ist
  auf dem Mac noch ohne Wirkung.
- Clipboard-Erhalt gilt nur fuer **Text** - kopierte Bilder/Dateien
  ueberleben ein Diktat nicht.
- In der History bleibt der **Fenstertitel leer** (braeuchte
  Screen-Recording-Permission, bewusst weggelassen); der App-Name steht da.
- **Maus-Seitentasten** als Hotkey sind auf dem Mac ungetestete Annahme -
  gern probieren, aber Scheitern ist halb-erwartet.

## Wenn etwas schiefgeht

- **Log-Datei**: `data/logs/localflow.log` im LocalFlow-Ordner - bitte
  mitschicken. Sie enthaelt KEINE diktierten Texte, nur Metadaten.
- Terminal-Ausgabe (Traceback) kopieren.
- **Hotkey reagiert nicht / kein Paste**: fast immer Berechtigungen -
  Bedienungshilfen + Eingabemonitoring fuers Terminal pruefen, Terminal
  neu starten.
- **Pill erscheint nie**: im Log nach "AppKit-Overlay" suchen ("bereit"
  vs. "fehlgeschlagen") und die Zeilen schicken.
- **Meldung "Text im Clipboard"** statt Paste: die Ziel-App liess sich
  nicht aktivieren - App-Name notieren, Text ist per `Cmd + V` da.

## Was wir zurueckbrauchen

1. macOS-Version, Chip (z.B. M2 Pro), Python-Version
2. Die Checkliste A-I mit ✅/❌ und Notizen
3. Screenshots aus F
4. Benchmark-Ausgabe aus I
5. Bei Fehlern: `data/logs/localflow.log` + Terminal-Ausgabe
