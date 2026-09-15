"""Flow-Bar: kleine Pill am unteren Bildschirmrand, monochrom, als Win32
Layered Window mit Per-Pixel-Alpha (UpdateLayeredWindow) und PIL-Renderer.

Warum kein Tk mehr: Tk-Canvas kennt weder Kantenglaettung noch Alpha (Fake-
Alpha ueber Farb-Mix, harte Pixelkanten, ~43 fps mit Jitter). Hier wird jeder
Frame mit 3-fachem Supersampling in ein RGBA-Bild gezeichnet (geglaettete
Stadion-Kanten, echte Transparenz, weicher Schatten, FreeType-Text) und per
UpdateLayeredWindow auf den Schirm geschoben. Gemessen: 60 fps stabil,
3-5 ms pro Frame, ~20 % eines Kerns (Tk: 32 %).

- Aufnahme: EIN Ring aus fuenf kreisenden Punkten, mittig in einer kompakten
  Pille; die Punkte atmen mit dem Mikrofonpegel. Kommt Live-Text, wandert der
  Ring nach links und die Pille waechst mit dem Text (keine Waveform mehr).
- Kurzer Tipp (Modus "both"): Ringbogen um den Orb waechst auf ein Viertel
  (Antizipation); der zweite Tipp schliesst ihn mit Ueberschwingen zum Ring.
- Freisprechen: Ring um den Orb.
- Verarbeitung: "working"-Orb, waechst aus der Pillenmitte.
- Eingefuegt: Haken, dann geht die Pille wie gekommen nach unten.
- Alle Uebergaenge sind Federn (overlay_model.Spring): Zielwechsel behalten
  die Geschwindigkeit; Inhalte crossfaden wirklich (echtes Alpha).
- Fenster hat FESTE Groesse (max. ausgeklappte Pille), wird beim Einblenden
  einmal auf den Monitor des fokussierten Fensters gesetzt (physische Pixel,
  Pille skaliert mit der Monitor-DPI) und ist click-through + topmost.
- Reduced Motion: Crossfade statt Slide, kein Bounce, Orbs als Standbild.

Zeichnerische Konventionen: alle Geometrie in "logischen" Pixeln (wie im
AppKit-Port), der Painter multipliziert mit k = DPI-Skalierung x SS.
"""

import collections
import ctypes
import logging
import math
import os
import queue
import threading
import time
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .overlay_model import (
    ARC_TAP, BOTTOM_MARGIN, CHECK_S,
    EXPAND_MAX_LINES, EXPAND_VPAD, FONT_SIZE, H, HOLD_EXPAND_S, LEAN_SCALE,
    MATERIALIZE_FROM, MAX_TEXT_PX,
    MIN_VISIBLE_S, MORPH_S, N_BARS, ORB_GROW_S, ORB_LISTEN_SIZE,
    ORB_LISTENING, ORB_ONLY_W, ORB_PRESET, ORB_PROCESSING, ORB_SIZE, PAD_BOTTOM, PAD_R,
    PAD_TOP, PILL_ALPHA, POSITIONS, REDUCED_FADE_S, RING_BOUNCE, SIDE_PAD, SLIDE_PX,
    SPRING_ALPHA, SPRING_LEAN,
    SPRING_ARC, SPRING_EXPAND, SPRING_HIDE, SPRING_RING, SPRING_SHOW,
    SPRING_WIDTH, TEXT_STATES, THEMES, WAVE_DT, WAVE_LEFT, WAVE_STATES,
    Spring, Tween, check_path, clamp, ease_out, fit_text_tail, orb_dots,
    smooth, wrap_text,
)

log = logging.getLogger("localflow.overlay")

SS = 3                      # Supersampling-Faktor des Renderers
FRAME_S = 1 / 60            # Ziel-Takt sichtbar
IDLE_S = 0.03               # Takt unsichtbar (nur Queue + Messages)
SHADOW = ()                 # bewusst kein Schatten: clean, wie Apples Status-Pille

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

_IVDM_CLASS = None  # lazy definiertes comtypes-Interface (einmal pro Prozess)


def _vdm():
    """IVirtualDesktopManager-Instanz (dokumentierte Shell-COM-API)."""
    global _IVDM_CLASS
    import comtypes
    from ctypes import HRESULT, POINTER
    from ctypes.wintypes import BOOL, HWND
    from comtypes import COMMETHOD, GUID, IUnknown

    if _IVDM_CLASS is None:
        class IVirtualDesktopManager(IUnknown):
            _iid_ = GUID("{a5cd92ff-29be-454c-8d04-d82879fb3f1b}")
            _methods_ = [
                COMMETHOD([], HRESULT, "IsWindowOnCurrentVirtualDesktop",
                          (["in"], HWND, "topLevelWindow"),
                          (["out"], POINTER(BOOL), "onCurrentDesktop")),
                COMMETHOD([], HRESULT, "GetWindowDesktopId",
                          (["in"], HWND, "topLevelWindow"),
                          (["out"], POINTER(GUID), "desktopId")),
                COMMETHOD([], HRESULT, "MoveWindowToDesktop",
                          (["in"], HWND, "topLevelWindow"),
                          (["in"], POINTER(GUID), "desktopId")),
            ]
        _IVDM_CLASS = IVirtualDesktopManager

    comtypes.CoInitialize()  # idempotent pro Thread
    return comtypes.CoCreateInstance(
        GUID("{aa509086-5ca9-4c25-8f95-589d3c07b48a}"), interface=_IVDM_CLASS)


def _ensure_on_current_desktop(hwnd):
    """Virtuelle Desktops: eine Topmost-Pill "klebt" auf dem Desktop, auf dem
    sie erzeugt wurde - beim Einblenden notfalls auf den Desktop des gerade
    fokussierten Fensters umziehen (Feldbefund 2026-07-14). Best-Effort."""
    if not hwnd:
        return
    try:
        vdm = _vdm()
        if vdm.IsWindowOnCurrentVirtualDesktop(hwnd):
            return
        fg = user32.GetForegroundWindow()
        if not fg:
            return
        vdm.MoveWindowToDesktop(hwnd, vdm.GetWindowDesktopId(fg))
        log.info("Pill war auf einem anderen virtuellen Desktop - auf den "
                 "aktuellen verschoben")
    except Exception:  # noqa: BLE001
        log.debug("Virtual-Desktop-Pruefung fehlgeschlagen", exc_info=True)


