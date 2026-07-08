"""Clipboard-Erhaltung: Text- und Datei-Kopien ueberleben ein Snapshot/Restore.

Achtung: manipuliert kurz das echte Clipboard und stellt es am Ende wieder her.
"""

import os
import sys
import time

import win32clipboard
import win32con

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.inject import _pack_hdrop, _restore_clipboard, _set_clipboard_text, _snapshot_clipboard

# Original des Nutzers sichern
user_snap = _snapshot_clipboard()

try:
    # 1. Text-Roundtrip
    _set_clipboard_text("SNAPSHOT-TEST-TEXT")
    snap = _snapshot_clipboard()
    assert snap.get(win32con.CF_UNICODETEXT) == "SNAPSHOT-TEST-TEXT"
    _set_clipboard_text("zerstoert")
    _restore_clipboard(snap)
    assert _snapshot_clipboard().get(win32con.CF_UNICODETEXT) == "SNAPSHOT-TEST-TEXT"
    print("Text-Roundtrip OK")

    # 2. Datei-Kopie (CF_HDROP) Roundtrip
    test_file = os.path.abspath(__file__)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, _pack_hdrop((test_file,)))
    finally:
        win32clipboard.CloseClipboard()
    snap = _snapshot_clipboard()
    assert snap.get(win32con.CF_HDROP) == (test_file,), snap.get(win32con.CF_HDROP)
    _set_clipboard_text("diktat-text")   # simuliertes Diktat ueberschreibt
    _restore_clipboard(snap)             # Restore bringt die Datei zurueck
    restored = _snapshot_clipboard()
    assert restored.get(win32con.CF_HDROP) == (test_file,), restored
    print("HDROP-Roundtrip OK (Datei-Kopien ueberleben ein Diktat)")

finally:
    # Nutzer-Clipboard wiederherstellen
    if user_snap:
        _restore_clipboard(user_snap)
    time.sleep(0.1)

print("\nCLIPBOARD TEST PASSED")
