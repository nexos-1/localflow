"""Text ins aktive Fenster einfuegen: Clipboard sichern -> setzen -> Ctrl+V -> restaurieren.

Gleiche Strategie wie Wispr Flow ("paste_event"): funktioniert in praktisch
jeder App und ist bei langen Texten um Groessenordnungen schneller als Tippen.

Gesichert/restauriert werden Text (CF_UNICODETEXT), Bilder (CF_DIB) und
Datei-Kopien (CF_HDROP), damit ein Diktat kein kopiertes Bild/keine Datei
des Nutzers zerstoert.
"""

import ctypes
import logging
import struct
import threading
import time

# Waehrend WIR Tasten senden (Ctrl+V, ALT-Tap), muss der Hotkey-Hook
# weghoeren - sonst beendet unser eigenes synthetisches ctrl-up ein gerade
# gehaltenes Ctrl+Win des Nutzers (live beobachtet).
injection_active = threading.Event()

# Serialisiert das gesamte Paste (Clipboard sichern -> setzen -> Ctrl+V ->
# restaurieren). Ohne diesen Lock koennten zwei schnell aufeinanderfolgende
# Diktate ihre Clipboard-Operationen und synthetischen Tastendruecke
# verschraenken -> falscher Text gepastet, Nutzer-Clipboard zerstoert.
_paste_lock = threading.Lock()

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

log = logging.getLogger("localflow.inject")

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_C = 0x43
VK_V = 0x56
VK_LEFT = 0x25
VK_RIGHT = 0x27
KEYEVENTF_KEYUP = 0x0002

# Smart Spacing wird in diesen Apps NIE probiert: die Sonde sendet Strg+C,
# und das ist in Terminals ein Abbruch-Signal (wuerde z.B. eine getippte
# Kommandozeile killen). Namen = Prozessname ohne .exe, lowercase.
SMART_SPACING_SKIP_APPS = {
    "windowsterminal", "openconsole", "conhost", "cmd", "powershell",
    "pwsh", "wezterm-gui", "alacritty", "mintty", "putty", "kitty",
}

# Beginnt der NEUE Text mit einem dieser Zeichen, klebt er zu Recht an
# (Satzzeichen-Fortsetzung) - kein Leerzeichen davor.
_NO_SPACE_START = set(",.;:!?)]}%…")
# Steht VOR dem Cursor eines dieser Zeichen, ist Ankleben gewollt
# (oeffnende Klammern/Anfuehrungszeichen).
_NO_SPACE_AFTER = set("([{\"'„«‚")

# Sprachbefehl-Tasten (siehe commands.py). Nur diese werden je gesendet.
_COMMAND_VK = {
    "enter": 0x0D,      # VK_RETURN
    "backspace": 0x08,  # VK_BACK
    "escape": 0x1B,     # VK_ESCAPE
    "tab": 0x09,        # VK_TAB
    "delete": 0x2E,     # VK_DELETE
}

PRESERVED_FORMATS = (win32con.CF_UNICODETEXT, win32con.CF_DIB, win32con.CF_HDROP)

# Ergebnis-Codes fuer paste_text
PASTE_OK = "ok"
PASTE_CLIPBOARD_ONLY = "clipboard_only"   # Ziel nicht fokussierbar, Text liegt im Clipboard
PASTE_FAILED = "failed"


def _open_clipboard(retries: int = 6) -> bool:
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:  # noqa: BLE001 - kann kurz von anderer App gesperrt sein
            time.sleep(0.02 * (attempt + 1))
    return False


def _snapshot_clipboard() -> dict:
    """Aktuelle Clipboard-Inhalte der erhaltenen Formate sichern."""
    snap: dict = {}
    if not _open_clipboard():
        return snap
    try:
        for fmt in PRESERVED_FORMATS:
            if not win32clipboard.IsClipboardFormatAvailable(fmt):
                continue
            try:
                snap[fmt] = win32clipboard.GetClipboardData(fmt)
            except Exception:  # noqa: BLE001
                pass
    finally:
        win32clipboard.CloseClipboard()
    return snap


def _pack_hdrop(paths: tuple[str, ...]) -> bytes:
    """DROPFILES-Struktur fuer CF_HDROP bauen (pywin32 liest Tupel, schreibt aber nicht)."""
    body = "".join(p + "\0" for p in paths) + "\0"
    return struct.pack("<Iiiii", 20, 0, 0, 0, 1) + body.encode("utf-16-le")


