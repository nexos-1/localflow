"""macOS-App-Integration (EXPERIMENTELL/ungetestet, siehe PORTING.md)."""

import logging
import os

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


def ensure_launcher_shortcut():
    """No-op: Discoverability kommt auf macOS spaeter ueber ein .app-Bundle
    (PORTING.md 3.11); ein Startmenue-Aequivalent gibt es nicht."""


def set_dpi_awareness():
    """No-op: macOS skaliert Fenster selbst (Retina-Backing)."""
