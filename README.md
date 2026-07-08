# LocalFlow

**Fully local voice dictation for Windows.** Hold a hotkey, speak, release -
your words appear as polished text in whatever app has focus. No cloud, no
subscription: Whisper (speech-to-text) and Ollama (AI cleanup) run entirely
on your own machine.

Built as a drop-in replacement for Wispr Flow. German README: [README.de.md](README.de.md)

> **Windows is first-class. macOS is experimental**: a Darwin backend exists
> (paste, hotkeys, voice commands, sounds) and its portable pieces are
> smoke-tested in CI on real macOS runners, but the app has never been used
> interactively on a Mac and has no overlay yet - see [PORTING.md](PORTING.md)
> for status and plan.

## Features

- **Push-to-talk dictation** into any Windows app (paste via clipboard,
  bound to the window you dictated in)
- **Smart spacing**: if the caret sits directly after existing text
  (sentence end, mid-word), a space is inserted automatically; selections
  are never touched and terminals are excluded. Toggleable.
- **Hands-free mode**: double-tap the hotkey, keep talking, tap again to stop
- **Hotkeys**: any keyboard combo or mouse side buttons (Mouse4/Mouse5),
  captured live in the settings UI; optional **second dictation hotkey**
  running in parallel (e.g. Mouse5 *and* Ctrl+Win)
- **Live transcript preview**: watch your words appear in the overlay pill
  *while* you speak; hover over the pill to expand the full text as
  multi-line. The final, cleaned text is pasted on release. Toggleable.
- **Voice commands**: end a dictation with "press enter", "press backspace",
  "press escape" or "press delete" and LocalFlow presses the key instead of
  typing the phrase. Trigger words are editable in the dashboard.
- **AI cleanup** (local LLM): punctuation, casing, filler removal,
  numbers-as-digits - meaning-preserving, calibrated on real dictations
- **Multilingual**: language auto-detected per dictation (e.g. German/English
  mixed), restricted to your configured languages
- **System audio auto-mute**: other apps (YouTube, Spotify) fade to silence
  in ~100 ms while you dictate and are restored exactly afterwards; the
  recording head where audio was still audible is trimmed automatically
- **Animated overlay pill**: monochrome, live waveform with auto-gain,
  smooth state transitions, live transcript, hover-to-expand; widget design
  panel with dark/light theme, glass look, font family and size - all
  applied live
- **Custom sounds**: replace the start/stop/hands-free chimes with your own
  WAVs (drop them into `data/sounds/` and list their names in
  `custom.txt` - they survive app updates)
- **Clipboard etiquette**: your previous clipboard content (text, image or
  copied files) is restored after each paste, and LocalFlow's transient
  entries are excluded from the Win+V clipboard history and cloud clipboard
- **Dashboard** (localhost): history with day grouping and search,
  dictionary (boost words + text snippets), settings, stats including time
  saved vs. typing - shows a clear banner when the app is not running and
  reconnects automatically
- **One-click Wispr Flow import**: dictionary and dictation history are
  pulled straight from the locally installed Wispr app (dashboard button)
- **Quality guards**: Whisper hallucination filtering (silence/noise),
  prompt-echo filtering, language restriction
- **Privacy**: microphone stream only open while recording; logs contain no
  dictation plaintext; the core loop makes zero network calls beyond
  localhost (Ollama on 127.0.0.1)
- **Hardened local API**: Host allowlist (DNS-rebinding defense) + custom-header
  CSRF protection on the dashboard; powerful test/debug routes only exist with
  `LOCALFLOW_DEBUG=1`
- Single-instance lock (a second start simply opens the dashboard),
  crash-safe volume restore, autostart with Windows, Ollama health check
  with double-spawn protection

## Requirements

- Windows 11, Python 3.11+
- NVIDIA GPU recommended (CUDA) - falls back to CPU automatically. Note:
  the pinned requirements include the CUDA runtime wheels (~1 GB); CPU-only
  users can remove the `nvidia-*` lines.
- [Ollama](https://ollama.com/download) for AI cleanup (optional - without
  it you get the raw transcript) with a small model, e.g. `ollama pull gemma3:4b`

## Install (Windows)

**Easiest**: download the repo as ZIP, extract it, and **double-click
`install.bat`**. It installs Python via winget if missing, creates a venv,
installs pinned dependencies, sets up the Start Menu entry and launches the
app. No terminal needed.

From a terminal instead:

```powershell
git clone https://github.com/nexos-1/localflow.git
cd localflow
powershell -ExecutionPolicy Bypass -File install.ps1
```

The Whisper model (~1.6 GB) downloads on first start; subsequent starts
load it from cache in a few seconds. To reopen after quitting: press the
Windows key and type "LocalFlow".

## Install (macOS - experimental)

```bash
bash install.sh
.venv/bin/python run.py
```

Grant Microphone + Accessibility (and if asked, Input Monitoring)
permissions on first start. Expect rough edges: the port has never been
used interactively on real hardware, there is no overlay yet (audio
feedback only), and no audio ducking. Also note: CPU-only Whisper is too
slow for dictation on Apple Silicon (measured ~20 s for 16 s of audio); a
Metal-backed engine is required and planned. Status: [PORTING.md](PORTING.md).

