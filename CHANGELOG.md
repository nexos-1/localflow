# Changelog

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
