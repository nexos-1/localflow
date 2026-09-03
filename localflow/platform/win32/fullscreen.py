"""Vollbild-/Spiel-Erkennung (Win32) - fuer "im Spiel automatisch pausieren".

Bewusst OHNE Polling, Timer oder Hintergrund-Thread: die Frage "laeuft
gerade eine Vollbild-App?" wird nur genau dann gestellt, wenn der
Diktat-Hotkey gedrueckt wird (Gate im Hook). Kosten pro Abfrage: eine
Handvoll user32-Aufrufe (Mikrosekunden), kein Speicher, kein Zustand.

Zwei Quellen, beide muessen billig sein:
1. SHQueryUserNotificationState: Windows meldet selbst, wenn eine
   Direct3D-App exklusiv im Vollbild laeuft (klassische Spiele) oder eine
   Vollbild-Praesentation aktiv ist.
2. Geometrie: das Vordergrundfenster bedeckt den kompletten Monitor
   (randlose "Borderless Windowed"-Spiele, F11-Vollbild im Browser,
   Vollbild-Video). Ein MAXIMIERTES normales Fenster mit Titelleiste
   zaehlt nicht - es endet an der Taskleiste und traegt WS_CAPTION.
   Der Desktop selbst (Progman/WorkerW) bedeckt den Monitor ebenfalls
   und wird ausgenommen.
"""

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger("localflow.fullscreen")

# SHQueryUserNotificationState - QUERY_USER_NOTIFICATION_STATE
QUNS_BUSY = 2                     # Vollbild-Praesentation o.ae.
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # exklusives D3D-Vollbild (Spiele)
QUNS_PRESENTATION_MODE = 4
_FULLSCREEN_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
MONITOR_DEFAULTTONEAREST = 2
_DESKTOP_CLASSES = {"Progman", "WorkerW"}


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


_user32 = ctypes.windll.user32
# Signaturen EINMAL setzen (64-bit: HMONITOR ist ein Zeiger, kein int).
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.MonitorFromWindow.restype = ctypes.c_void_p
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.IsZoomed.argtypes = [wintypes.HWND]


def covers_monitor(win: tuple[int, int, int, int],
                   mon: tuple[int, int, int, int]) -> bool:
    """Bedeckt das Fensterrechteck (l, t, r, b) den Monitor vollstaendig?
    Pure Funktion, testbar. Randlose Vollbildfenster sind exakt so gross
    wie der Monitor; ein paar Pixel Ueberhang (unsichtbare Rahmen) sind ok."""
    wl, wt, wr, wb = win
    ml, mt, mr, mb = mon
    if mr <= ml or mb <= mt:
        return False
    return wl <= ml and wt <= mt and wr >= mr and wb >= mb


def classify(covers: bool, has_caption: bool, is_zoomed: bool,
             class_name: str, own_process: bool) -> bool:
    """Geometrie-Entscheidung als pure Funktion (testbar):
    Vollbild = bedeckt den Monitor UND ist kein Desktop, kein eigenes
    Fenster (Overlay-Pille) und kein maximiertes Fenster mit Titelleiste."""
    if not covers or own_process or class_name in _DESKTOP_CLASSES:
        return False
    if has_caption and is_zoomed:
        return False
    return True


def _query_notification_state() -> int | None:
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value
    except Exception:  # noqa: BLE001 - nur ein Hinweis, Geometrie prueft weiter
        log.debug("SHQueryUserNotificationState fehlgeschlagen", exc_info=True)
    return None


def is_fullscreen_app_active(hwnd: int | None = None,
                             own_pid: int | None = None) -> bool:
    """True, wenn (bei hwnd=None) das Vordergrundfenster eine Vollbild-App
    ist. hwnd/own_pid nur fuer Tests - mit hwnd entfaellt die D3D-Abfrage.

    Laeuft im Low-Level-Maus-Hook-Thread: alle Aufrufe hier lesen nur
    Fensterdaten aus dem Kernel (kein SendMessage an den fremden Thread -
    GetWindowText o.ae. waere tabu, das koennte am Zielfenster haengen)."""
    if hwnd is None:
        if _query_notification_state() in _FULLSCREEN_STATES:
            return True
        hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    try:
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        mon = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not mon:
            return False
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        covers = covers_monitor((rect.left, rect.top, rect.right, rect.bottom),
                                (m.left, m.top, m.right, m.bottom))
        if not covers:
            return False  # haeufigster Fall - Rest gar nicht erst abfragen
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, buf, 64)
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
        return classify(covers=True,
                        has_caption=bool(style & WS_CAPTION),
                        is_zoomed=bool(_user32.IsZoomed(hwnd)),
                        class_name=buf.value,
                        own_process=pid.value == (own_pid if own_pid is not None
                                                  else os.getpid()))
    except Exception:  # noqa: BLE001 - Erkennung darf den Hotkey nie blockieren
        log.debug("Vollbild-Erkennung fehlgeschlagen", exc_info=True)
        return False