def _assert_topmost(hwnd):
    """Topmost real durchsetzen: Windows wirft Fenster gelegentlich aus dem
    Topmost-Band (Vollbild-/Video-Apps), das Style-Bit bleibt stehen
    (Feldbefund 2026-07-14). Bei jedem Einblenden + periodisch."""
    if not hwnd:
        return
    try:
        # HWND_TOPMOST=-1 als echter Pointer; SWP_NOSIZE|NOMOVE|NOACTIVATE|NOOWNERZORDER
        user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0213)
    except Exception:  # noqa: BLE001
        log.debug("Topmost-Nachdruck fehlgeschlagen", exc_info=True)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _active_monitor_work_area() -> tuple[int, int, int, int, float]:
    """Arbeitsflaeche (physische Pixel) + DPI-Skalierung des Monitors mit dem
    fokussierten Fenster (Multi-Monitor: die Pill erscheint dort, wo
    diktiert wird)."""
    try:
        hwnd = user32.GetForegroundWindow()
        hmon = user32.MonitorFromWindow(hwnd, 1)  # MONITOR_DEFAULTTOPRIMARY
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcWork
            scale = 1.0
            try:
                dx, dy = wintypes.UINT(), wintypes.UINT()
                if ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx),
                                                         ctypes.byref(dy)) == 0:
                    scale = max(0.5, dx.value / 96.0)
            except Exception:  # noqa: BLE001
                pass
            if r.right - r.left >= 200 and r.bottom - r.top >= 200:
                return r.left, r.top, r.right, r.bottom, scale
    except Exception:  # noqa: BLE001
        pass
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1), 1.0


# ---------------------------------------------------------------- Fonts

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _font_file(family: str, weight: str = "semibold") -> str:
    """Schriftdatei zu einer Familie ueber die Windows-Font-Registry
    (HKLM + HKCU). weight: "semibold" (bevorzugt), "bold", "regular"."""
    import winreg
    fam = (family or "Segoe UI").strip().lower()
    entries = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(key, i)
                i += 1
            except OSError:
                break
            if isinstance(val, str) and name.lower().startswith(fam):
                entries.append((name.lower()[len(fam):].strip(), val))

    def rank(rest: str) -> int:
        if "italic" in rest or "light" in rest or "black" in rest:
            return 9
        semibold = "semibold" in rest
        bold = "bold" in rest and not semibold
        regular = rest.startswith("(") or rest == ""
        order = {"semibold": (semibold, bold, regular), "bold": (bold, semibold, regular),
                 "regular": (regular, semibold, bold)}[weight]
        for i, hit in enumerate(order):
            if hit:
                return i
        return 8
    if entries:
        rest, val = min(entries, key=lambda e: rank(e[0]))
        path = val if os.path.isabs(val) else os.path.join(_FONT_DIR, val)
        if os.path.exists(path):
            return path
    for fb in ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        p = os.path.join(_FONT_DIR, fb)
        if os.path.exists(p):
            return p
    raise OSError("keine Schriftdatei gefunden")


class _Fonts:
    """Schriften in Render-Aufloesung (k = Skalierung x SS); measure() liefert
    logische Pixel, damit die Layout-Logik plattformneutral bleibt."""

    def __init__(self, family: str, size: int, k: float):
        self.family, self.size, self.k = family, size, k
        path = _font_file(family)
        self.font = ImageFont.truetype(path, max(4, int(round(size * k))))
        self.badge = ImageFont.truetype(path, max(4, int(round(max(6, size - 3) * k))))
        asc, desc = self.font.getmetrics()
        self.line_h = (asc + desc) / k + 3
        self._cache: dict = {}

    def measure(self, s: str) -> float:
        v = self._cache.get(s)
        if v is None:
            if len(self._cache) > 4096:
                self._cache.clear()
            v = self.font.getlength(s) / self.k
            self._cache[s] = v
        return v

    def badge_measure(self, s: str) -> float:
        return self.badge.getlength(s) / self.k


# ---------------------------------------------------------------- Win32 Layered Window

WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x80
WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x8000000, 0x8
WS_POPUP = 0x80000000
ULW_ALPHA = 2
AC_SRC_OVER, AC_SRC_ALPHA = 0, 1
WM_CLOSE, WM_DESTROY, WM_QUIT = 0x0010, 0x0002, 0x0012


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                       ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                       ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.CreateCompatibleDC.restype = wintypes.HDC

_CLASS_NAME = "LocalFlowPill"
_class_registered = False


@_WNDPROC
def _wndproc(hwnd, msg, wp, lp):
    if msg == WM_CLOSE:
        user32.DestroyWindow(hwnd)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