def _restore_clipboard(snap: dict):
    if not _open_clipboard():
        log.warning("Clipboard-Restore: nicht zu oeffnen")
        return
    try:
        win32clipboard.EmptyClipboard()
        for fmt, data in snap.items():
            try:
                if fmt == win32con.CF_HDROP:
                    win32clipboard.SetClipboardData(fmt, _pack_hdrop(data))
                else:
                    win32clipboard.SetClipboardData(fmt, data)
            except Exception as e:  # noqa: BLE001
                log.warning("Clipboard-Restore Format %s fehlgeschlagen: %s", fmt, e)
    finally:
        win32clipboard.CloseClipboard()


def _set_clipboard_text(text: str, retries: int = 5):
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return
            finally:
                win32clipboard.CloseClipboard()
        except Exception:  # noqa: BLE001
            time.sleep(0.03 * (attempt + 1))
    raise RuntimeError("Clipboard konnte nicht gesetzt werden")


def _get_clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            try:
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:  # noqa: BLE001
                return None
        return None
    finally:
        win32clipboard.CloseClipboard()


def _tap(vk: int):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.01)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _combo(mod: int, vk: int):
    ctypes.windll.user32.keybd_event(mod, 0, 0, 0)
    time.sleep(0.01)
    _tap(vk)
    time.sleep(0.01)
    ctypes.windll.user32.keybd_event(mod, 0, KEYEVENTF_KEYUP, 0)


_PROBE_SENTINEL = "⁣LocalFlow-Probe⁣"


def _probe_char_before_caret() -> str | None:
    """Zeichen unmittelbar vor dem Cursor im fokussierten Feld ermitteln.
    Rueckgabe: None = unbekannt ODER es existiert eine Selektion (dann nichts
    anfassen - der Ersetzen-Workflow des Nutzers hat Vorrang); "" = Feld-/
    Zeilenanfang; sonst das Zeichen. Der Cursor steht danach wieder an der
    urspruenglichen Position. Ablauf: Sentinel ins Clipboard -> Strg+C (aendert
    sich das Clipboard, gab es eine Selektion) -> Shift+Links + Strg+C liest
    das Zeichen -> Rechts kollabiert die Selektion zurueck."""
    injection_active.set()
    try:
        _set_clipboard_text(_PROBE_SENTINEL)
        time.sleep(0.03)
        _combo(VK_CONTROL, VK_C)
        time.sleep(0.06)
        if _get_clipboard_text() != _PROBE_SENTINEL:
            return None  # Selektion vorhanden (oder App kopiert ganze Zeile)
        ctypes.windll.user32.keybd_event(VK_SHIFT, 0, 0, 0)
        time.sleep(0.01)
        _tap(VK_LEFT)
        time.sleep(0.01)
        ctypes.windll.user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)
        _combo(VK_CONTROL, VK_C)
        time.sleep(0.06)
        got = _get_clipboard_text()
        if got is None or got == _PROBE_SENTINEL:
            return ""  # nichts selektierbar -> Cursor steht ganz am Anfang
        _tap(VK_RIGHT)  # Selektion kollabieren = urspruengliche Position
        time.sleep(0.02)
        return got
    except Exception:  # noqa: BLE001
        return None
    finally:
        injection_active.clear()


def _should_space(before: str | None, text: str) -> bool:
    """Reine Entscheidungslogik (unit-getestet): Leerzeichen voranstellen?"""
    if not before or not text:
        return False  # unbekannt/Selektion/Feldanfang: nichts erzwingen
    last = before[-1]
    if last.isspace() or last in _NO_SPACE_AFTER:
        return False
    if text[0] in _NO_SPACE_START or text[0].isspace():
        return False
    return True


def _send_ctrl_v():
    injection_active.set()
    try:
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)  # Hook-Verarbeitung der Events abwarten
    finally:
        injection_active.clear()


