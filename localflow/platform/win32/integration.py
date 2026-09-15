"""Win32-App-Integration: Single-Instance-Mutex, DPI, Startmenue-Eintrag.
(Aus main.py/shortcuts.py extrahiert, Verhalten identisch.)"""

import logging

log = logging.getLogger("localflow.integration")


def acquire_single_instance() -> bool:
    """Systemweiter Mutex - verhindert zwei parallele LocalFlow-Instanzen
    (doppelte Hooks wuerden jedes Diktat doppelt pasten)."""
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LocalFlowSingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def set_dpi_awareness():
    """Scharfe (nicht skaliert-verwaschene) Overlay-Darstellung auf High-DPI."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass


def prefers_reduced_motion() -> bool:
    """Windows-Einstellung "Animationen anzeigen" (Barrierefreiheit /
    Visuelle Effekte) - aus = Bewegung reduzieren. Liest
    SPI_GETCLIENTAREAANIMATION; bei Fehler False (volle Animation)."""
    try:
        import ctypes
        from ctypes import wintypes
        SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = wintypes.BOOL(1)
        if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0):
            return not bool(enabled.value)
    except Exception:  # noqa: BLE001
        log.debug("Reduced-Motion-Abfrage fehlgeschlagen", exc_info=True)
    return False


def ensure_launcher_shortcut():
    """Startmenue-Verknuepfung (Win-Taste -> "LocalFlow")."""
    from ...shortcuts import ensure_start_menu_shortcut
    ensure_start_menu_shortcut()