class _LayeredWindow:
    """Click-through Topmost-Fenster mit Per-Pixel-Alpha-Oberflaeche."""

    def __init__(self, w: int, h: int):
        global _class_registered
        hinst = kernel32.GetModuleHandleW(None)
        if not _class_registered:
            wc = _WNDCLASSW()
            wc.lpfnWndProc = _wndproc
            wc.hInstance = hinst
            wc.lpszClassName = _CLASS_NAME
            if not user32.RegisterClassW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err not in (0, 1410):  # ERROR_CLASS_ALREADY_EXISTS
                    raise OSError(f"RegisterClassW fehlgeschlagen: {err}")
            _class_registered = True
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        self.hwnd = user32.CreateWindowExW(ex, _CLASS_NAME, "LocalFlow", WS_POPUP,
                                           0, 0, w, h, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW fehlgeschlagen: {ctypes.get_last_error()}")
        self.w = self.h = 0
        self.hdc = gdi32.CreateCompatibleDC(None)
        self.hbm = None
        self.bits = ctypes.c_void_p()
        self.resize(w, h)
        self._msg = wintypes.MSG()
        self.alive = True
        user32.ShowWindow(self.hwnd, 8)  # SW_SHOWNA: sichtbar, ohne Fokus (Inhalt ist leer/transparent)

    def resize(self, w: int, h: int):
        if (w, h) == (self.w, self.h):
            return
        if self.hbm:
            gdi32.DeleteObject(self.hbm)
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        self.hbm = gdi32.CreateDIBSection(self.hdc, ctypes.byref(bmi), 0,
                                          ctypes.byref(self.bits), None, 0)
        if not self.hbm or not self.bits.value:
            raise OSError("CreateDIBSection fehlgeschlagen")
        gdi32.SelectObject(self.hdc, self.hbm)
        self.w, self.h = w, h
        self._size = wintypes.SIZE(w, h)
        self._src = wintypes.POINT(0, 0)
        self._blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        # Direkter Blick auf die DIB-Bits (BGRA, top-down): Frames werden
        # ohne Zwischenpuffer hineingeschrieben.
        buf_t = ctypes.c_uint8 * (w * h * 4)
        self.dib = np.ctypeslib.as_array(buf_t.from_address(self.bits.value)).reshape(h, w, 4)
        self._dirty = None  # (x0, y0, x1, y1) der zuletzt beschriebenen Region
        self.clear()

    def move(self, x: int, y: int):
        # SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE
        user32.SetWindowPos(self.hwnd, None, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)

    def present(self, region: Image.Image, x: int, y: int, constant_alpha: float = 1.0) -> bool:
        """Teilbild (Pillenregion, Kanaele bereits in BGR-Reihenfolge) an
        (x, y) in die DIB schreiben und anzeigen. Premultiply macht PIL in C
        ("RGBa"); der Rest des Fensters bleibt transparent, die vorige
        Region wird geloescht. Praesenz laeuft ueber SourceConstantAlpha."""
        rw, rh = region.size
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + rw), min(self.h, y + rh)
        if self._dirty is not None:
            dx0, dy0, dx1, dy1 = self._dirty
            self.dib[dy0:dy1, dx0:dx1] = 0
        if x1 > x0 and y1 > y0:
            raw = np.frombuffer(region.convert("RGBa").tobytes(), dtype=np.uint8).reshape(rh, rw, 4)
            self.dib[y0:y1, x0:x1] = raw[y0 - y:y1 - y, x0 - x:x1 - x]
            self._dirty = (x0, y0, x1, y1)
        else:
            self._dirty = None
        self._blend.SourceConstantAlpha = int(round(255 * clamp(constant_alpha)))
        return bool(user32.UpdateLayeredWindow(self.hwnd, None, None, ctypes.byref(self._size),
                                               self.hdc, ctypes.byref(self._src), 0,
                                               ctypes.byref(self._blend), ULW_ALPHA))

    def clear(self):
        self.dib[:] = 0
        self._dirty = None
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 0, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, None, None, ctypes.byref(self._size), self.hdc,
                                   ctypes.byref(self._src), 0, ctypes.byref(blend), ULW_ALPHA)

    def pump(self) -> bool:
        """Nachrichten abarbeiten; False, sobald das Fenster zerstoert wurde
        (WM_CLOSE von aussen, Session-Events) - der Watchdog startet dann neu."""
        m = self._msg
        while user32.PeekMessageW(ctypes.byref(m), None, 0, 0, 1):
            if m.message == WM_QUIT:
                self.alive = False
                return False
            user32.TranslateMessage(ctypes.byref(m))
            user32.DispatchMessageW(ctypes.byref(m))
        if not user32.IsWindow(self.hwnd):
            self.alive = False
            return False
        return True

    def destroy(self):
        try:
            if self.hbm:
                gdi32.DeleteObject(self.hbm)
            if self.hdc:
                gdi32.DeleteDC(self.hdc)
            if user32.IsWindow(self.hwnd):
                user32.DestroyWindow(self.hwnd)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- Pille (Logik + Painter)

def _rgb(hexcol: str) -> tuple[int, int, int]:
    """Farbe in DIB-Kanalreihenfolge (B, G, R): der Painter zeichnet direkt
    so, wie die Layered-Window-Bitmap die Bytes erwartet - kein Umsortieren
    pro Frame. Fuer Vorschau-PNGs dreht render_full() die Kanaele zurueck."""
    return int(hexcol[5:7], 16), int(hexcol[3:5], 16), int(hexcol[1:3], 16)


class _OffsetDraw:
    """ImageDraw-Proxy, der alle Koordinaten um den Ursprung des gerade
    gerenderten Teilbereichs verschiebt. Der Painter rechnet weiter in
    absoluten Fenster-Koordinaten (x k), gezeichnet wird aber nur die
    Pillenregion - bei eingeklappter Pille ein Bruchteil des Fensters."""

    def __init__(self, draw, dx: float, dy: float):
        self._d, self.dx, self.dy = draw, dx, dy

    def _sh(self, xy):
        dx, dy = self.dx, self.dy
        return [v - (dx if i % 2 == 0 else dy) for i, v in enumerate(xy)]

    def rounded_rectangle(self, xy, **kw):
        self._d.rounded_rectangle(self._sh(xy), **kw)

    def rectangle(self, xy, **kw):
        self._d.rectangle(self._sh(xy), **kw)

    def ellipse(self, xy, **kw):
        self._d.ellipse(self._sh(xy), **kw)

    def arc(self, xy, **kw):
        self._d.arc(self._sh(xy), **kw)

    def line(self, xy, **kw):
        self._d.line(self._sh(xy), **kw)

    def text(self, xy, *a, **kw):
        self._d.text((xy[0] - self.dx, xy[1] - self.dy), *a, **kw)

    def gradient_pill(self, xy, radius, top, bottom):
        """Vertikaler Verlauf (RGBA oben -> RGBA unten) durch eine Stadion-
        Maske: die Pille laeuft nach unten ins Transparente aus."""
        x0, y0, x1, y1 = self._sh(xy)
        img = self._d._image
        W, Hh = img.size
        ya, yb = max(0, int(math.floor(y0))), min(Hh, int(math.ceil(y1)) + 1)
        xa, xb = max(0, int(math.floor(x0))), min(W, int(math.ceil(x1)) + 1)
        if yb <= ya or xb <= xa:
            return
        ys = np.arange(ya, yb, dtype=np.float32)
        t = np.clip((ys - y0) / max(1.0, y1 - y0), 0.0, 1.0)[:, None]
        top_a, bot_a = np.array(top, dtype=np.float32), np.array(bottom, dtype=np.float32)
        rows = top_a[None, :] * (1 - t) + bot_a[None, :] * t          # (h, 4)
        block = np.repeat(rows[:, None, :], xb - xa, axis=1)          # (h, w, 4)
        grad = Image.fromarray(np.ascontiguousarray(block.astype(np.uint8)), "RGBA")
        mask = Image.new("L", (xb - xa, yb - ya), 0)
        ImageDraw.Draw(mask).rounded_rectangle([x0 - xa, y0 - ya, x1 - xa, y1 - ya],
                                               radius=radius, fill=255)
        img.paste(grad, (xa, ya), mask)


