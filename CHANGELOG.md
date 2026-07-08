# Changelog

## Unreleased

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
  afplay, LaunchAgent autostart, flock single-instance; no overlay yet
  (NullOverlay placeholder), no ducking. **Untested on real hardware** -
  see PORTING.md phase 3.
- `install.sh` (macOS), CI workflow (Windows + macOS runners) that
  smoke-tests the darwin backend on real macOS
- `tests/test_darwin_port.py`: platform-independent checks (plist,
  keymaps, combo translation, backend surface)
- One-click uninstall: `uninstall.bat` (Windows) / `uninstall.sh` (macOS) -
  stops the app, removes autostart + Start Menu entry / LaunchAgent, and
  optionally deletes the Whisper model cache, the Ollama cleanup model and
  the whole folder (dictation history only after explicit confirmation)

### Fixed
- Dictation crashed on stop when sounds were enabled (two `sounds.play`
  call sites missed in the platform-layer refactor; the whole package is
  now verified with pyflakes)

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
