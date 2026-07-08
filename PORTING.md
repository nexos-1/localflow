# PORTING.md - LocalFlow on macOS

Status: LocalFlow is Windows-only today. This document explains exactly why
(file and line level), defines the target architecture for a portable core
with platform backends, sketches the macOS implementation, and lays out a
three-phase plan. Analysis date: 2026-07-07. No macOS hardware was available;
everything marked "assumption" needs verification on a real Mac in Phase 3.

---

## 1. Current state: Windows-only on three levels

### 1.1 Dependency level - `pip install -r requirements.txt` on macOS

Verified against PyPI (JSON API, 2026-07-07), pinned versions:

| Package | macOS status |
|---|---|
| `nvidia-cublas-cu12==12.9.2.10` | no macOS files at all - now behind a `sys_platform == "win32"` marker |
| `nvidia-cudnn-cu12==9.23.2.1` | no macOS files at all - marker |
| `pywin32==312` | no macOS files at all - marker |
| `pycaw==20251023`, `comtypes==1.4.16` | pure-Python wheels, but wrap Windows COM - marker |
| `keyboard==0.13.5` | pure-Python, installs, but its darwin backend requires root: `keyboard/_darwinkeyboard.py:429-430` raises `OSError` unless `os.geteuid() == 0` (verified in the installed wheel). Replaced by a Quartz backend in Phase 3. |
| `pystray==0.19.5` | works on macOS (NSStatusBar via AppKit, `_darwin.py:59`), but `HAS_DEFAULT_ACTION = False` (`_darwin.py:39`) - the `default=True` menu item (dashboard on icon click) does not fire on click; `notify()` uses `osascript` (`_darwin.py:122`) |
| `ctranslate2==4.8.0` | has `macosx_11_0_arm64` and `x86_64` wheels (cp39-cp314) - CPU only, no Metal backend |
| `sounddevice==0.5.5` | universal2 macOS wheel - fully portable |
| `av==17.1.0` | macOS arm64/x86_64 wheels present |
| `faster-whisper`, `numpy`, `Pillow`, `flask`, `requests`, `huggingface_hub`, `psutil` | portable |

### 1.2 Import level - the process cannot even start

`run.py` imports `localflow.main`, which imports at module level:

- `main.py` `import keyboard` - on macOS requires pyobjc and, for hooks, root
- `main.py` `from .inject import ...` - `inject.py` does top-level
  `import win32api / win32clipboard / win32con / win32gui / win32process`
- `main.py` `from . import sounds` - `sounds.py` does `import winsound`
  (module does not exist outside Windows)
- `main.py` `from .hotkey import PushToTalk` - `hotkey.py` does top-level
  `import keyboard`

Even the platform-neutral `DictationController` is unreachable on macOS
because it lives behind `hotkey.py`'s `import keyboard`. Both `run.py` and
`localflow/main.py` therefore carry an explicit `sys.platform` guard with a
friendly message pointing here.

Note: `from ctypes import wintypes` (overlay.py, hotkey.py) imports fine on
POSIX in Python 3; only the runtime `ctypes.windll.*` calls fail.

### 1.3 API level - Win32 usage per module