class _Pill:
    """Zustandsmaschine, Federn und Painter der Pille - fensterunabhaengig,
    damit sich Frames auch ohne Fenster rendern lassen (Tests, Vorschau)."""

    def __init__(self, family: str = "Segoe UI", size: int = FONT_SIZE, scale: float = 1.0):
        self.scale = scale
        self.k = scale * SS
        self.fonts = _Fonts(family, size, self.k)
        self.st = {
            "target": "hidden", "vis": "recording", "prev": None,
            "level": 0.0, "smooth": 0.0, "text": "", "shown": False,
            "shown_at": 0.0, "state_t0": 0.0, "wave_acc": 0.0, "scroll": 0.0,
            "glass": False, "source": "pc", "col": THEMES["dark"],
            "reduced": False, "showing": None, "hover": False,
            "held_since": None,   # Hotkey gehalten seit (Bubble nach HOLD_EXPAND_S)
            "error": "",          # Fehlergrund fuer den error-Zustand
            "position": POSITIONS[0],  # unten-Mitte (Einstellung overlay_position)
            "margin": float(BOTTOM_MARGIN),  # Abstand zum Arbeitsflaechen-Rand (logisch)
        }
        self.width = Spring(self.content_width("recording"), *SPRING_WIDTH)
        self.expand = Spring(0.0, *SPRING_EXPAND)
        self.fade = Tween(1.0, lambda p: p)
        self.ring = Spring(0.0, *SPRING_RING)
        self.arc = Spring(0.0, *SPRING_ARC)
        self.check = Tween(0.0, ease_out)
        self.slide = Spring(1.0, *SPRING_SHOW)
        self.alpha = Spring(0.0, *SPRING_ALPHA)
        self.lean = Spring(1.0, *SPRING_LEAN)    # 1.0 normal, LEAN_SCALE im Tipp-Fenster
        self.wave = collections.deque([0.0] * N_BARS, maxlen=N_BARS)
        self._wrap_cache: dict = {}
        self.pill_rect = None  # (px, py, w, ph) logisch, letzter Frame
        self.recompute_size()

    # ---- Layout -------------------------------------------------------------

    def recompute_size(self):
        f = self.fonts
        base_w = max(self.content_width(s) for s in WAVE_STATES + ("processing",) + TEXT_STATES)
        self.max_w = int(max(base_w, WAVE_LEFT + MAX_TEXT_PX + PAD_R)) + 8 + int(f.badge_measure("iPad") + 18)
        # Fenster nur so hoch wie die maximal ausgeklappte Pille bei der
        # AKTUELLEN Schrift (bei Schriftwechsel wird das Fenster neu erzeugt)
        expand_max_h = 2 * EXPAND_VPAD + EXPAND_MAX_LINES * math.ceil(f.line_h) + 20
        self.win_h = int(max(PAD_TOP + H, expand_max_h) + SLIDE_PX + PAD_BOTTOM + 6)
        self._wrap_cache.clear()

    def set_font(self, family: str | None, size: int | None):
        fam = family or self.fonts.family
        sz = max(12, min(32, int(size))) if size else self.fonts.size
        self.fonts = _Fonts(fam, sz, self.k)
        self.recompute_size()

    def set_scale(self, scale: float):
        if abs(scale - self.scale) < 1e-3:
            return
        self.scale = scale
        self.k = scale * SS
        self.fonts = _Fonts(self.fonts.family, self.fonts.size, self.k)
        self.recompute_size()

    def badge_w(self) -> float:
        if self.st["source"] != "ipad":
            return 0.0
        return self.fonts.badge_measure("iPad") + 12 + 6

    def content_width(self, state: str) -> float:
        m = self.fonts.measure
        st = self.st
        if state in WAVE_STATES:
            if st["text"]:
                tw = min(m(st["text"]) + 6, MAX_TEXT_PX)
                return WAVE_LEFT + tw + self.badge_w() + PAD_R
            return ORB_ONLY_W + self.badge_w()
        if state in ("processing", "done"):
            return 64
        if state == "loading":
            return 14 + 12 + 8 + m("Lade Modelle …") + 14
        if state == "clipboard":
            return 14 + 14 + 8 + m("In der Zwischenablage · Strg+V") + 14
        if state == "error":
            return 14 + 7 + 8 + m(self.error_text()) + 14
        return 100

    def anchor(self) -> tuple[str, str]:
        """("bottom"|"top", "center"|"left"|"right") aus der Position."""
        pos = self.st.get("position") or POSITIONS[0]
        vert, _, horiz = pos.partition("-")
        return ("top" if vert == "top" else "bottom",
                horiz if horiz in ("left", "right") else "center")

    def error_text(self) -> str:
        reason = (self.st.get("error") or "").strip()
        return f"Fehler · {reason}" if reason else "Fehler"

    def wrap(self, text: str, zone: float) -> list[str]:
        key = (text, round(zone / 2) * 2)
        v = self._wrap_cache.get(key)
        if v is None:
            if len(self._wrap_cache) > 256:
                self._wrap_cache.clear()
            v = wrap_text(text, key[1], self.fonts.measure)
            self._wrap_cache[key] = v
        return v

    # ---- Zustand ------------------------------------------------------------

    def apply_state(self, new: str, now: float) -> bool:
        """True, wenn die Pille dadurch FRISCH eingeblendet wird (der Aufrufer
        positioniert dann das Fenster)."""
        st = self.st
        if new == st["target"]:
            return False
        st["target"] = new
        if new in ("hidden", None):
            return False
        old = st["vis"]
        if not st["shown"]:
            st["vis"], st["prev"] = new, None
            st["text"] = ""
            st["state_t0"] = st["shown_at"] = now
            st["shown"] = True
            st["showing"] = None
            self.width.snap(self.content_width(new))
            self.fade.snap(1.0)
            self.ring.snap(1.0 if new == "locked" else 0.0)
            self.arc.snap(ARC_TAP if new == "armed" else 0.0)
            self.check.snap(1.0 if new == "done" else 0.0)
            self.slide.snap(0.0 if st["reduced"] else 1.0)
            self.expand.snap(0.0)
            self.lean.snap(1.0)
            self.wave.extend([0.0] * N_BARS)
            st["smooth"] = 0.0
            return True
        if new == old:
            return False
        if new in WAVE_STATES and old not in WAVE_STATES:
            st["text"] = ""
        st["vis"] = new
        self.width.to(self.content_width(new))
        if {old, new} <= set(WAVE_STATES):
            bounce = new == "locked" and not st["reduced"]
            self.ring.tune(SPRING_RING[0], RING_BOUNCE if bounce else SPRING_RING[1])
            self.ring.to(1.0 if new == "locked" else 0.0)
            self.arc.to(ARC_TAP if new == "armed" else 0.0)
            # Tipp-Fenster: Pille lehnt sich minimal zurueck (Antizipation)
            self.lean.to(LEAN_SCALE if new == "armed" and not st["reduced"] else 1.0)
        else:
            st["prev"] = old
            st["state_t0"] = now
            self.fade.snap(0.0)
            self.fade.to(1.0, MORPH_S, now)
            self.ring.snap(1.0 if new == "locked" else 0.0)
            self.arc.snap(0.0)
            self.lean.to(1.0)
            if new == "done":
                self.check.snap(0.0)
                self.check.to(1.0, CHECK_S, now + MORPH_S * 0.5)
        return False

    def tick(self, now: float, dt: float) -> bool:
        """Federn/Pegel fortschreiben. True = Pille ist praesent (zeichnen)."""
        st = self.st
        want = st["target"] not in ("hidden", None)
        hold = st["shown"] and (now - st["shown_at"]) < MIN_VISIBLE_S
        showing = bool(want or hold)
        if showing != st["showing"]:
            st["showing"] = showing
            self.slide.tune(*(SPRING_SHOW if showing else SPRING_HIDE))
            self.alpha.tune(*((REDUCED_FADE_S, 1.0) if st["reduced"] else SPRING_ALPHA))
        self.alpha.to(1.0 if showing else 0.0)
        if st["reduced"]:
            self.slide.snap(0.0)
        else:
            self.slide.to(0.0 if showing else 1.0)
        self.alpha.update(dt)
        self.slide.update(dt)
        present = st["shown"] and (self.alpha.v > 0.003 or self.alpha.target > 0.0)
        if not present:
            if st["shown"]:
                st["shown"] = False
                st["prev"] = None
                self.fade.snap(1.0)
                self.pill_rect = None
            return False

        target = st["level"] if (st["vis"] in WAVE_STATES and want) else 0.0
        tau = 0.035 if target > st["smooth"] else 0.09
        st["smooth"] += (target - st["smooth"]) * (1 - math.exp(-dt / tau))
        st["wave_acc"] += dt
        while st["wave_acc"] >= WAVE_DT:
            st["wave_acc"] -= WAVE_DT
            self.wave.append(st["smooth"] if st["vis"] in WAVE_STATES else 0.0)
        st["scroll"] = st["wave_acc"] / WAVE_DT
        if st["vis"] not in WAVE_STATES:
            k = math.exp(-dt / 0.055)
            for i in range(len(self.wave)):
                self.wave[i] *= k

        held_long = st["held_since"] is not None and (now - st["held_since"]) >= HOLD_EXPAND_S
        hovering = ((st["hover"] or held_long) and st["vis"] in WAVE_STATES and bool(st["text"])
                    and len(self.wrap(st["text"], MAX_TEXT_PX)) > 1)
        self.expand.to(1.0 if hovering else 0.0)
        self.expand.update(dt)
        if st["vis"] in WAVE_STATES:
            cw = self.content_width(st["vis"])
            fw = WAVE_LEFT + MAX_TEXT_PX + PAD_R
            self.width.to(cw + (fw - cw) * self.expand.v)
        self.width.update(dt)
        self.ring.update(dt)
        self.arc.update(dt)
        self.lean.update(dt)
        self.check.update(now)
        if self.fade.update(now) >= 1.0:
            st["prev"] = None
        return True

    # ---- Painter -------------------------------------------------------------

    def render_full(self, now: float) -> Image.Image:
        """Vorschau/Tests: kompletter Frame in Fenstergroesse als echtes RGBA."""
        region, x, y = self.render(now)
        s = self.scale
        img = Image.new("RGBA", (int(round(self.max_w * s)), int(round(self.win_h * s))), (0, 0, 0, 0))
        b, g, r, a = region.split()
        img.paste(Image.merge("RGBA", (r, g, b, a)), (x, y))
        return img

    def render(self, now: float) -> tuple[Image.Image, int, int]:
        """Pillenregion (1x, Kanaele B,G,R,A) plus Offset im Fenster."""
        st = self.st
        k = self.k
        W, Hc = self.max_w, self.win_h
        w = self.width.v
        vert, horiz = self.anchor()
        if horiz == "left":
            px = float(SIDE_PAD)
        elif horiz == "right":
            px = W - SIDE_PAD - w
        else:
            px = (W - w) / 2
        slide_off = SLIDE_PX * clamp(self.slide.v, -0.25, 1.1)
        ph = float(H)
        if self.expand.v > 0.001 and st["text"]:
            zone = max(20.0, w - WAVE_LEFT - PAD_R - self.badge_w())
            nlines = min(len(self.wrap(st["text"], zone)), EXPAND_MAX_LINES)
            full_h = max(float(H), 2 * EXPAND_VPAD + max(1, nlines) * self.fonts.line_h)
            full_h = min(full_h, float(Hc - PAD_BOTTOM - PAD_TOP - SLIDE_PX - 2))
            ph = H + (full_h - H) * self.expand.v
        if vert == "top":
            # oben verankert: Pille kommt von oben herein, Bubble waechst nach unten
            py = SLIDE_PX + PAD_TOP - slide_off
            pill_bottom = py + ph
        else:
            pill_bottom = (Hc - PAD_BOTTOM) + slide_off
            py = pill_bottom - ph
        # Nur die Pillenregion (+ Schatten) in Supersampling zeichnen, dann
        # ins 1x-Fensterbild setzen - das Fenster ist fuer die ausgeklappte
        # Bubble dimensioniert, die eingeklappte Pille braucht ein Fuenftel.
        m = (SHADOW[-1][0] if SHADOW else 0) + 6
        rx0, ry0 = max(0.0, px - m), max(0.0, py - m)
        rx1, ry1 = min(float(W), px + w + m), min(float(Hc), py + ph + m + 2)
        cw, ch = max(1, int(math.ceil((rx1 - rx0) * k))), max(1, int(math.ceil((ry1 - ry0) * k)))
        region = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = _OffsetDraw(ImageDraw.Draw(region), rx0 * k, ry0 * k)
        self._pill_body(d, px, py, w, ph)
        f = self.fade.v
        a_vis = 1.0
        if st["prev"] is not None:
            a_prev = smooth(1 - f / 0.6)
            self._content(d, st["prev"], a_prev, now, px, py, w, ph)
            a_vis = smooth((f - 0.35) / 0.65)
        if st["vis"] in TEXT_STATES:
            a_vis *= clamp((w - self.content_width(st["vis"]) + 8) / 8)
        self._content(d, st["vis"], a_vis, now, px, py, w, ph)
        self.pill_rect = (px, py, w, ph)
        s = self.scale
        small = region.reduce(SS) if SS > 1 else region
        ox, oy = rx0 * s, ry0 * s
        # Materialisieren + Zuruecklehnen: die fertige Region um die Unterkante
        # der Pille skalieren (Origin = wo sie herkommt). Nur waehrend der
        # Ein-/Ausblendung bzw. im Tipp-Fenster faellt hier ein Resize an.
        mat = 1.0 if st["reduced"] else MATERIALIZE_FROM + (1 - MATERIALIZE_FROM) * clamp(self.alpha.v)
        mat *= self.lean.v
        if mat < 0.999:
            nw, nh = max(1, int(round(small.width * mat))), max(1, int(round(small.height * mat)))
            small = small.resize((nw, nh), Image.LANCZOS)
            cxp = (px + w / 2) * s
            pbp = (py if vert == "top" else pill_bottom) * s  # Origin = Ankerkante
            ox = cxp - (cxp - ox) * mat
            oy = pbp - (pbp - oy) * mat
        return small, int(round(ox)), int(round(oy))

    def _pill_body(self, d, px, py, w, ph):
        k = self.k
        col = self.st["col"]
        top, bottom, border = _rgb(col["bg"]), _rgb(col["bg2"]), _rgb(col["border"])
        a_top, a_bot = PILL_ALPHA["glass" if self.st["glass"] else "solid"]
        r = ph / 2 if ph <= H + 0.5 else H / 2
        # weicher Schatten: gestapelte, wachsende Stadien mit fallender Deckkraft
        for spread, a in SHADOW:
            d.rounded_rectangle([(px - spread) * k, (py - spread + 3) * k,
                                 (px + w + spread) * k, (py + ph + spread + 3) * k],
                                radius=(r + spread) * k, fill=(0, 0, 0, int(255 * a)))
        # Koerper: Verlauf von bg (oben, deckend) nach bg2 (unten, durchscheinend)
        d.gradient_pill([px * k, py * k, (px + w) * k, (py + ph) * k], r * k,
                        top + (int(255 * a_top),), bottom + (int(255 * a_bot),))
        # feine Haarlinie zur Abgrenzung auf gleichfarbigen Hintergruenden
        d.rounded_rectangle([px * k, py * k, (px + w) * k, (py + ph) * k], radius=r * k,
                            outline=border + (int(255 * a_top * 0.8),), width=max(1, int(round(k))))

    def _content(self, d, state, alpha, now, px, py, w, ph):
        if alpha <= 0.01:
            return
        st, k, f = self.st, self.k, self.fonts
        col = st["col"]
        fg, dim = _rgb(col["fg"]), _rgb(col["dim"])
        A = lambda a: int(round(255 * clamp(a * alpha)))  # noqa: E731
        top_anchor = self.anchor()[0] == "top"
        cy = py + H / 2 if top_anchor else py + ph - H / 2

        def dot(x, y, r, color, a):
            d.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=color + (A(a),))

        def orb(state_name, cx, size, grow, t):
            # Wenige grosse Punkte mit Halo (Apples Status-Pille): erst der
            # weiche Schein, dann der Kern; Tiefe bleibt ueber Groesse/Tinte.
            ox, oy = cx - size / 2, cy - size / 2
            for x, y, rr, white, a in orb_dots(state_name, t, size, grow, preset=ORB_PRESET):
                dot(ox + x, oy + y, rr, fg, (1 - white) * a)

        if state in WAVE_STATES:
            rp = self.ring.v
            # Ring mittig, solange die Pille schmal ist (kein Text); mit
            # wachsender Breite gleitet er auf die linke Position
            cx_left = px + WAVE_LEFT / 2 - 2
            cx_mid = px + (w - self.badge_w()) / 2
            cx = cx_left + (cx_mid - cx_left) * clamp((ORB_ONLY_W + 36 - w) / 36)
            t_orb = 0.6 if st["reduced"] else now
            # Punkte atmen mit dem Pegel (geglaettet); armed: Ring friert ein
            grow = 1.0 + 0.45 * clamp(st["smooth"])
            orb(ORB_LISTENING, cx, ORB_LISTEN_SIZE, grow,
                st["state_t0"] + 0.6 if state == "armed" else t_orb)
            if rp > 0.01:
                # Ring um den Orb; rp > 1 = Ueberschwingen der Lock-Feder
                rr = ORB_LISTEN_SIZE / 2 + 2.5 + 3.0 * max(0.0, rp - 1.0) + 1.5 * math.sin(math.pi * clamp(rp))
                d.ellipse([(cx - rr) * k, (cy - rr) * k, (cx + rr) * k, (cy + rr) * k],
                          outline=fg + (A(clamp(rp)),), width=max(1, int(round(1.6 * k))))
            av = self.arc.v
            if av > 0.01 and rp < 0.5:
                ra = ORB_LISTEN_SIZE / 2 + 3.0
                d.arc([(cx - ra) * k, (cy - ra) * k, (cx + ra) * k, (cy + ra) * k],
                      start=-90, end=-90 + 360 * clamp(av), fill=fg + (A(0.85),),
                      width=max(1, int(round(1.4 * k))))
            bw_badge = self.badge_w()
            zone = max(6.0, w - WAVE_LEFT - PAD_R - bw_badge)
            x0 = px + WAVE_LEFT
            if bw_badge > 0:
                tw = f.badge_measure("iPad")
                bx1 = px + w - PAD_R + 4
                bx0 = bx1 - tw - 12
                d.rounded_rectangle([bx0 * k, (cy - 10) * k, bx1 * k, (cy + 10) * k], radius=4 * k,
                                    outline=fg + (A(0.55),), width=max(1, int(round(k))))
                d.text(((bx0 + bx1) / 2 * k, cy * k), "iPad", font=f.badge, fill=fg + (A(0.7),), anchor="mm")
            text_gate = clamp((w - (WAVE_LEFT + PAD_R + 24)) / 24)
            if text_gate <= 0.01:
                return
            alpha *= text_gate
            A = lambda a: int(round(255 * clamp(a * alpha)))  # noqa: E731
            if st["text"] and ph > H + 1.0:
                lines = self.wrap(st["text"], zone)
                maxn = max(1, int((ph - 2 * EXPAND_VPAD) / f.line_h))
                # unten verankert: neueste Zeile unten neben dem Ring, aeltere
                # darueber; oben verankert: Zeilen laufen nach unten weiter
                shown = lines[-maxn:] if top_anchor else list(reversed(lines[-maxn:]))
                ex = self.expand.v
                for i, ln in enumerate(shown):
                    la = 1.0 if i == 0 else smooth((ex - i * 0.06) / 0.5)
                    yy = cy + i * f.line_h if top_anchor else cy - i * f.line_h
                    d.text((x0 * k, yy * k), ln, font=f.font,
                           fill=fg + (A(0.94 * la),), anchor="lm")
            elif st["text"]:
                d.text((x0 * k, cy * k), fit_text_tail(st["text"], zone, f.measure),
                       font=f.font, fill=fg + (A(0.94),), anchor="lm")
        elif state == "processing":
            grow = 1.0 if st["reduced"] else smooth((now - st["state_t0"]) / ORB_GROW_S)
            orb(ORB_PROCESSING, px + w / 2, ORB_SIZE, grow, 0.6 if st["reduced"] else now)
        elif state == "done":
            pts = check_path(px + w / 2, cy, clamp(self.check.v))
            if pts:
                d.line([(v * k) for v in pts], fill=fg + (A(1.0),), width=max(2, int(round(2 * k))),
                       joint="curve")
                r = max(1.0, k)  # runde Enden
                d.ellipse([pts[0] * k - r, pts[1] * k - r, pts[0] * k + r, pts[1] * k + r], fill=fg + (A(1.0),))
                d.ellipse([pts[-2] * k - r, pts[-1] * k - r, pts[-2] * k + r, pts[-1] * k + r], fill=fg + (A(1.0),))
        elif state == "loading":
            a0 = ((now - st["state_t0"]) * 240) % 360
            d.arc([(px + 14) * k, (cy - 6) * k, (px + 26) * k, (cy + 6) * k], start=a0, end=a0 + 100,
                  fill=dim + (A(1.0),), width=max(1, int(round(2 * k))))
            d.text(((px + 34) * k, cy * k), "Lade Modelle …", font=f.font, fill=dim + (A(1.0),), anchor="lm")
        elif state == "clipboard":
            d.rounded_rectangle([(px + 15) * k, (cy - 6) * k, (px + 25) * k, (cy + 7) * k], radius=1.5 * k,
                                outline=dim + (A(1.0),), width=max(1, int(round(1.4 * k))))
            d.rounded_rectangle([(px + 18) * k, (cy - 8) * k, (px + 22) * k, (cy - 5) * k], radius=k,
                                fill=dim + (A(1.0),))
            d.text(((px + 36) * k, cy * k), "In der Zwischenablage · Strg+V", font=f.font,
                   fill=fg + (A(1.0),), anchor="lm")
        elif state == "error":
            d.ellipse([(px + 14) * k, (cy - 3.5) * k, (px + 21) * k, (cy + 3.5) * k], fill=dim + (A(1.0),))
            d.text(((px + 29) * k, cy * k), self.error_text(), font=f.font, fill=fg + (A(1.0),), anchor="lm")


