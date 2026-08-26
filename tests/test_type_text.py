"""Tipp-Modus: Text kommt an UND die Zwischenablage bleibt voellig unberuehrt.

Hintergrund: paste_text laeuft zwangslaeufig ueber die Zwischenablage und macht
LocalFlow zu deren Besitzer. Programme mit Zwischenablage-Ueberwachung (z.B.
Claude Code) melden deshalb bei JEDEM Diktat eine Aenderung. type_text tippt
per SendInput mit Unicode-Events und fasst sie gar nicht an.

Der harte Nachweis ist die Sequenznummer: GetClipboardSequenceNumber zaehlt
JEDE Aenderung der Zwischenablage systemweit. Bleibt sie ueber ein Diktat
konstant, wurde nichts angefasst - unabhaengig davon, wie ein Detektor prueft.

Achtung: baut ein eigenes Fenster und tippt hinein. Es gehen keine Tasten an
fremde Fenster: schlaegt das Fokussieren fehl, tippt type_text gar nicht.
"""

import ctypes
import os
import sys
import threading
import time

import win32con
import win32gui

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow import inject

WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
# Umlaute und ein Emoji (Surrogatpaar) sind der interessante Teil: sie muessen
# als UTF-16-Codeeinheiten gesendet werden, sonst kommt Unsinn an.
PROBE = "Gruesse, Umlaute aeoeue ÄÖÜ ß und ein Emoji 😀 - fertig."

box, ready, stop, focus_now = {}, threading.Event(), threading.Event(), threading.Event()


def ui_thread():
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = "LocalFlowTypeTarget"
    wc.lpfnWndProc = {win32con.WM_DESTROY: lambda *a: win32gui.PostQuitMessage(0) or 0}
    win32gui.RegisterClass(wc)
    top = win32gui.CreateWindow(
        wc.lpszClassName, "LocalFlow Tipp-Ziel",
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        200, 200, 600, 160, 0, 0, 0, None)
    edit = win32gui.CreateWindow(
        "EDIT", "", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_BORDER
        | win32con.ES_AUTOHSCROLL, 10, 10, 560, 30, top, 0, 0, None)
    box["top"], box["edit"] = top, edit
    ready.set()
    while not stop.is_set():
        win32gui.PumpWaitingMessages()
        if focus_now.is_set():
            win32gui.SetFocus(edit)   # wirkt nur im besitzenden Thread
            focus_now.clear()
        time.sleep(0.01)
    win32gui.DestroyWindow(top)


def read_text(hwnd):
    n = ctypes.windll.user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.SendMessageW(hwnd, WM_GETTEXT, n + 1, buf)
    return buf.value


def clip_seq():
    return ctypes.windll.user32.GetClipboardSequenceNumber()


t = threading.Thread(target=ui_thread, daemon=True)
t.start()
assert ready.wait(5), "Zielfenster kam nicht hoch"
top, edit = box["top"], box["edit"]
time.sleep(0.4)

try:
    # 1. Reine Event-Erzeugung (ohne Fenster): UTF-16-Codeeinheiten, je Down+Up
    assert len(inject._unicode_events("Hi")) == 4, "2 Zeichen = 4 Events"
    assert len(inject._unicode_events("\U0001F600")) == 4, "Emoji = 2 Einheiten = 4 Events"
    assert len(inject._unicode_events("a\r\nb")) == 6, "\\r\\n darf nur EIN Return sein"
    assert ctypes.sizeof(inject._INPUT) == 40, "INPUT-Struktur hat die falsche Groesse"
    print("Event-Erzeugung OK")

    # 2. Der Kernnachweis: tippen, ohne die Zwischenablage anzufassen
    marker = "UNBERUEHRTER-INHALT-DES-NUTZERS"
    inject._set_clipboard_text(marker)
    time.sleep(0.3)

    inject.focus_window(top)
    focus_now.set()
    time.sleep(0.4)

    seq_vorher = clip_seq()
    status = inject.type_text(PROBE, target_hwnd=top)
    time.sleep(0.6)
    seq_nachher = clip_seq()

    text = read_text(edit)
    print("type_text        :", status)
    print("Feldinhalt       : %r" % text)
    print("Clipboard-Seq    : %d -> %d (Differenz %d)"
          % (seq_vorher, seq_nachher, seq_nachher - seq_vorher))

    assert status == inject.PASTE_OK, "Status %s" % status
    assert text == PROBE, "getippter Text weicht ab:\n  ist %r\n  soll %r" % (text, PROBE)
    assert seq_nachher == seq_vorher, (
        "Zwischenablage wurde angefasst (Sequenznummer +%d) - genau das soll "
        "der Tipp-Modus vermeiden" % (seq_nachher - seq_vorher))
    assert inject._get_clipboard_text() == marker, "Clipboard-Inhalt veraendert"
    print("Zwischenablage unangetastet OK (Sequenznummer unveraendert)")

    # 3. Gegenprobe: paste_text bewegt die Sequenznummer sehr wohl. Ohne das
    #    koennte Punkt 2 auch bestehen, wenn die Messung gar nichts misst.
    focus_now.set()
    time.sleep(0.3)
    seq_vorher = clip_seq()
    inject.paste_text(" [eingefuegt]", restore_delay=0.5, target_hwnd=top)
    time.sleep(0.4)
    delta_paste = clip_seq() - seq_vorher
    print("Zum Vergleich paste_text: Sequenznummer +%d" % delta_paste)
    assert delta_paste > 0, "Messung untauglich - paste_text muesste die Seq. bewegen"
    print("Messung ist aussagekraeftig OK")

finally:
    stop.set()
    t.join(3)

print("\nTYPE-TEXT TEST PASSED")
