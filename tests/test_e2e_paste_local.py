"""E2E: paste_text fuegt wirklich ein UND laesst die Zwischenablage heil.

Braucht - anders als test_e2e_inject.py - KEINE laufende App: das Zielfenster
wird selbst gebaut. Deckt die Regression aus test_clipboard_owner.py von der
anderen Seite ab, naemlich dass die Clipboard-Rettung das Einfuegen nicht
kaputtmacht.

Warum nicht Notepad: Windows-11-Notepad ist eine WinUI-App, ihr Inhalt ist
nicht per WM_GETTEXT auslesbar. Ein klassisches EDIT-Control ist es sehr wohl.

Beweist in einem Durchlauf:
  1. Das Diktat landet wirklich im Zielfenster (echtes Strg+V, echtes Paste).
  2. Das kopierte Bild des Nutzers ist danach NOCH DA.

Das Fenster laeuft in einem eigenen Thread mit Nachrichtenschleife, damit
Windows das Paste verarbeiten kann, waehrend paste_text im Hauptthread
seine restore_delay abwartet.
"""
import ctypes
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import win32clipboard
import win32con
import win32gui

from localflow import inject

WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
DIKTAT = "Dies ist ein simuliertes Diktat aus dem Gegentest."

box = {}
ready = threading.Event()
stop = threading.Event()
focus_now = threading.Event()


def make_dib(w=8, h=8):
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, 0, 0, 0, 0, 0)
    return header + bytes(((w * 24 + 31) // 32) * 4 * h)


def ui_thread():
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "LocalFlowPasteTarget"
    wc.lpfnWndProc = {win32con.WM_DESTROY: lambda *a: win32gui.PostQuitMessage(0) or 0}
    win32gui.RegisterClass(wc)
    top = win32gui.CreateWindow(
        wc.lpszClassName, "LocalFlow Paste-Ziel",
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        200, 200, 500, 200, 0, 0, 0, None)
    edit = win32gui.CreateWindow(
        "EDIT", "", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
        | win32con.ES_AUTOHSCROLL,
        10, 10, 460, 30, top, 0, 0, None)
    box["top"], box["edit"] = top, edit
    ready.set()
    while not stop.is_set():
        win32gui.PumpWaitingMessages()
        if focus_now.is_set():
            # SetFocus wirkt NUR im besitzenden Thread - vom Hauptthread aus
            # waere es wirkungslos und das Strg+V ginge ins Leere.
            win32gui.SetFocus(edit)
            focus_now.clear()
        time.sleep(0.01)
    win32gui.DestroyWindow(top)


def read_text(hwnd):
    n = ctypes.windll.user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, buf)
    return buf.value


t = threading.Thread(target=ui_thread, daemon=True)
t.start()
assert ready.wait(5), "Zielfenster kam nicht hoch"
top, edit = box["top"], box["edit"]
print("Zielfenster hwnd=%s Edit=%s" % (top, edit))
time.sleep(0.5)

try:
    # Der Nutzer hat ein Bild kopiert
    assert inject._open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, make_dib())
    finally:
        inject._close_clipboard()
    vorher = inject._snapshot_clipboard()
    assert vorher and win32con.CF_DIB in vorher, "Bild kam nicht ins Clipboard"
    print("Bild im Clipboard: ja")

    # Fokus auf das Eingabefeld, dann diktieren wie im Live-Betrieb
    inject.focus_window(top)
    focus_now.set()
    time.sleep(0.4)

    # MEHRERE Diktate aus jeweils FRISCHEN Worker-Threads - genau so laeuft es
    # in der App (_process pro Diktat in einem eigenen, kurzlebigen Thread).
    # Ein Fehler, der erst ab dem zweiten Diktat auftritt, wird nur so sichtbar:
    # im Feld war das erste Diktat "ok" und jedes weitere "failed", weil das
    # Clipboard-Besitzerfenster mit dem ersten Worker-Thread gestorben war.
    # Zustand des Besitzerfensters zuruecksetzen, damit es der ERSTE
    # Diktat-Worker anlegt - so wie in der frisch gestarteten App. Ohne das
    # gehoert es noch dem Hauptthread (der oben das Bild gesetzt hat), der
    # bleibt am Leben, und der Test bestuende auch auf kaputtem Code.
    inject._owner_hwnd = None
    inject._owner_ready.clear()

    stati = []
    for runde in range(3):
        ergebnis = {}

        def diktat(r=runde, out=ergebnis):
            out["status"] = inject.paste_text(
                "%s (%d)" % (DIKTAT, r), restore_delay=0.8, target_hwnd=top)

        wt = threading.Thread(target=diktat, name="diktat-worker-%d" % runde)
        wt.start()
        wt.join(20)
        assert not wt.is_alive(), "Diktat-Worker %d haengt" % runde
        stati.append(ergebnis.get("status"))
        print("Diktat %d -> %s" % (runde, stati[-1]))
        time.sleep(0.3)

    time.sleep(0.5)
    text = read_text(edit)
    nachher = inject._snapshot_clipboard()
    print("Feldinhalt: %r" % text)
    print("Clipboard danach: Formate=%s" % sorted(nachher.keys() if nachher else []))

    assert all(s == inject.PASTE_OK for s in stati), "Paste-Status: %s" % (stati,)
    assert text.count(DIKTAT) == 3, "nicht alle drei Diktate kamen an: %r" % text
    status = stati[-1]
    assert nachher and win32con.CF_DIB in nachher, "BILD VERLOREN - der Bug ist zurueck"
    print("\nE2E OK: Diktat eingefuegt UND Bild erhalten")
finally:
    stop.set()
    t.join(3)
