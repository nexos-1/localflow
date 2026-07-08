# Contributing

Thanks for your interest! LocalFlow is a small, focused project - the
goal is a fast, fully local dictation tool, not a platform. Bug reports,
portability fixes and focused improvements are very welcome.

## Dev setup

```bash
git clone https://github.com/nexos-1/localflow.git
cd localflow
# Windows: powershell -ExecutionPolicy Bypass -File install.ps1
# macOS:   bash install.sh
```

The venv ends up in `.venv/`. All user data lives in `data/` (git-ignored).

## Running tests

Tests are plain Python scripts (no pytest). Run them individually with the
venv interpreter:

```bash
.venv/bin/python tests/test_pipeline.py          # offline pipeline
.venv/bin/python tests/test_dictation_modes.py   # hotkey state machine
.venv/bin/python tests/test_darwin_port.py       # macOS backend contracts
```

See the README "Tests" section for the full list. CI
([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the
hardware-free suites on Windows and real macOS runners - it must stay
green. `tests/test_e2e_*.py` paste into real windows; read them before
running.

Lint: `python -m pyflakes localflow/ tests/` should be clean.

## Guidelines

- Keep diffs focused; one topic per PR.
- Bug fixes come with a test that would have caught the bug.
- Platform-specific code goes into `localflow/platform/<os>/`; shared
  logic stays platform-neutral (see `docs/ARCHITECTURE.md`).
- Parts of the codebase are commented in German - leave existing comments
  alone; new code may be commented in English or German.
- Dependency policy: pinned versions only, and no version published less
  than 14 days ago (supply-chain caution).
- Privacy is a feature: no telemetry, no network calls beyond localhost,
  never log dictated text.

## macOS status

The macOS port is experimental and looking for testers - see
[docs/TESTING-MACOS.md](docs/TESTING-MACOS.md) and
[PORTING.md](PORTING.md) for what is verified and what still needs real
hardware.