| Module | Windows API usage |
|---|---|
| `main.py` | single instance via `CreateMutexW`/`GetLastError`; toggle hotkey via `keyboard.add_hotkey`/`remove_hotkey`; autostart via `winreg` HKCU Run key (builds a `pythonw.exe` command); `shcore.SetProcessDpiAwareness` (guarded) |
| `hotkey.py` | low-level mouse hook `WH_MOUSE_LL` for mouse side buttons incl. optional event swallowing (`SetWindowsHookExW`, message loop, `PostThreadMessageW`); `keyboard.hook`; combo capture uses both hooks |
| `inject.py` | clipboard snapshot/restore of `CF_UNICODETEXT`/`CF_DIB`/`CF_HDROP`; `keybd_event` Ctrl+V; voice-command keys via VK map; foreground window handle; focus stealing via ALT tap + `SetForegroundWindow` + `AttachThreadInput` fallback; process name/title via `OpenProcess`/`GetModuleFileNameEx` |
| `overlay.py` | Tk window on a worker thread; Windows-only Tk `-transparentcolor`; monitor work area of the focused window; pill rect via `GetWindowRect`; timer resolution `winmm.timeBeginPeriod/timeEndPeriod`; hover detection `GetCursorPos`; click-through window styles (`WS_EX_LAYERED\|TRANSPARENT\|TOOLWINDOW\|NOACTIVATE`) |
| `ducking.py` | per-app session volumes via pycaw/WASAPI (lazy imports - the module imports cleanly everywhere, the worker functionality is Windows-only) |
| `sounds.py` | playback via `winsound.PlaySound(..., SND_ASYNC)`; the sound synthesis itself is pure numpy/wave and portable |
| `shortcuts.py` | Start menu `.lnk` via `WScript.Shell` COM; fully wrapped in try/except, degrades instead of crashing |
| `cleanup.py` | `subprocess.CREATE_NO_WINDOW \| DETACHED_PROCESS` (POSIX: use `start_new_session=True`); psutil process scan is portable |
| `stt.py` | NVIDIA DLL dir registration - effectively inert on macOS (the `site-packages/nvidia` directory cannot exist there) |
| `importer.py` | Wispr Flow source path under `%APPDATA%` |

### 1.4 Already portable (no changes needed)

`pipeline.py`, `stt.py` (CPU fallback chain ends at `("cpu", "int8")`),
`cleanup.py` (except the Popen flags), `db.py` (sqlite/WAL), `settings.py`
(data dir is `<project>/data` with `LOCALFLOW_DATA_DIR` override),
`commands.py` (pure regex), `audio.py` (sounddevice universal2),
`appicon.py` (PIL), the Flask dashboard `web/app.py` including its
host-allowlist/CSRF hardening, the sound synthesis, and the
`DictationController` state machine (unit-tested).

---

## 2. Target architecture

### 2.1 Layout

```
localflow/
  controller.py          # DictationController + normalize_combo/KEY_ALIASES
                         # moved out of hotkey.py (no keyboard import)
  platform/
    __init__.py          # get_backends() -> selects by sys.platform
    base.py              # Protocols below + shared constants
    win32/
      hotkey.py          # current hotkey.py minus controller
      inject.py          # current inject.py
      ducking.py         # current ducking.py
      overlay.py         # current overlay.py (Tk)
      sounds.py          # winsound playback
      autostart.py       # winreg
      integration.py     # mutex, DPI, start menu shortcut
    darwin/              # Phase 3
      ...
```

### 2.2 Backend interfaces (signatures derived from actual call sites)

```python
# localflow/platform/base.py
from typing import Protocol, Callable, Optional

WindowTarget = Optional[int]   # win32: HWND; darwin: pid


class PttHook(Protocol):
    """Today: hotkey.PushToTalk(combo, controller, swallow_mouse)."""
    def start(self) -> None: ...
    def stop(self) -> None: ...


class HotkeyBackend(Protocol):
    def make_ptt(self, combo: str, controller: "DictationController",
                 swallow_mouse: bool = False) -> PttHook: ...
    def add_hotkey(self, combo: str, callback: Callable[[], None]) -> object: ...
    def remove_hotkey(self, handle: object) -> None: ...
    def capture_combo(self, timeout: float = 10.0) -> str | None: ...


class Injector(Protocol):
    PASTE_OK: str
    PASTE_CLIPBOARD_ONLY: str
    PASTE_FAILED: str
    def is_injecting(self) -> bool: ...
    def get_foreground_target(self) -> WindowTarget: ...
    def get_active_app(self) -> tuple[str, str]: ...          # (app, title)
    def paste_text(self, text: str, restore_delay: float = 1.0,
                   target: WindowTarget = None) -> str: ...
    def press_keys(self, keys: list[str], target: WindowTarget = None,
                   gap: float = 0.04) -> None: ...


class Ducker(Protocol):
    duck_volume: float
    is_muted: bool
    mute_complete_ts: float     # consumed by main._trim_muted_head
    did_mute_sessions: int      # 0 => head trim disables itself
    def duck(self) -> None: ...
    def restore(self) -> None: ...


class OverlayBackend(Protocol):
    """Queue-based, all methods callable from any thread (as today)."""
    def start(self) -> None: ...
    def set_state(self, state: str) -> None: ...   # hidden|loading|recording|
                                                   # locked|processing|clipboard|error
    def set_level(self, level: float) -> None: ...
    def set_text(self, text: str) -> None: ...
    def set_glass(self, enabled: bool) -> None: ...
    def set_style(self, font_family: str | None,
                  font_size: int | None) -> None: ...


class SoundBackend(Protocol):
    def ensure_sounds(self) -> None: ...           # synthesis is shared code
    def play(self, name: str) -> None: ...         # start|stop|lock|error, async


class AutostartBackend(Protocol):
    def is_enabled(self) -> bool: ...
    def set_enabled(self, enabled: bool) -> None: ...


class AppIntegration(Protocol):
    def acquire_single_instance(self) -> bool: ...
    def ensure_launcher_shortcut(self) -> None: ...  # darwin: no-op
    def set_dpi_awareness(self) -> None: ...         # darwin: no-op
```