# ---------------------------------------------------------------- Overlay (Thread + Watchdog)

WATCHDOG_CHECK_S = 5.0     # Pruefintervall
WATCHDOG_MISSES = 2        # so viele stale-Checks in Folge = tot


class Overlay:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._hb = {"t": 0.0, "alpha": 0.0, "vis": "hidden"}  # Herzschlag + Sichtbarkeit (Tests)
        self._hwnd_box = {"hwnd": None}
        self._last = {}            # zuletzt gesetzte Werte (Replay nach Neustart)
        self._gen = 0
        self._thread = None
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        self._launch()
        threading.Thread(target=self._watch, daemon=True,
                         name="localflow-overlay-watchdog").start()

    def _launch(self):
        self._gen += 1
        self._hb = {"t": time.perf_counter(), "alpha": 0.0, "vis": "hidden"}
        self._hwnd_box = {"hwnd": None}
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"localflow-overlay-{self._gen}")
        self._thread.start()

    def _watch(self):
        misses = 0
        while True:
            time.sleep(WATCHDOG_CHECK_S)
            stale = time.perf_counter() - self._hb["t"]
            if stale < WATCHDOG_CHECK_S * 1.5:
                misses = 0
                continue
            misses += 1
            if misses < WATCHDOG_MISSES:
                continue
            misses = 0
            log.warning("Overlay-Thread tot (letzter Tick vor %.0fs) - starte die "
                        "Pill neu", stale)
            self._hide_zombie_window()
            self._queue = queue.Queue()
            self._launch()
            self._replay_settings()

    def _hide_zombie_window(self):
        hwnd = self._hwnd_box.get("hwnd")
        if not hwnd:
            return
        try:
            if user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, 0)  # SW_HIDE
        except Exception:  # noqa: BLE001
            log.debug("Zombie-Fenster verstecken fehlgeschlagen", exc_info=True)

    def _replay_settings(self):
        last = self._last
        for key in ("glass", "source", "style", "theme", "reduced", "position", "margin"):
            if key in last:
                self._queue.put((key, last[key]))
        if last.get("state") not in (None, "hidden"):
            self._queue.put(("state", last["state"]))
            if last.get("text"):
                self._queue.put(("text", last["text"]))

    # ---- oeffentlicher Vertrag (beliebige Threads) ----------------------------

    def set_state(self, state: str):
        if state != self._last.get("state"):
            log.info("Overlay-State: %s -> %s", self._last.get("state", "-"), state)
        self._last["state"] = state
        if state not in WAVE_STATES:
            self._last["text"] = ""
        self._queue.put(("state", state))

    def set_level(self, level: float):
        self._queue.put(("level", level))

    def set_text(self, text: str):
        self._last["text"] = text or ""
        self._queue.put(("text", text or ""))

    def set_source(self, source: str):
        src = "ipad" if source == "ipad" else "pc"
        self._last["source"] = src
        self._queue.put(("source", src))

    def set_glass(self, enabled: bool):
        self._last["glass"] = bool(enabled)
        self._queue.put(("glass", bool(enabled)))

    def set_style(self, font_family: str | None = None, font_size: int | None = None):
        self._last["style"] = (font_family, font_size)
        self._queue.put(("style", (font_family, font_size)))

    def set_theme(self, theme: str):
        self._last["theme"] = theme
        self._queue.put(("theme", theme))

    def set_reduced_motion(self, enabled: bool):
        self._last["reduced"] = bool(enabled)
        self._queue.put(("reduced", bool(enabled)))

    def set_held(self, held: bool):
        """Hotkey wird gerade gehalten (Modus hold/both): nach HOLD_EXPAND_S
        klappt die Bubble mit dem Live-Text auch ohne Maus auf."""
        self._queue.put(("held", bool(held)))

    def set_error(self, reason: str):
        """Kurzer Fehlergrund fuer den error-Zustand ("Kein Mikrofon")."""
        self._queue.put(("error", (reason or "").strip()))

    def set_position(self, position: str):
        """Position auf der Arbeitsflaeche, z.B. "bottom-center", "top-left"."""
        pos = position if position in POSITIONS else POSITIONS[0]
        self._last["position"] = pos
        self._queue.put(("position", pos))

    def set_margin(self, margin_px: float):
        """Abstand der Pille zum Arbeitsflaechen-Rand in logischen Pixeln."""
        try:
            m = max(0.0, min(400.0, float(margin_px)))
        except (TypeError, ValueError):
            m = float(BOTTOM_MARGIN)
        self._last["margin"] = m
        self._queue.put(("margin", m))

    # ---- Render-Thread ---------------------------------------------------------

    def _run(self):
        try:
            self._run_loop()
            log.warning("Overlay-Schleife hat sich beendet (Fenster zerstoert?)")
        except Exception:  # noqa: BLE001
            log.warning("Overlay-Thread gestorben", exc_info=True)

    def _run_loop(self):
        q, hb, hwnd_box = self._queue, self._hb, self._hwnd_box
        pill = _Pill()
        win = _LayeredWindow(int(pill.max_w * pill.scale), int(pill.win_h * pill.scale))
        hwnd_box["hwnd"] = win.hwnd
        last = {"t": time.perf_counter(), "x": None, "y": None, "next": 0.0}
        stats = {"n": 0, "sum": 0.0, "max": 0.0, "t0": time.perf_counter()}
        fine = False
        top_ts = 0.0

        def position_window():
            left, top, right, bottom, scale = _active_monitor_work_area()
            pill.set_scale(scale)
            win.resize(int(round(pill.max_w * scale)), int(round(pill.win_h * scale)))
            vert, horiz = pill.anchor()
            margin = float(pill.st["margin"])
            if horiz == "left":
                x = left + (margin - SIDE_PAD) * scale
            elif horiz == "right":
                x = right - (margin - SIDE_PAD) * scale - win.w
            else:
                x = (left + right) / 2 - win.w / 2
            if vert == "top":
                y = top + (margin - SLIDE_PX - PAD_TOP) * scale
            else:
                y = bottom - (margin - PAD_BOTTOM) * scale - win.h
            x, y = int(round(x)), int(round(y))
            if (x, y) != (last["x"], last["y"]):
                win.move(x, y)
                last["x"], last["y"] = x, y

        try:
            while win.pump():
                now = time.perf_counter()
                dt = min(now - last["t"], 0.1)
                last["t"] = now
                present = False
                try:
                    try:
                        while True:
                            kind, value = q.get_nowait()
                            if kind == "state":
                                if pill.apply_state(value, now):
                                    position_window()
                                    _ensure_on_current_desktop(win.hwnd)
                                    _assert_topmost(win.hwnd)
                                    top_ts = now
                                    if not fine:
                                        try:
                                            ctypes.windll.winmm.timeBeginPeriod(1)
                                        except Exception:  # noqa: BLE001
                                            pass
                                        fine = True
                                    last["t"] = now = time.perf_counter()
                            elif kind == "level":
                                pill.st["level"] = float(value)
                            elif kind == "text":
                                pill.st["text"] = value
                            elif kind == "glass":
                                pill.st["glass"] = bool(value)
                            elif kind == "source":
                                pill.st["source"] = value
                            elif kind == "theme":
                                pill.st["col"] = THEMES.get(value, THEMES["dark"])
                            elif kind == "reduced":
                                pill.st["reduced"] = bool(value)
                                pill.st["showing"] = None
                            elif kind == "held":
                                pill.st["held_since"] = now if value else None
                            elif kind == "error":
                                pill.st["error"] = value
                            elif kind in ("position", "margin"):
                                pill.st[kind] = value
                                if pill.st["shown"]:
                                    last["x"] = None  # live umziehen
                                    position_window()
                            elif kind == "style":
                                try:
                                    pill.set_font(*value)
                                    win.resize(int(round(pill.max_w * pill.scale)),
                                               int(round(pill.win_h * pill.scale)))
                                    last["x"] = None  # Position neu setzen (Groesse geaendert)
                                except Exception:  # noqa: BLE001
                                    log.debug("Schrift-Umstellung fehlgeschlagen", exc_info=True)
                    except queue.Empty:
                        pass

                    # Hover: globale Mausposition gegen das Pill-Rechteck (physisch)
                    hover = False
                    if pill.pill_rect and last["x"] is not None:
                        try:
                            pt = wintypes.POINT()
                            if user32.GetCursorPos(ctypes.byref(pt)):
                                rx, ry, rw, rh = pill.pill_rect
                                s = pill.scale
                                m = 8 * s
                                lft, top_ = last["x"] + rx * s, last["y"] + ry * s
                                hover = (lft - m <= pt.x <= lft + rw * s + m
                                         and top_ - m <= pt.y <= top_ + rh * s + m)
                        except Exception:  # noqa: BLE001
                            hover = False
                    pill.st["hover"] = hover

                    present = pill.tick(now, dt)
                    hb["alpha"] = pill.alpha.v if present else 0.0
                    hb["vis"] = pill.st["vis"] if present else "hidden"
                    if present:
                        if now - top_ts > 2.0:
                            _assert_topmost(win.hwnd)
                            top_ts = now
                        region, rx, ry = pill.render(now)
                        win.present(region, rx, ry, pill.alpha.v)
                        if log.isEnabledFor(logging.DEBUG):
                            stats["n"] += 1
                            stats["sum"] += dt
                            stats["max"] = max(stats["max"], dt)
                            if now - stats["t0"] >= 10.0 and stats["n"]:
                                log.debug("Overlay-Frames: avg=%.1f ms, max=%.1f ms",
                                          stats["sum"] / stats["n"] * 1000, stats["max"] * 1000)
                                stats.update(n=0, sum=0.0, max=0.0, t0=now)
                    elif fine:
                        win.clear()
                        try:
                            ctypes.windll.winmm.timeEndPeriod(1)
                        except Exception:  # noqa: BLE001
                            pass
                        fine = False
                except Exception:  # noqa: BLE001
                    log.debug("Overlay-Tick fehlgeschlagen", exc_info=True)
                finally:
                    hb["t"] = time.perf_counter()
                # Takt: sichtbar feste 60-Hz-Raster (kein Drift durch Render-
                # zeit), unsichtbar Schongang
                if present:
                    t_now = time.perf_counter()
                    if last["next"] < t_now - FRAME_S:
                        last["next"] = t_now  # zu weit hinten: Raster neu setzen
                    last["next"] += FRAME_S
                    rest = last["next"] - t_now
                    if rest > 0.0005:
                        time.sleep(rest)
                else:
                    last["next"] = 0.0
                    time.sleep(IDLE_S)
        finally:
            if fine:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:  # noqa: BLE001
                    pass
            win.destroy()
