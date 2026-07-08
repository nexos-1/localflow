"""Start-Menue-Verknuepfung: LocalFlow ist nach dem Beenden ueber das
Startmenue (Win-Taste -> "LocalFlow") jederzeit wieder startbar.

Wird bei jedem App-Start aktualisiert (idempotent) - so stimmen Pfade auch
nach einem Verschieben des Projektordners wieder.
"""

import logging
import os
import sys

log = logging.getLogger("localflow.shortcuts")

START_MENU = os.path.join(os.environ.get("APPDATA", ""),
                          r"Microsoft\Windows\Start Menu\Programs")
LNK_PATH = os.path.join(START_MENU, "LocalFlow.lnk")


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_start_menu_shortcut():
    from .appicon import ensure_ico
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        ico = ensure_ico()
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        run_py = os.path.join(_project_root(), "run.py")
        shell = win32com.client.Dispatch("WScript.Shell")
        lnk = shell.CreateShortCut(LNK_PATH)
        lnk.TargetPath = pythonw
        lnk.Arguments = f'"{run_py}"'
        lnk.WorkingDirectory = _project_root()
        lnk.IconLocation = ico
        lnk.Description = "LocalFlow - lokales Diktieren (Whisper + Ollama)"
        lnk.Save()
        log.info("Start-Menue-Verknuepfung aktualisiert: %s", LNK_PATH)
    except Exception:  # noqa: BLE001
        log.exception("Start-Menue-Verknuepfung fehlgeschlagen")