def press_keys(keys: list[str], target_hwnd: int | None = None, gap: float = 0.04):
    """Sprachbefehl-Tasten (Enter/Backspace/Escape ...) ins Zielfenster senden.
    Serialisiert mit dem Paste (gemeinsamer Lock) und unter injection_active,
    damit der Hotkey-Hook die synthetischen Events ignoriert. Wird nach einem
    etwaigen Paste aufgerufen - fokussiert das Ziel sicherheitshalber erneut."""
    vks = [_COMMAND_VK[k] for k in keys if k in _COMMAND_VK]
    if not vks:
        return
    with _paste_lock:
        # Tasten NIE blind senden: landet der Fokus nicht im Zielfenster,
        # wuerde z.B. ein Enter im falschen Fenster etwas absenden.
        if target_hwnd is not None and not focus_window(target_hwnd):
            log.warning("Sprachbefehl verworfen - Zielfenster %s nicht fokussierbar",
                        target_hwnd)
            return
        injection_active.set()
        try:
            time.sleep(0.04)  # kurzer Moment, falls direkt nach einem Paste
            for vk in vks:
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.012)
                ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(gap)
        finally:
            injection_active.clear()


def get_foreground_hwnd() -> int:
    return win32gui.GetForegroundWindow()


def focus_window(hwnd: int) -> bool:
    """Fenster in den Vordergrund holen; umgeht die Foreground-Sperre.
    True, wenn hwnd danach wirklich fokussiert ist."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if win32gui.GetForegroundWindow() == hwnd:
        return True
    injection_active.set()
    try:
        # ALT-Tap loest die SetForegroundWindow-Sperre
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            # AttachThreadInput-Fallback
            try:
                fg = win32gui.GetForegroundWindow()
                fg_tid, _ = win32process.GetWindowThreadProcessId(fg)
                cur_tid = win32api.GetCurrentThreadId()
                ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.08)
    finally:
        injection_active.clear()
    return win32gui.GetForegroundWindow() == hwnd


def get_active_app() -> tuple[str, str]:
    """(prozessname, fenstertitel) des Vordergrundfensters - fuer die History."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
        try:
            exe = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        name = exe.rsplit("\\", 1)[-1].removesuffix(".exe")
        return name, title
    except Exception:  # noqa: BLE001
        return "", ""


def paste_text(text: str, restore_delay: float = 1.0, target_hwnd: int | None = None,
               smart_spacing: bool = False) -> str:
    """Fuegt text ins Zielfenster ein. Gibt PASTE_OK, PASTE_CLIPBOARD_ONLY
    oder PASTE_FAILED zurueck.

    - Zielfenster nicht fokussierbar -> Text bleibt im Clipboard
      (PASTE_CLIPBOARD_ONLY), damit der Nutzer manuell einfuegen kann.
    - restore_delay muss grosszuegig sein: restaurieren wir das alte Clipboard,
      bevor die Ziel-App das Ctrl+V verarbeitet hat, landet der alte Inhalt
      statt des Diktats im Feld (beobachtet bei frisch gestartetem Notepad)."""
    if not text:
        return PASTE_FAILED

    # Ganzer Paste-Vorgang seriell - nur ein Diktat manipuliert das Clipboard
    # gleichzeitig (sonst Fehl-Paste / zerstoertes Nutzer-Clipboard).
    with _paste_lock:
        focused = True
        if target_hwnd is not None:
            focused = focus_window(target_hwnd)

        if not focused:
            try:
                _set_clipboard_text(text)
                log.warning("Zielfenster %s nicht fokussierbar - Text liegt im Clipboard",
                            target_hwnd)
                return PASTE_CLIPBOARD_ONLY
            except RuntimeError as e:
                log.error("%s", e)
                return PASTE_FAILED

        snap = _snapshot_clipboard()
        if smart_spacing:
            # Klebt der neue Text sonst direkt an bestehendem Text (Satzende,
            # Wortmitte), automatisch ein Leerzeichen voranstellen. Die Sonde
            # laeuft NACH dem Snapshot (sie benutzt das Clipboard) und bricht
            # bei vorhandener Selektion sofort ab (Ersetzen-Workflow).
            before = _probe_char_before_caret()
            if _should_space(before, text):
                text = " " + text
        try:
            _set_clipboard_text(text)
        except RuntimeError as e:
            log.error("%s", e)
            return PASTE_FAILED
        time.sleep(0.05)  # Clipboard-Besitzwechsel settlen lassen
        _send_ctrl_v()
        # Der Ziel-App Zeit geben, das Paste zu verarbeiten, bevor restauriert wird
        time.sleep(restore_delay)
        if snap:
            _restore_clipboard(snap)
        return PASTE_OK