Additionally, `stt.Transcriber` becomes a seam so an Apple-Silicon engine
can be swapped in later without touching the pipeline:

```python
class TranscriberBackend(Protocol):
    device: str   # pipeline checks == "cuda" for the resilient fallback
    def transcribe(self, audio, language: str | None = None,
                   initial_prompt: str | None = None,
                   allowed_languages: list[str] | None = None,
                   beam_size: int = 1) -> tuple[str, str, object]: ...
```

### 2.3 Contract notes

- `WindowTarget` is opaque to `main.py`. Windows keeps HWND semantics,
  darwin uses the frontmost application pid.
- The `injection_active` coupling between inject and the hotkey hook moves
  into the platform package: the hook asks `injector.is_injecting()`.
- A no-op `Ducker` with `did_mute_sessions = 0` automatically disables the
  muted-head trim in `main._trim_muted_head` - no main.py changes needed
  for platforms without ducking.
- Combo strings stay canonical (`ctrl+win`, `maus5`); each backend owns its
  raw-name alias table. On darwin the canonical token `win` maps to the
  Command key.

---

## 3. macOS implementation sketch (Phase 3)

All packages below must pass the project's 14-day supply-chain rule at
install time.

### 3.1 Hotkey backend
- Packages: `pyobjc-framework-Quartz` (raw CGEventTap) or `pynput`
  (assumption: per-event suppression via its darwin intercept - verify).
- APIs: `CGEventTapCreate(kCGHIDEventTap, ...)` listening to
  `keyDown/keyUp/flagsChanged` plus `otherMouseDown/Up` for mouse buttons
  4/5 (`buttonNumber` 3/4). Modifier-only combos like ctrl+cmd come from
  `flagsChanged`. Swallowing = active tap returning NULL for the event.
- Permissions: Accessibility and Input Monitoring (TCC), NOT root.
- Watchdog: taps are disabled by the OS on slow callbacks
  (`kCGEventTapDisabledByTimeout`) - re-enable in the callback.

### 3.2 Injector backend
- Packages: `pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz`.
- Clipboard: `NSPasteboard.generalPasteboard` - snapshot/restore string,
  TIFF/PNG image data (counterpart of CF_DIB), and file URLs (CF_HDROP).
- Paste: `CGEventCreateKeyboardEvent` with Command flag + Carbon key code
  for V (kVK_ANSI_V = 9; key codes are assumptions until verified),
  posted via `CGEventPost`. Voice-command keys: Return 36, Delete
  (backspace) 51, Escape 53, Tab 48, Forward-Delete 117.
- Targeting: capture `NSWorkspace.frontmostApplication()` pid before the
  tail sleep; re-activate via `NSRunningApplication`. If activation fails,
  fall back to PASTE_CLIPBOARD_ONLY exactly like Windows.
- `get_active_app`: app name from NSRunningApplication; window TITLE
  requires `CGWindowListCopyWindowInfo` + Screen Recording permission -
  ship without titles first.
- Synthetic-event filtering: keep the `injection_active` flag; the event
  tap checks it (optionally tag events via a dedicated CGEventSource).

### 3.3 Overlay + tray: one AppKit main loop (the structural change)
- Problem: today the Tk overlay runs on a worker thread while pystray
  blocks the main thread. On macOS both Tcl/Tk and AppKit demand the
  process main thread (AppKit constraint verified in pystray
  `_darwin.py:53`; Tk constraint is an assumption). Tk also lacks
  `-transparentcolor` there, so the pill would render as an opaque
  rectangle.
