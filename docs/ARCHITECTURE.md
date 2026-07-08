# LocalFlow - Architecture & Design Decisions

Goal: a fully local push-to-talk dictation app for Windows. Core loop:
**hold hotkey -> speak -> release -> formatted text appears in the active
field.** Everything runs on the user's machine: Whisper for STT, a small
local LLM (Ollama) for cleanup. No network calls beyond localhost.

## Module map

| Module | Responsibility |
|---|---|
| `main.py` | Entry point, orchestration, tray icon (pystray), autostart (HKCU Run key), live-preview loop, voice-command execution |
| `hotkey.py` | Dictation state machine (hold / hold+double-tap hands-free / toggle) + low-level keyboard and mouse hooks; testable without hooks |
| `audio.py` | Mic capture 16 kHz mono (sounddevice), stream open only while recording, adaptive level meter (auto-gain for the waveform) |
| `stt.py` | faster-whisper `large-v3-turbo` on CUDA (fallback chain to CPU), language restriction |
| `stt_mlx.py` | mlx-whisper (Metal) for Apple Silicon - same interface as `stt.py`, plus an energy gate replacing the missing VAD |
| `stt_factory.py` | picks the platform engine (mlx on darwin, faster-whisper elsewhere; explicit device pins force faster-whisper) |
| `stt_quality.py` | engine-independent hallucination + prompt-echo guards, shared by both engines |
| `cleanup.py` | Ollama cleanup, prompt calibrated for light-touch formatting; health check + on-demand `ollama serve` with double-spawn protection |
| `commands.py` | Trailing voice commands ("press enter" -> key press), phrase matching on the raw transcript |
| `pipeline.py` | STT -> voice-command extraction -> cleanup -> dictionary/snippets -> history; GPU inference serialized |
| `inject.py` | Clipboard save -> set -> Ctrl+V -> restore (multi-format preservation: text, images, file lists); paste bound to the window that was focused at dictation time; synthetic key sender for voice commands |
| `ducking.py` | System audio mute during recording: single COM worker thread (no volume races), fast fade, crash recovery via state file |
| `overlay.py` | Animated overlay pill (tkinter, separate thread): waveform, live transcript, hover-to-expand, glass look; all state via a queue |
| `overlay_model.py` | platform-neutral pill choreography (tweens, easing, colors, text layout, timing) shared by the Tk (Windows) and AppKit (macOS) overlays |
| `db.py` | SQLite: history + dictionary |
| `settings.py` | JSON config in the data directory |
| `importer.py` | One-shot import from a locally installed Wispr Flow (`flow.sqlite`: dictionary + history) |
| `web/` | Flask dashboard on 127.0.0.1: history, dictionary editor, settings, import |

## Key design decisions

- **Latency budget**: end-to-end (speech end -> pasted text) targets ~1 s.
  Measured ~0.8 s median with CUDA. `beam_size=1` beats beam 5 on real
  dictations (WER 3.0% vs 6.1% median) and is faster - hence the default.
- **Light-touch cleanup**: the LLM fixes punctuation, casing, fillers and
  number words, never meaning or tone. The prompt is few-shot calibrated on
  real before/after dictation pairs. On any cleanup failure the raw
  transcript is used - the pipeline never blocks on the LLM.
- **Paste, don't type**: injection via clipboard + synthetic Ctrl+V is
  orders of magnitude faster than key-wise typing and works in almost every
  app. The user's clipboard (text, images, copied files) is snapshotted and
  restored afterwards.
- **Target-window binding**: the foreground window is captured when the
  dictation stops; the paste goes only there. If it cannot be focused, the
  text stays in the clipboard and the user gets a notification.
- **Mic privacy**: the input stream is opened per recording (Windows'
  "microphone in use" indicator only lights while dictating). Logs contain
  metadata only (durations, word counts) - never dictated text.
- **Voice commands on the raw transcript**: trailing phrases ("press
  enter") are stripped before LLM cleanup, because the LLM would reformat
  them. Executable keys are allow-listed (enter/backspace/escape/tab/delete)
  at every layer.
- **Data directory next to the code** (`<repo>/data`, overridable via
  `LOCALFLOW_DATA_DIR`): chosen so the location is independent of how the
  process is started (shell, Start Menu, autostart, sandboxed parents).
  `%APPDATA%` proved fragile: sandboxed launchers can transparently
  redirect it, silently splitting the data into two divergent copies.
- **Dashboard security**: bind to 127.0.0.1, Host allowlist against DNS
  rebinding, custom-header CSRF token for all state-changing requests
  (forms can't set custom headers; cross-origin fetch fails preflight).
  Powerful debug routes are only registered with `LOCALFLOW_DEBUG=1`.
- **Single instance**: a global mutex; a second start opens the dashboard
  of the running instance instead of erroring.
- **Hotkey robustness**: all hook events (keyboard + mouse) flow through
  one serial dispatch queue - per-event threads caused out-of-order
  down/up and endless recordings. The state machine is decoupled from the
  hooks and unit-tested.

## Deliberately out of scope (v0.x)

Meeting transcription, polish-selected-text, per-app tone matching,
mobile sync, teams/sharing. The dictionary (boost words + snippets) and
trailing voice commands are the only "command mode" features.

## Interop notes (Wispr Flow import)

The importer reads the locally installed Wispr Flow data
(`%APPDATA%\Wispr Flow\flow.sqlite`) and converts dictionary entries
(boost words, snippets) and history rows (raw/formatted text, app,
language, duration, timestamps) into LocalFlow's schema. Pure local
interoperability with the user's own data; nothing is uploaded.
