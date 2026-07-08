"""macOS-App-Integration (EXPERIMENTELL/ungetestet, siehe PORTING.md).

Enthaelt neben Single-Instance auch das Pendant zur Windows-Startmenue-
Verknuepfung: ein LOKAL erzeugtes ~/Applications/LocalFlow.app - ein
Wrapper-Bundle, dessen Executable ein Shellskript ist, das das venv-Python
mit run.py startet. Weil das Bundle auf dem Rechner des Nutzers entsteht
(nie heruntergeladen wird), traegt es kein Quarantaene-Attribut: kein
Gatekeeper, keine Signatur, KEINE Notarisierung noetig (bewusste
Produktentscheidung, PORTING.md 3.11). Start dann per Spotlight/Launchpad
wie eine echte App; LSUIElement haelt es aus dem Dock (Menueleisten-App).
"""

import logging
import os
import plistlib

log = logging.getLogger("localflow.darwin")

_lock_file = None  # offen halten - der flock lebt so lange wie der Prozess


def acquire_single_instance() -> bool:
    """Exklusiver flock auf einer Lock-Datei im Datenordner."""
    global _lock_file
    import fcntl
    from ...settings import APP_DIR
    os.makedirs(APP_DIR, exist_ok=True)
    _lock_file = open(os.path.join(APP_DIR, ".localflow.lock"), "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


APP_BUNDLE = os.path.expanduser("~/Applications/LocalFlow.app")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def build_info_plist(version: str) -> bytes:
    """Info.plist des Wrapper-Bundles (pure Funktion, testbar)."""
    from .autostart import LABEL
    return plistlib.dumps({
        "CFBundleName": "LocalFlow",
        "CFBundleDisplayName": "LocalFlow",
        "CFBundleIdentifier": LABEL,
        "CFBundleExecutable": "localflow",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleIconFile": "localflow",
        # Menueleisten-App: kein Dock-Icon, kein App-Switcher-Eintrag
        "LSUIElement": True,
        "NSMicrophoneUsageDescription":
            "LocalFlow nimmt dein Diktat waehrend gedruecktem Hotkey auf.",
    })


def build_launcher_script(python_path: str, run_py: str) -> str:
    """Executable des Bundles: startet das venv-Python mit run.py (pure
    Funktion, testbar). Pfade gequotet - Repo-Pfade duerfen Leerzeichen
    enthalten ("whispr clone")."""
    return ("#!/bin/bash\n"
            "# Von LocalFlow generiert (bei jedem App-Start aktualisiert).\n"
            f"exec \"{python_path}\" \"{run_py}\"\n")


def _write_if_changed(path: str, data: bytes) -> bool:
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    with open(path, "wb") as f:
        f.write(data)
    return True


def ensure_launcher_shortcut():
    """~/Applications/LocalFlow.app erzeugen/aktualisieren (idempotent,
    wie die Startmenue-Verknuepfung auf Windows). Fehler sind nie fatal -
    die App laeuft auch ohne das Bundle."""
    import sys
    try:
        from ... import __version__
        macos_dir = os.path.join(APP_BUNDLE, "Contents", "MacOS")
        res_dir = os.path.join(APP_BUNDLE, "Contents", "Resources")
        os.makedirs(macos_dir, exist_ok=True)
        os.makedirs(res_dir, exist_ok=True)

        changed = _write_if_changed(
            os.path.join(APP_BUNDLE, "Contents", "Info.plist"),
            build_info_plist(__version__))
        launcher = os.path.join(macos_dir, "localflow")
        script = build_launcher_script(
            sys.executable, os.path.join(_repo_root(), "run.py"))
        changed |= _write_if_changed(launcher, script.encode())
        os.chmod(launcher, 0o755)

        icns = os.path.join(res_dir, "localflow.icns")
        if not os.path.exists(icns):
            try:
                from ...appicon import make_icon
                make_icon(size=1024).save(icns, format="ICNS")
            except Exception:  # noqa: BLE001 - Icon ist Kosmetik
                log.debug("App-Icon (.icns) konnte nicht erzeugt werden",
                          exc_info=True)
        if changed:
            log.info("Launcher-Bundle aktualisiert: %s", APP_BUNDLE)
    except Exception:  # noqa: BLE001
        log.exception("Launcher-Bundle konnte nicht erzeugt werden")


def set_dpi_awareness():
    """No-op: macOS skaliert Fenster selbst (Retina-Backing)."""