- Solution: on darwin, do not use Tk at all. One NSApplication run loop on
  the main thread hosts BOTH the status item and the overlay: a
  borderless, non-activating NSPanel
  (`NSWindowStyleMaskBorderless|NonactivatingPanel`), window level
  status-bar-high, `ignoresMouseEvents = True` (click-through), clear
  background, custom NSView drawing the pill (port of overlay.py's state
  machine: states, width tween, fades, waveform). Animation via
  NSTimer/CVDisplayLink; window alpha for show/hide; placement via
  `NSScreen.visibleFrame`.
- Hover detection: `NSEvent.mouseLocation()` (global, no permission).
- pystray caveat: no default click action on darwin - "open dashboard on
  icon click" becomes a plain menu item there.
- The `Overlay` facade (queue-based `set_state/set_level/set_text/...`)
  stays identical; only the render host differs per platform.
- **IMPLEMENTED 2026-07-08** exactly as designed above
  (`platform/darwin/overlay.py`): the choreography (tweens, easing,
  colors, text layout, timing) was extracted to the shared
  `overlay_model.py` and is used by BOTH the Tk and the AppKit pill, so
  future polish lands on both platforms. Animation runs on a
  self-re-arming `AppHelper.callLater` tick (60 fps visible, 10 Hz idle);
  the panel hangs off pystray's NSApp loop - no main.py changes needed.
  CI-verified on real macOS runners (tests/test_darwin_overlay_ci.py):
  panel construction, full dictation state cycle, glass alpha,
  click-through, drawRect execution. NOT yet verified: how it LOOKS
  (positioning, font metrics, hover feel) - needs eyes on real hardware.

### 3.4 Ducking backend
- macOS has no public per-app volume API (assumption carried over from the
  2026-07-03 analysis; re-check at implementation time). Options:
  1. No-op backend (recommended default; hide `duck_audio` in the
     dashboard on darwin). Head-trim disables itself.
  2. System output volume via `osascript` (crude).
  3. Pause scriptable players (Music, Spotify) via AppleScript.

### 3.5 Sounds backend
- Keep the numpy/wave synthesis as shared code.
- Playback: `NSSound` (async) or `subprocess.Popen(["afplay", path])`.

### 3.6 Autostart backend
- LaunchAgent plist at `~/Library/LaunchAgents/<bundle-id>.plist` with
  `RunAtLoad = true` and `ProgramArguments = [<venv python>, run.py]`;
  manage via `launchctl`.

### 3.7 Single instance + integration
- `fcntl.flock` on a lock file in the data dir (held for process
  lifetime); keep the existing "second start opens the dashboard"
  behavior.
- `ensure_launcher_shortcut` and `set_dpi_awareness`: no-ops on darwin.

### 3.8 Cleanup (Ollama)
- Replace the Windows `creationflags` with `start_new_session=True` on
  POSIX. Ollama ships natively for macOS. `psutil` is a direct dependency.

### 3.9 STT - MEASURED 2026-07-08 (GitHub macos-latest, Apple Silicon)
- `large-v3-turbo` on ctranslate2 CPU/int8 is **far too slow**: ~20 s to
  transcribe 16 s of speech; preview-style passes 18-28 s each (model load
  14 s). Even granting that GitHub runners are low-core M-chips and real
  M-series Macs may be ~3-4x faster, that still lands at 5-7 s per pass -
  unusable for the live preview (needs <0.7 s) and painful for the final
  pass. Reproduce with `gh workflow run stt-bench` (tests/bench_stt_ci.py).
- CONCLUSION: a Metal-backed engine is **mandatory**, not optional, for
  the Mac port: implement `TranscriberBackend` on `mlx-whisper` (Metal) or
  `pywhispercpp` (whisper.cpp, Metal) - or fall back to a much smaller
  model at a quality cost. The hallucination filters only need segment
  logprob/no-speech fields - verify the chosen engine exposes them.
