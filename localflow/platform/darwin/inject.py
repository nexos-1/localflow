"""Injector fuer macOS: NSPasteboard + synthetisches Cmd+V via CGEvent.
(EXPERIMENTELL/ungetestet auf Hardware - siehe PORTING.md 3.2.)

Gegenueber Windows bewusst v1-reduziert: Clipboard-Erhaltung nur fuer TEXT
(Bilder/Datei-Kopien: spaeter). WindowTarget ist die PID der App, die beim
Diktat-Stopp vorne war; "Fokussieren" = NSRunningApplication.activate.
Braucht TCC-Permission "Accessibility" (Events senden).

Carbon-Virtual-Key-Codes (ANSI-Layout; ASSUMPTION bis Hardware-Test):
V=9, Return=36, Tab=48, Backspace(Delete)=51, Escape=53, Fwd-Delete=117.
"""

import logging
import threading
import time

log = logging.getLogger("localflow.darwin")

# Waehrend WIR Events senden, muss der Hotkey-Hook weghoeren (gleiche
# Semantik wie win32.inject.injection_active).
injection_active = threading.Event()
_paste_lock = threading.Lock()

PASTE_OK = "ok"
PASTE_CLIPBOARD_ONLY = "clipboard_only"
PASTE_FAILED = "failed"

_VK_V = 9
_COMMAND_VK = {
    "enter": 36,
    "tab": 48,
    "backspace": 51,   # macOS "delete" = Backspace-Semantik
    "escape": 53,
    "delete": 117,     # forward delete = Entfernen-Semantik
}


def _pasteboard():
    from AppKit import NSPasteboard
    return NSPasteboard.generalPasteboard()


def _get_clipboard_text():
    try:
        from AppKit import NSPasteboardTypeString
        return _pasteboard().stringForType_(NSPasteboardTypeString)
    except Exception:  # noqa: BLE001
        return None


def _set_clipboard_text(text: str):
    from AppKit import NSPasteboardTypeString
    pb = _pasteboard()
    pb.clearContents()
    if not pb.setString_forType_(text, NSPasteboardTypeString):
        raise RuntimeError("NSPasteboard.setString schlug fehl")


def _post_key(vk: int, flags: int = 0):
    import Quartz
    for down in (True, False):
        evt = Quartz.CGEventCreateKeyboardEvent(None, vk, down)
        if flags:
            Quartz.CGEventSetFlags(evt, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
        time.sleep(0.012)


def _send_cmd_v():
    import Quartz
    injection_active.set()
    try:
        _post_key(_VK_V, Quartz.kCGEventFlagMaskCommand)
        time.sleep(0.03)
    finally:
        injection_active.clear()


def get_foreground_hwnd():
    """PID der vordersten App (Pendant zum HWND auf Windows)."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else None
    except Exception:  # noqa: BLE001
        return None


def get_active_app() -> tuple[str, str]:
    """(App-Name, "") - Fenstertitel braeuchte Screen-Recording-Permission
    (PORTING.md 3.2); v1 verzichtet darauf."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return (str(app.localizedName()) if app is not None else "", "")
    except Exception:  # noqa: BLE001
        return "", ""


def focus_window(pid) -> bool:
    if not pid:
        return False
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
        if app is None:
            return False
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.08)
        return get_foreground_hwnd() == int(pid)
    except Exception:  # noqa: BLE001
        log.debug("focus_window fehlgeschlagen", exc_info=True)
        return False


def paste_text(text: str, restore_delay: float = 1.0, target_hwnd=None,
               smart_spacing: bool = False) -> str:
    # smart_spacing: auf darwin noch ohne Wirkung (Caret-Sonde braucht eine
    # Cmd+C-Variante mit Selektions-Schutz - Phase 3b, siehe PORTING.md).
    if not text:
        return PASTE_FAILED
    with _paste_lock:
        focused = True
        if target_hwnd is not None:
            focused = focus_window(target_hwnd)
        if not focused:
            try:
                _set_clipboard_text(text)
                log.warning("Ziel-App %s nicht aktivierbar - Text liegt im Clipboard",
                            target_hwnd)
                return PASTE_CLIPBOARD_ONLY
            except Exception:  # noqa: BLE001
                return PASTE_FAILED
        old = _get_clipboard_text()
        try:
            _set_clipboard_text(text)
        except Exception:  # noqa: BLE001
            return PASTE_FAILED
        time.sleep(0.05)
        _send_cmd_v()
        time.sleep(restore_delay)
        if old is not None:
            try:
                _set_clipboard_text(old)
            except Exception:  # noqa: BLE001
                log.debug("Clipboard-Restore fehlgeschlagen", exc_info=True)
        return PASTE_OK


def press_keys(keys: list[str], target_hwnd=None, gap: float = 0.04):
    """Sprachbefehl-Tasten senden - wie auf Windows NUR, wenn das Ziel
    wirklich fokussiert werden konnte."""
    vks = [_COMMAND_VK[k] for k in keys if k in _COMMAND_VK]
    if not vks:
        return
    with _paste_lock:
        if target_hwnd is not None and not focus_window(target_hwnd):
            log.warning("Sprachbefehl verworfen - Ziel-App %s nicht aktivierbar",
                        target_hwnd)
            return
        injection_active.set()
        try:
            time.sleep(0.04)
            for vk in vks:
                _post_key(vk)
                time.sleep(gap)
        finally:
            injection_active.clear()
