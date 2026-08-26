"""Regression: ein Diktat darf die Zwischenablage des Nutzers nie loeschen.

Feldbefund 2026-08-26: OpenClipboard wurde ohne Fenster-Handle gerufen. Dann
setzt EmptyClipboard den Clipboard-Besitzer auf NULL, und das nachfolgende
SetClipboardData scheitert mit ERROR_CLIPBOARD_NOT_OPEN (1418) - im Restore
also: der Inhalt des Nutzers ist schon geloescht, das Zurueckschreiben schlaegt
fehl, ein kopiertes Bild ist unwiederbringlich weg. Im Stresstest trat das nach
~1500 Zyklen zuverlaessig auf.

Achtung: manipuliert kurz das echte Clipboard und stellt es am Ende wieder her.
"""

import os
import struct
import subprocess
import sys
import threading
import time

import win32clipboard
import win32con
import win32gui

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow import inject
from localflow.inject import (_clipboard_owner, _close_clipboard, _open_clipboard,
                              _restore_clipboard, _set_clipboard_text,
                              _snapshot_clipboard)

CYCLES = 300  # der Bug schlug im Stresstest nach ~1500 zu; 300 reichen fuer CI


def _make_dib(w: int = 8, h: int = 8) -> bytes:
    """Minimales 24-bit-DIB (BITMAPINFOHEADER + Pixel), wie es eine Bildkopie
    im Clipboard hinterlaesst."""
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, 0, 0, 0, 0, 0)
    stride = ((w * 24 + 31) // 32) * 4
    return header + bytes(stride * h)


user_snap = _snapshot_clipboard()
failures = []
try:
    # 1. Besitzerfenster existiert und ist ein echtes Handle
    assert _clipboard_owner(), "kein Clipboard-Besitzerfenster erzeugt"
    print("Besitzerfenster OK")

    # 2. DER Kernfall: nach EmptyClipboard muss SetClipboardData funktionieren.
    #    Ohne Besitzerfenster schlaegt genau das mit 1418 fehl.
    assert _open_clipboard(), "Clipboard nicht zu oeffnen"
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, "BESITZER-TEST")
    finally:
        _close_clipboard()
    assert _snapshot_clipboard().get(win32con.CF_UNICODETEXT) == "BESITZER-TEST"
    print("SetClipboardData nach EmptyClipboard OK")

    # 2b. Die Ursache selbst, deterministisch: nach EmptyClipboard MUSS unser
    #     Fenster der Clipboard-Besitzer sein. Ohne Handle beim OpenClipboard
    #     ist der Besitzer 0 - und genau dann faellt SetClipboardData
    #     irgendwann mit 1418 um. Der Zyklustest unten trifft das nur als
    #     Rennen (im Stresstest erst nach ~1500 Runden), diese Pruefung immer.
    try:
        owner = win32clipboard.GetClipboardOwner()
    except Exception:  # noqa: BLE001 - pywin32 meldet Besitzer 0 als Fehler
        owner = 0
    assert owner == _clipboard_owner(), (
        f"Clipboard-Besitzer ist {owner}, erwartet {_clipboard_owner()} - "
        "OpenClipboard wurde ohne Fenster-Handle gerufen (das war der Bug)")
    print("Clipboard-Besitzer ist unser Fenster OK (das war der Bug)")

    # 2c. Das Besitzerfenster muss den erzeugenden Thread UEBERLEBEN.
    #     Windows zerstoert ein Fenster mit seinem Thread. Diktate laufen in
    #     kurzlebigen Worker-Threads - wurde das Fenster dort angelegt, war es
    #     nach dem ersten Diktat weg und jedes weitere OpenClipboard lief gegen
    #     ein ungueltiges Handle ("Clipboard konnte nicht gesetzt werden").
    #     Im Feld beobachtet, von den Tests im Hauptthread nicht getroffen.
    #     Wichtig: Zustand zuruecksetzen, damit der Worker das Fenster WIRKLICH
    #     selbst anlegt. Ohne das bekaeme er nur das im Hauptthread erzeugte
    #     Handle zurueck - der Test bestuende dann auch auf kaputtem Code
    #     (genau so zuerst passiert).
    inject._owner_hwnd = None
    inject._owner_ready.clear()

    aus_worker = {}

    def im_worker():
        aus_worker["hwnd"] = inject._clipboard_owner()

    w = threading.Thread(target=im_worker, name="wegwerf-worker")
    w.start()
    w.join(5)
    assert not w.is_alive(), "Worker-Thread haengt"
    hwnd = aus_worker.get("hwnd")
    assert hwnd, "Worker bekam kein Besitzerfenster"
    time.sleep(0.3)  # Windows das Aufraeumen des toten Threads zugestehen
    assert win32gui.IsWindow(hwnd), (
        "Besitzerfenster mit dem erzeugenden Thread gestorben - "
        "es gehoert auf einen dauerhaften Thread")
    assert inject._clipboard_owner() == hwnd, "Besitzerfenster wechselte unerwartet"
    assert _open_clipboard(), "Clipboard nach Thread-Ende nicht mehr zu oeffnen"
    _close_clipboard()
    _set_clipboard_text("NACH-WORKER")   # der Aufruf, der im Feld scheiterte
    assert _snapshot_clipboard().get(win32con.CF_UNICODETEXT) == "NACH-WORKER"
    print("Besitzerfenster ueberlebt den erzeugenden Thread OK")

    # 3. Ein Bild ueberlebt viele Diktat-Zyklen (Snapshot -> Diktat -> Restore)
    dib = _make_dib()
    assert _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
    finally:
        _close_clipboard()
    for i in range(CYCLES):
        snap = _snapshot_clipboard()
        if snap is None:
            continue  # Clipboard war gesperrt - Inhalt bleibt unangetastet
        _set_clipboard_text("simuliertes Diktat %d" % i)
        if snap:
            _restore_clipboard(snap)
        cur = _snapshot_clipboard()
        if cur is None or win32con.CF_DIB not in cur:
            failures.append(i)
            break
    assert not failures, f"Bild nach {failures[0]} Zyklen verloren"
    print(f"Bild ueberlebt {CYCLES} Diktat-Zyklen OK")

    # 4. _snapshot_clipboard muss "nicht zu oeffnen" (None) von "war leer" ({})
    #    unterscheiden - sonst loescht paste_text den Inhalt des Nutzers.
    #    Die Sperre muss aus einem FREMDEN Prozess kommen: fuer dasselbe
    #    Besitzerfenster ist OpenClipboard wiedereintrittsfaehig, ein zweiter
    #    Thread derselben App wuerde also gar nicht blockieren.
    #    Der Sperr-Prozess braucht ein ECHTES Fenster: OpenClipboard scheitert
    #    nur, wenn ein anderes FENSTER die Zwischenablage offen haelt. Mit
    #    Handle 0 haelt sie formal kein Fenster, und unser Aufruf kaeme
    #    gelegentlich doch durch (als flackernder Test beobachtet).
    hog_code = (
        "import sys, time, win32gui, win32clipboard\n"
        "h = win32gui.CreateWindowEx(0, 'STATIC', 'hog', 0, 0,0,0,0, -3, 0, 0, None)\n"
        "win32clipboard.OpenClipboard(h)\n"
        "sys.stdout.write('HELD\\n'); sys.stdout.flush()\n"
        "time.sleep(4)\n"
    )
    hog = subprocess.Popen([sys.executable, "-c", hog_code],
                           stdout=subprocess.PIPE, text=True)
    try:
        assert hog.stdout.readline().strip() == "HELD", "Sperr-Prozess kam nicht hoch"
        blocked = _snapshot_clipboard()
    finally:
        hog.kill()
        hog.wait(5)
    assert blocked is None, f"gesperrtes Clipboard muss None liefern, war {blocked!r}"
    print("Gesperrtes Clipboard -> None (nicht {}) OK")

    # 5. _close_clipboard darf nie werfen, auch ohne offenes Clipboard
    _close_clipboard()
    print("_close_clipboard ohne offenes Clipboard OK")

finally:
    if user_snap:
        _restore_clipboard(user_snap)
    time.sleep(0.1)

print("\nCLIPBOARD-OWNER TEST PASSED")