- **mlx-whisper MEASURED 2026-07-08** (same runner class, `gh workflow run
  mlx-bench`, tests/bench_mlx_ci.py): Metal IS exposed on GitHub runners
  ("Apple Paravirtual device", 7 GB). `large-v3-turbo` warm full pass:
  **3.5 s for 16.2 s audio** (5.7x faster than CPU); preview-style passes
  flat at 2.9-3.4 s regardless of buffer length. The runner GPU is
  paravirtualized, so treat these as a LOWER bound - real M-series
  hardware is substantially faster. Good enough for the final dictation
  pass; the live preview interval needs re-measuring on real hardware.
- **IMPLEMENTED**: `stt_mlx.MlxTranscriber` (Metal engine, same interface),
  `stt_factory.make_transcriber` (auto-selects mlx on darwin, faster-whisper
  elsewhere; explicit device pins force faster-whisper), shared quality
  filters extracted to `stt_quality.py` (mlx segments expose
  avg_logprob/no_speech_prob, so hallucination + prompt-echo guards work
  identically). Functional CI test on real Apple Silicon:
  tests/test_stt_mlx_ci.py (mlx-bench workflow). Notes: no beam search
  (greedy), no VAD, language restriction falls back to first allowed
  language (mlx exposes no probability list).

### 3.10 Settings, importer, dashboard
- Per-platform defaults: `overlay_font` "Segoe UI" -> system font; hotkey
  display strings ("win" shown as Cmd). Data dir logic already portable.
- Importer: Wispr Flow on macOS presumably stores `flow.sqlite` under
  `~/Library/Application Support/Wispr Flow` (assumption - verify).
- Dashboard: fully portable; UI texts like "Strg+V" need a cosmetic pass.

### 3.11 Permissions (TCC) and packaging
- Required: Microphone, Accessibility (paste + event tap), Input
  Monitoring (key listening). Optional: Screen Recording (window titles).
- TCC grants attach to the HOST binary: running from a terminal grants the
  terminal, not LocalFlow. Ship a real `.app` bundle (py2app or briefcase)
  with a stable bundle id, `LSUIElement = true` (menu-bar app, no Dock
  icon). Ad-hoc signing resets TCC on every rebuild - a Developer ID
  certificate avoids permission re-prompts during development and is
  required for distribution (notarization).

---

## 4. Open risks

1. ~~Main-loop restructuring (tray + overlay on one AppKit loop)~~
   RESOLVED without restructuring: the overlay host is fully
   backend-owned; on darwin the NSPanel + its timer simply attach to the
   NSApp loop that pystray already runs on the main thread (3.3).
2. TCC friction: permissions bound to the bundle; rebuilds with changing
   signatures re-prompt; dev runs from the venv behave differently than
   the bundled app.
3. ~~STT latency on CPU unknown~~ RESOLVED: CPU measured unusable, mlx
   engine implemented and CI-tested (3.9). Remaining: preview latency on
   real (unvirtualized) M-series hardware; mlx model cache lives under
   `~/.cache/huggingface` with different repo names (uninstall.sh hint).
4. Ducking cannot be ported 1:1 - product decision required (no-op vs.
   system volume vs. player pause).
5. Event swallowing (`swallow_mouse`) depends on active-tap semantics and
   OS tap timeouts - needs careful testing in real apps.
6. Clipboard fidelity: restoring images/file copies across the paste is
   best-effort on macOS (TIFF vs. DIB, promised pasteboard data).
7. pystray darwin: no default click action; menu-only UX difference.
8. Everything in section 3 is untestable until real hardware exists
   (Phase 3 gate).

---

## 5. Phase plan

### Phase 1 - guard + documentation (DONE; no behavior change on Windows)
- This file.
- `run.py` checks `sys.platform` BEFORE importing `localflow.main` (the
  import itself crashes on macOS, see 1.2) and exits with a friendly
  message pointing here; same guard at the top of `localflow/main.py`
  (covers `python -m localflow.main`).
