"""Autostart via LaunchAgent-plist (EXPERIMENTELL/ungetestet auf Hardware).

Die plist-Erzeugung ist eine reine Funktion und wird plattformunabhaengig
unit-getestet (tests/test_darwin_port.py); nur load/unload beruehren macOS.
"""

import logging
import os
import plistlib
import subprocess
import sys

log = logging.getLogger("localflow.darwin")

LABEL = "io.github.nexos-1.localflow"


def _plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def _run_py() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "run.py")


def build_launch_agent(python_path: str, run_py: str) -> bytes:
    """LaunchAgent-Definition als plist-Bytes (pure Funktion, testbar)."""
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [python_path, run_py],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    })


def is_enabled() -> bool:
    return os.path.exists(_plist_path())


def set_enabled(enabled: bool):
    path = _plist_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(build_launch_agent(sys.executable, _run_py()))
        subprocess.run(["launchctl", "load", "-w", path], check=False)
    else:
        subprocess.run(["launchctl", "unload", path], check=False)
        try:
            os.remove(path)
        except OSError:
            pass
    log.info("Autostart (LaunchAgent) %s", "aktiviert" if enabled else "deaktiviert")