## Usage

| Action | Default |
|---|---|
| Dictate (hold) | hold `Ctrl + Win`, release when done |
| Hands-free | double-tap the hotkey, tap again to stop |
| Hands-free toggle key | `Ctrl + Alt + Space` |
| Press a key by voice | say "... press enter" at the end of a dictation |
| Expand the live transcript | hover the pill while dictating |
| Dashboard | click the tray icon or open http://127.0.0.1:5111 |

Modes (hold only / hold + double-tap / toggle), both hotkeys, voice command
trigger words, live preview, microphone, cleanup model, audio mute, widget
design (font, size, glass look) and autostart are all configurable in the
dashboard; changes apply immediately.

A note on mouse-button hotkeys: by default the side button keeps its normal
function in parallel (e.g. browser back/forward) while also triggering
dictation. Enable "swallow mouse hotkey" in the settings to make the button
exclusive to dictation - then pressing it over selected text replaces the
selection instead of moving the caret.

## Uninstall

**Windows**: double-click **`uninstall.bat`**. It stops the app, removes
the autostart entry and Start Menu shortcut, and offers to delete the
Whisper model cache (~1.6 GB), the Ollama cleanup model and finally the
whole folder. Your dictation history (`data/localflow.sqlite`) is only
deleted if you explicitly confirm it.

**macOS**: `bash uninstall.sh` (same flow; also removes the LaunchAgent).

## Data & privacy

All data stays local in `<repo>/data/` (config.json, SQLite history, logs,
generated sounds). The location is deliberately independent of how the app
is started; override it with the `LOCALFLOW_DATA_DIR` environment variable.
The folder is git-ignored, so your dictation history can never end up in a
commit. Logs record metadata only (durations, word counts) - never the
dictated text itself.

## Measured performance (RTX 5080, real voice)

- End-to-end (speech end to pasted text): **~0.8 s median**
- STT: faster-whisper `large-v3-turbo`, CUDA float16, beam 1
  (3.0% median WER on the author's real dictations)
- Cleanup: `gemma3:4b` via Ollama, ~465 ms, 0.95 similarity to the
  commercial reference formatting
- Live preview: incremental re-transcription every ~0.4 s while recording

## Architecture

```
localflow/
  main.py        tray app, orchestration, autostart, live-preview loop
  controller.py  platform-neutral dictation state machine (hold/double-tap/toggle)
  hotkey.py      Win32 keyboard/mouse low-level hooks feeding the controller
  audio.py       mic capture (16 kHz mono), adaptive level meter
  stt.py         faster-whisper + quality guards
  cleanup.py     Ollama prompt calibrated for light-touch formatting
  commands.py    trailing voice commands ("press enter" -> key press)
  pipeline.py    STT -> voice commands -> cleanup -> dictionary -> history
  inject.py      clipboard paste with multi-format preservation, key sender
  ducking.py     system audio mute worker (fast fade, crash recovery)
  overlay.py     animated overlay pill (tkinter): waveform, live transcript,
                 hover expand, glass look
  db.py          SQLite history + dictionary
  importer.py    one-click import from Wispr Flow's flow.sqlite
  web/           Flask dashboard
  platform/      backend contracts + the win32 and darwin implementations
```

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

Run individual suites from `tests/` with the venv Python, e.g.:

```powershell
.venv\Scripts\python.exe tests\test_pipeline.py         # offline pipeline
.venv\Scripts\python.exe tests\test_stt_guards.py       # hallucination/language guards
.venv\Scripts\python.exe tests\test_dictation_modes.py  # hotkey state machine
.venv\Scripts\python.exe tests\test_second_hotkey.py    # dual hotkey wiring
.venv\Scripts\python.exe tests\test_commands.py         # voice command parsing
.venv\Scripts\python.exe tests\test_cleanup_start.py    # Ollama no-double-spawn
.venv\Scripts\python.exe tests\test_levelmeter.py       # adaptive level meter
.venv\Scripts\python.exe tests\test_smart_spacing.py    # smart-spacing decision logic
.venv\Scripts\python.exe tests\test_clipboard.py        # clipboard preservation
.venv\Scripts\python.exe tests\test_darwin_port.py      # macOS backend (portable checks)
```

The hardware-free suites also run in CI on Windows and on real macOS
runners ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

`tests/test_e2e_*.py` drive the running app end-to-end (they type and paste
into real windows - read them before running). `tests/extract_real_audio.py`
can build a personal STT benchmark from a local Wispr Flow database; the
extracted audio stays on your machine and is git-ignored.

## Known limitations

- Very short dictations (under ~1 s) are inherently hard for Whisper; the
  detected language is always right, but single words can come out wrong.
- The AI-cleanup prompt is calibrated for German and English; other
  languages transcribe fine but may be cleaned less reliably.
- No meeting notetaker, no polish-selected-text - deliberately out of scope
  (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## License

[MIT](LICENSE). Dependencies remain under their own licenses (note:
`pystray` is LGPL-3.0, used as an ordinary pip dependency).
