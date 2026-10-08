# Installing LocalFlow - step by step

Deutsche Version: [INSTALL.de.md](INSTALL.de.md)

This guide is for users who don't work with GitHub or terminals every
day. It covers every click, including the security warnings you will see
and why they appear. Total time: ~10 minutes plus model downloads.

---

## Windows

### 1. Download

1. Open the project page on GitHub.
2. Click the green **"Code"** button, then **"Download ZIP"**.
3. In your Downloads folder, right-click the ZIP -> **"Extract All..."**
   and pick a permanent location, e.g. `C:\LocalFlow`.
   **Important:** extract first - don't run anything from inside the ZIP
   preview window.

### 2. Run the installer

Double-click **`install.bat`** in the extracted folder.

**You will likely see a blue SmartScreen warning** ("Windows protected
your PC"). This is normal for any script downloaded from the internet
that isn't signed with a paid certificate - it is not a virus detection.
LocalFlow is open source; everything the script does is readable in
plain text (`install.bat` / `install.ps1`). To proceed:
click **"More info"** -> **"Run anyway"**.

What the installer does, in order:
- Installs Python 3.12 via winget if you don't have it. If it does this,
  it asks you to **close the window and double-click `install.bat` once
  more** (so the fresh Python is picked up) - that's expected.
- Creates an isolated Python environment in the folder (`.venv/` -
  nothing is installed system-wide).
- Downloads the pinned dependencies. On Windows this includes CUDA
  libraries (~1 GB) - give it a few minutes.
- Creates a Start Menu entry and launches LocalFlow.

### 3. First start - what "normal" looks like

- On the very first start, LocalFlow downloads the speech-recognition
  model (~1.6 GB). Until that finishes, the pill at the bottom of the
  screen shows "Lade Modelle ..." if you try to dictate. This happens
  once; later starts load from cache in seconds.
- LocalFlow lives in the **system tray** (arrow near the clock) - there
  is no main window. Click the tray icon for the dashboard, right-click
  for the menu.
- To reopen it later: press the Windows key, type "LocalFlow".

### 4. Try it

1. Click into any text field (e.g. Notepad).
2. **Hold `Ctrl + Win`**, speak a sentence, release.
3. The pill shows your words live while you speak; on release the
   polished text is pasted.

Other basics: double-tap the hotkey for hands-free mode (tap again to
stop), `Ctrl + Alt + Space` as an alternative toggle. Everything
(hotkeys, microphone, languages, design) is configurable in the
dashboard: tray icon -> "Dashboard öffnen".

### 5. AI cleanup (set up automatically)

The installer already downloaded the cleanup engine: llama.cpp (~30 MB)
and the Gemma 3 4B model (~2.5 GB) into `data\llamacpp\`. LocalFlow starts
it by itself - nothing else to install, no extra background app. It adds
punctuation, casing and filler-word removal; without it you get the raw
transcript.

If that download failed (e.g. no internet during setup), run
`install-llama.ps1` again, or install [Ollama](https://ollama.com/download)
and run `ollama pull gemma3:4b` - LocalFlow uses Ollama as a fallback.

### Uninstall

Double-click **`uninstall.bat`** in the LocalFlow folder. It stops the
app, removes the autostart and Start Menu entries, and asks before
deleting the model cache, the Ollama model and your dictation history.
The cleanup engine in `data\llamacpp\` goes away with the LocalFlow folder.

---

## macOS (experimental)

**Requirements:** a Mac with Apple Silicon (M1 or newer) and Python 3.11+
(`python3 --version`; if missing: `brew install python`). Fair warning:
the macOS port is experimental - see the note at the end.

### 1. Download and install

1. GitHub -> green **"Code"** button -> **"Download ZIP"** -> unzip, e.g.
   to your home folder.
2. Open **Terminal** (Cmd+Space, type "Terminal") and run:

```bash
cd ~/localflow      # wherever you unzipped it
bash install.sh
```

No Gatekeeper warning appears in this flow - you are running an open
script yourself rather than opening a downloaded app. The installer
creates an isolated environment (`.venv/`), installs dependencies
(including the Metal speech engine on Apple Silicon), downloads the
cleanup engine (llama.cpp with Metal + Gemma 3 4B, ~2.5 GB), and
generates **LocalFlow.app in ~/Applications**. That app is built locally
on your machine, which is why it needs no Apple signing/notarization and
triggers no Gatekeeper warning either.

### 2. First start and permissions

Start LocalFlow via Spotlight (**Cmd+Space -> "LocalFlow"**) or, to see
the logs, with `.venv/bin/python run.py` from the folder.

macOS will ask for permissions - grant them to whichever app started
LocalFlow (LocalFlow/Python for Spotlight, or your Terminal):

1. **Microphone** - prompt appears at your first dictation.
2. **Accessibility**: System Settings -> Privacy & Security ->
   Accessibility -> enable the requesting app. Needed to paste text.
3. **Input Monitoring**, if asked - needed to hear the hotkey.

After granting 2./3., quit and restart LocalFlow once.

First start also downloads the speech model (~1.5 GB from HuggingFace).

### 3. Try it

Hold **`Ctrl + Cmd`** (the Mac equivalent of Ctrl+Win), speak, release.
Dashboard: menu-bar icon -> "Dashboard öffnen".

AI cleanup is set up by the installer (llama.cpp + Gemma 3 4B); Ollama
is only a fallback.

### Uninstall

```bash
bash uninstall.sh
```

Removes the LaunchAgent, LocalFlow.app and (after asking) the model
caches and your history.

### Experimental status

The macOS port is functionally tested in CI on real Apple Silicon
runners, but young on real desks: no audio ducking yet, smart spacing
has no effect, clipboard restore covers text only. Details:
[../PORTING.md](../PORTING.md). Problems? Please open an issue with
`data/logs/localflow.log` attached (it contains no dictated text).