- requirements.txt: `sys_platform == "win32"` markers on `pywin32`,
  `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `pycaw`, `comtypes`;
  `psutil` declared as a direct dependency. On Windows the resolver
  outcome is byte-identical.

### Phase 2 - extract interfaces, Windows implementation (DONE)
Implemented as a facade rather than a physical file move (same layering,
much smaller diff on a daily-driver app):
- `localflow/controller.py`: `DictationController` + combo normalization
  physically extracted; importable on any OS, zero platform imports.
  `localflow/hotkey.py` keeps only the Win32 hooks and re-exports the
  controller names for backward compatibility.
- `localflow/platform/base.py`: the backend Protocols (section 2.2).
- `localflow/platform/win32/`: the single architectural access point -
  `make_backends()` bundles hooks/inject/ducking/overlay/sounds plus the
  newly extracted `autostart.py` (winreg) and `integration.py` (mutex,
  DPI, launcher shortcut). The big Win32 modules stay at their historic
  paths; only this package and legacy shims reference them.
- `main.py` and the dashboard's capture route run entirely through
  `get_backends()`; `main.py` no longer imports keyboard/inject/overlay/
  ducking/sounds directly. `sounds.py` synthesis is shared, playback is
  lazy-imported win32. `cleanup.py` spawns Ollama POSIX-safely.
- Exit criteria met: full test suite green, backend smoke test (all
  protocol surfaces present, autostart command resolves from the new
  module location), manual dictation round-trip on Windows unchanged.

A darwin backend now only needs to implement the `make_backends()`
surface (10 attributes) plus the overlay/tray main-loop rework - no
further `main.py` changes required.

### Phase 3 - darwin backend (CODE WRITTEN 2026-07-07, **UNTESTED**)
`localflow/platform/darwin/` implements the full `make_backends()` surface:
injector (NSPasteboard text-only + Cmd+V/keys via CGEvent, pid targeting),
hotkeys (pynput: PTT, toggle via GlobalHotKeys, capture; `win` maps to Cmd;
mouse side buttons assumed at button values 3/4; swallow via
`darwin_intercept` with graceful degradation), sounds (shared synthesis +
afplay), autostart (LaunchAgent plist + launchctl), single instance
(flock), no-op ducker (disables head-trim automatically) and the animated
pill as an **AppKit NSPanel** (section 3.3; NullOverlay remains as the
no-pyobjc fallback). `install.sh` exists.

Verification status - be honest about this:
- Verified from Windows: syntax of all modules, plist generation, Carbon
  keymap covers all voice-command keys, combo translation (win->cmd),
  mapping consistency, backend surface completeness
  (`tests/test_darwin_port.py`).
- Verified via CI on real macOS runners once the repo is on GitHub
  (`.github/workflows/ci.yml`): imports, backend construction,
  NSPasteboard round-trip, portable unit tests.
- NOT verified anywhere yet: event taps/permissions, CGEvent key codes on
  real hardware, pynput mouse-button values, focus/activation behavior,
  end-to-end dictation. Anyone running this on a Mac is a tester.

### Phase 3b - remaining on real hardware
- ~~NSPanel overlay + tray on one AppKit main loop (section 3.3)~~ DONE
  and CI-tested (construction + state cycle); visual QA (position, font
  metrics, hover feel) still needs real eyes.
- Manual e2e matrix: paste into TextEdit, browser, terminal, Slack;
  hold/double-tap/toggle modes; mouse-button hotkeys; dashboard capture.
- ~~Benchmark STT on Apple Silicon; decide on mlx/whisper.cpp backend~~
  DONE via CI (3.9): mlx-whisper chosen, implemented (`stt_mlx.py`) and
  functionally tested on real Apple Silicon runners. Remaining on real
  hardware: re-measure preview latency (runner GPU is paravirtualized).
- Package as `.app` (py2app/briefcase), TCC prompts, codesigning +
  notarization (Apple Developer account) for a true one-click download.

---

## 6. Verification log

Verified 2026-07-07: all statements in section 1 against the working tree;
PyPI wheel availability for every pinned package (PyPI JSON API);
`keyboard/_darwinkeyboard.py:429-430` root check and `pystray/_darwin.py`
darwin behavior read from the installed wheels; pycaw's
`Requires-Dist: psutil`; psutil 7.2.2 macOS wheels present. Carried over
from the 2026-07-03 analysis (not re-verifiable without a Mac): Tk
main-thread constraint on macOS, absence of a public per-app volume API,
mlx-whisper/whisper.cpp suitability. Marked assumptions: Carbon virtual
key codes, pynput suppression details, Wispr Flow's macOS data path.
