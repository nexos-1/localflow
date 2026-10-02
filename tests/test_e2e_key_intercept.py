"""E2E: der echte WH_KEYBOARD_LL-Hook schluckt Enter nur waehrend der Aufnahme.

Braucht eine interaktive Windows-Session (echtes Fenster, Fokus, synthetische
Tasten), laeuft deshalb NICHT in der CI. Das Zielfenster ist ein klassisches
mehrzeiliges EDIT-Control (per WM_GETTEXT auslesbar); jedes durchgelassene
Enter wird dort zu einem Zeilenumbruch, jedes geschluckte nicht.

Prueft am echten System:
  1. Ohne Aufnahme geht Enter unveraendert durch.
  2. Waehrend der Aufnahme wird Enter geschluckt (Down, Auto-Repeat, Up),
     der Callback feuert genau einmal und die Taste "haengt" danach nicht.
  3. Shift+Enter geht auch waehrend der Aufnahme durch.
  4. LocalFlows eigenes Enter (inject.press_keys) wird nie geschluckt.
  5. Escape waehrend der Aufnahme loest den Callback aus.
"""
import ctypes
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import win32con
import win32gui

from localflow import inject
from localflow.hotkey import _KeyHook

WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
VK_RETURN, VK_SHIFT, VK_ESCAPE, VK_A = 0x0D, 0x10, 0x1B, 0x41
KEYUP = 0x0002
user32 = ctypes.windll.user32

box = {}
ready = threading.Event()
stop = threading.Event()
focus_now = threading.Event()


def ui_thread():
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "LocalFlowKeyHookTarget"
    wc.lpfnWndProc = {win32con.WM_DESTROY: lambda *a: win32gui.PostQuitMessage(0) or 0}
    win32gui.RegisterClass(wc)
    top = win32gui.CreateWindow(
        wc.lpszClassName, "LocalFlow Enter-Test",
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        200, 200, 500, 260, 0, 0, 0, None)
    edit = win32gui.CreateWindow(
        "EDIT", "", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
        | win32con.ES_MULTILINE | win32con.ES_WANTRETURN,
        10, 10, 460, 190, top, 0, 0, None)
    box["top"], box["edit"] = top, edit
    ready.set()
    while not stop.is_set():
        win32gui.PumpWaitingMessages()
        if focus_now.is_set():
            win32gui.SetFocus(edit)
            focus_now.clear()
        time.sleep(0.01)
    win32gui.DestroyWindow(top)


def read_text(hwnd):
    n = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, buf)
    return buf.value


def key(vk, up=False):
    user32.keybd_event(vk, 0, KEYUP if up else 0, 0)
    time.sleep(0.03)


def tap(vk):
    key(vk)
    key(vk, up=True)


def settle():
    time.sleep(0.25)


state = {"v": (frozenset(), frozenset())}
fired = []
hook = _KeyHook(lambda: state["v"], fired.append)

t = threading.Thread(target=ui_thread, daemon=True)
t.start()
assert ready.wait(5), "Zielfenster kam nicht hoch"
top, edit = box["top"], box["edit"]
hook.start()
assert hook._tid, "Hook nicht installiert"
try:
    inject.focus_window(top)
    focus_now.set()
    time.sleep(0.4)
    assert win32gui.GetForegroundWindow() == top, "Testfenster nicht im Vordergrund"

    # 1) keine Aufnahme: Enter geht durch
    tap(VK_A); tap(VK_RETURN); settle()
    txt = read_text(edit)
    assert txt.count("\r\n") == 1, repr(txt)
    print("1) ohne Aufnahme: Enter geht durch OK", repr(txt))

    # 2) Aufnahme laeuft: Enter + Auto-Repeat + Up werden geschluckt
    state["v"] = (frozenset({"enter", "escape"}), frozenset())
    key(VK_RETURN)
    state["v"] = (frozenset(), frozenset())   # wie main: nach dem Ausloesen leer
    key(VK_RETURN); key(VK_RETURN)            # Auto-Repeat
    key(VK_RETURN, up=True); settle()
    txt = read_text(edit)
    assert txt.count("\r\n") == 1, repr(txt)
    assert fired == ["enter"], fired
    assert not (user32.GetAsyncKeyState(VK_RETURN) & 0x8000), "Enter haengt"
    tap(VK_A); settle()                       # Fenster tippt danach normal weiter
    assert read_text(edit).endswith("a"), repr(read_text(edit))
    print("2) Aufnahme: Enter geschluckt, ein Ausloeser, nichts haengt OK")

    # 3) Shift+Enter geht durch
    state["v"] = (frozenset({"enter"}), frozenset())
    key(VK_SHIFT); tap(VK_RETURN); key(VK_SHIFT, up=True); settle()
    txt = read_text(edit)
    assert txt.count("\r\n") == 2, repr(txt)
    assert fired == ["enter"], fired
    print("3) Shift+Enter waehrend der Aufnahme geht durch OK")

    # 4) LocalFlows eigenes Enter wird nie geschluckt
    inject.press_keys(["enter"], target_hwnd=top); settle()
    txt = read_text(edit)
    assert txt.count("\r\n") == 3, repr(txt)
    assert fired == ["enter"], fired
    print("4) eigenes Enter (press_keys) geht durch OK")

    # 5) Escape
    state["v"] = (frozenset({"escape"}), frozenset())
    tap(VK_ESCAPE); settle()
    assert fired == ["enter", "escape"], fired
    state["v"] = (frozenset(), frozenset())
    tap(VK_RETURN); settle()                   # danach wieder normal
    assert read_text(edit).count("\r\n") == 4
    print("5) Escape loest aus, danach alles normal OK")
    print("ALLE E2E-KEYHOOK-TESTS OK")
finally:
    hook.stop()
    stop.set()
