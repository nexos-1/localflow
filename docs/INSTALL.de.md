# LocalFlow installieren - Schritt fuer Schritt

English version: [INSTALL.md](INSTALL.md)

Diese Anleitung ist fuer Nutzer, die nicht taeglich mit GitHub oder
Terminals arbeiten. Sie erklaert jeden Klick - inklusive der
Sicherheitswarnungen, die du sehen wirst, und warum sie erscheinen.
Dauer: ~10 Minuten plus Modell-Downloads.

---

## Windows

### 1. Herunterladen

1. Die Projektseite auf GitHub oeffnen.
2. Auf den gruenen **"Code"**-Button klicken, dann **"Download ZIP"**.
3. Im Downloads-Ordner: Rechtsklick auf die ZIP -> **"Alle
   extrahieren..."** und einen dauerhaften Ort waehlen, z.B.
   `C:\LocalFlow`. **Wichtig:** erst entpacken - nichts aus der
   ZIP-Vorschau heraus starten.

### 2. Installer ausfuehren

Im entpackten Ordner **`install.bat`** doppelklicken.

**Sehr wahrscheinlich erscheint eine blaue SmartScreen-Warnung** ("Der
Computer wurde durch Windows geschuetzt"). Das ist bei jedem aus dem
Internet geladenen Skript ohne bezahltes Zertifikat normal - es ist
KEINE Virenerkennung. LocalFlow ist Open Source; alles, was das Skript
tut, ist im Klartext nachlesbar (`install.bat` / `install.ps1`). Weiter
geht's mit: **"Weitere Informationen"** -> **"Trotzdem ausfuehren"**.

Was der Installer der Reihe nach macht:
- Installiert Python 3.12 ueber winget, falls es fehlt. In dem Fall
  bittet er dich, **das Fenster zu schliessen und `install.bat` noch
  einmal zu doppelklicken** (damit das frische Python greift) - das ist
  so gedacht.
- Erstellt eine isolierte Python-Umgebung im Ordner (`.venv/` - nichts
  wird systemweit installiert).
- Laedt die festgepinnten Abhaengigkeiten. Auf Windows sind CUDA-
  Bibliotheken dabei (~1 GB) - ein paar Minuten einplanen.
- Legt einen Startmenue-Eintrag an und startet LocalFlow.

### 3. Erster Start - was "normal" aussieht

- Beim allerersten Start laedt LocalFlow das Spracherkennungs-Modell
  (~1,6 GB). Bis das fertig ist, zeigt die Pill unten am Bildschirm
  "Lade Modelle ...", wenn du diktierst. Das passiert nur einmal;
  spaetere Starts laden in Sekunden aus dem Cache.
- LocalFlow lebt im **System-Tray** (Pfeil neben der Uhr) - es gibt kein
  Hauptfenster. Klick aufs Tray-Icon oeffnet das Dashboard, Rechtsklick
  das Menue.
- Spaeter wieder oeffnen: Windows-Taste druecken, "LocalFlow" tippen.

### 4. Ausprobieren

1. In ein beliebiges Textfeld klicken (z.B. Editor).
2. **`Strg + Win` halten**, einen Satz sprechen, loslassen.
3. Waehrend du sprichst, zeigt die Pill deine Worte live; beim Loslassen
   wird der formatierte Text eingefuegt.

Weitere Basics: Hotkey doppelt tippen = Freisprechen (nochmal druecken =
Stopp), `Strg + Alt + Leertaste` als alternativer Umschalter. Alles
(Hotkeys, Mikrofon, Sprachen, Design) laesst sich im Dashboard
einstellen: Tray-Icon -> "Dashboard oeffnen".

### 5. Optional: AI-Aufbereitung (empfohlen)

Ohne diesen Schritt bekommst du das rohe Transkript; mit ihm
Zeichensetzung, Gross-/Kleinschreibung und Fuellwort-Entfernung:

1. [Ollama](https://ollama.com/download) installieren (kostenlos, lokal).
2. Eingabeaufforderung oeffnen und ausfuehren: `ollama pull gemma3:4b`
   (~3 GB).

Fertig - LocalFlow findet Ollama beim naechsten Diktat automatisch.

### Deinstallation

**`uninstall.bat`** im LocalFlow-Ordner doppelklicken. Beendet die App,
entfernt Autostart- und Startmenue-Eintraege und fragt nach, bevor
Modell-Cache, Ollama-Modell oder deine Diktat-History geloescht werden.

---

## macOS (experimentell)

**Voraussetzungen:** ein Mac mit Apple Silicon (M1 oder neuer) und
Python 3.11+ (`python3 --version`; falls fehlt: `brew install python`).
Ehrliche Warnung: der macOS-Port ist experimentell - siehe Hinweis am
Ende.

### 1. Herunterladen und installieren

1. GitHub -> gruener **"Code"**-Button -> **"Download ZIP"** ->
   entpacken, z.B. in deinen Benutzerordner.
2. **Terminal** oeffnen (Cmd+Leertaste, "Terminal" tippen) und:

```bash
cd ~/localflow      # wohin auch immer du entpackt hast
bash install.sh
```

In diesem Ablauf erscheint keine Gatekeeper-Warnung - du fuehrst ein
offenes Skript selbst aus, statt eine heruntergeladene App zu oeffnen.
Der Installer erstellt eine isolierte Umgebung (`.venv/`), installiert
die Abhaengigkeiten (inkl. Metal-Sprach-Engine auf Apple Silicon),
prueft Ollama und erzeugt **LocalFlow.app in ~/Applications**. Diese App
wird lokal auf deinem Rechner gebaut - deshalb braucht sie weder
Apple-Signatur noch Notarisierung und loest ebenfalls keine
Gatekeeper-Warnung aus.

### 2. Erster Start und Berechtigungen

LocalFlow per Spotlight starten (**Cmd+Leertaste -> "LocalFlow"**) oder,
um die Logs zu sehen, mit `.venv/bin/python run.py` aus dem Ordner.

macOS fragt nach Berechtigungen - erteile sie der App, die LocalFlow
gestartet hat (LocalFlow/Python beim Spotlight-Start, sonst dein
Terminal):

1. **Mikrofon** - Prompt kommt beim ersten Diktat.
2. **Bedienungshilfen**: Systemeinstellungen -> Datenschutz & Sicherheit
   -> Bedienungshilfen -> die anfragende App aktivieren. Noetig fuers
   Einfuegen.
3. **Eingabemonitoring**, falls gefragt - noetig, um den Hotkey zu hoeren.

Nach 2./3. LocalFlow einmal beenden und neu starten.

Der erste Start laedt ausserdem das Sprachmodell (~1,5 GB von
HuggingFace).

### 3. Ausprobieren

**`Ctrl + Cmd` halten** (das Mac-Pendant zu Strg+Win), sprechen,
loslassen. Dashboard: Menueleisten-Icon -> "Dashboard oeffnen".

Optionale AI-Aufbereitung: [Ollama](https://ollama.com/download)
installieren, dann `ollama pull gemma3:4b`.

### Deinstallation

```bash
bash uninstall.sh
```

Entfernt LaunchAgent, LocalFlow.app und (nach Rueckfrage) Modell-Caches
und History.

### Experimenteller Status

Der macOS-Port ist in der CI auf echten Apple-Silicon-Runnern funktional
getestet, aber jung auf echten Schreibtischen: noch kein Audio-Ducking,
Smart Spacing ohne Wirkung, Clipboard-Erhalt nur fuer Text. Details:
[../PORTING.md](../PORTING.md). Probleme? Bitte ein Issue mit
`data/logs/localflow.log` anhaengen (enthaelt keine diktierten Texte).
