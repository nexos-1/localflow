"""Autostart via HKCU-Run-Key (aus main.py extrahiert, Verhalten identisch)."""

import logging
import os
import sys

log = logging.getLogger("localflow.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    run_py = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "run.py")
    return f'"{pythonw}" "{run_py}"'


def is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "LocalFlow")
        return True
    except OSError:
        return False


def set_enabled(enabled: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "LocalFlow", 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, "LocalFlow")
            except OSError:
                pass
    log.info("Autostart %s", "aktiviert" if enabled else "deaktiviert")
