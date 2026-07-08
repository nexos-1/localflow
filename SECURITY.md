# Security

## Design

LocalFlow is built to keep everything on your machine:

- No telemetry, no cloud calls: the core loop talks only to
  `127.0.0.1` (Ollama) - dictated audio and text never leave the device.
- The dashboard binds to `127.0.0.1` only, with a Host allowlist
  (DNS-rebinding defense) and custom-header CSRF protection on all
  state-changing routes.
- Debug/test routes (e.g. synthetic dictation) only exist when the
  `LOCALFLOW_DEBUG=1` environment variable is set.
- Logs contain metadata only (durations, word counts) - never dictated
  text. Dictation history stays in a local SQLite file under `data/`
  (git-ignored).
- Dependencies are pinned; new versions are only adopted after a 14-day
  cooling-off period (supply-chain caution).

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Security" tab ->
"Report a vulnerability") instead of a public issue. Include steps to
reproduce. You should get a response within a week.
