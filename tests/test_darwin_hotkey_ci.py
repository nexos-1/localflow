"""macOS-CI: der Hotkey-Listener darf den Prozess nicht abbrechen.

Feldbefund v0.4.1: Abbruch in HIToolbox direkt nach dem Hotkey-Start
(TSMGetInputSourceProperty -> islGetInputSourceListWithAdditions ->
dispatch_assert_queue(main)), weil pynputs Listener-Thread das Tastatur-
Layout ueber TIS liest. Seit macOS 15 schrittweise, ab 26.x strikt erzwungen.
Dieser Test laeuft auf echten macOS-Runnern in eigenen Subprozessen:

1. Negativkontrolle (nur informativ): ungepatchter pynput-Listener aus einem
   schlichten Python-Prozess. Bricht er ab, reproduziert der Runner den
   Feldbefund; laeuft er durch, greift die Assertion auf dieser macOS-Version
   (noch) nicht - beides wird nur protokolliert.
2. Unser Backend (PynputPtt + Toggle-Hotkey + capture_combo aus einem
   Fremd-Thread): muss mit Exit 0 enden; TIS darf ausschliesslich auf dem
   Main-Thread gelesen worden sein; die Listener sind unsere sicheren Klassen
   (eigener _run, Event-Maske ohne NSSystemDefined).
3. run_on_main: ein Aufruf aus einem Fremd-Thread landet auf dem Main-Thread
   (Tray-Icon-Wechsel: pystray setzt setImage_ im Aufrufer-Thread).
"""

import os
import subprocess
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if sys.platform != "darwin":
    sys.exit("Dieser Test braucht macOS (pynput/Quartz).")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run(code: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout)


ver = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip()
print(f"macOS {ver}, Python {sys.version.split()[0]}")

# --- 1) Negativkontrolle: pynput pur, Listener-Thread liest TIS selbst -----
neg = run("""
    import time
    from pynput import keyboard
    lst = keyboard.Listener(on_press=lambda k: None, on_release=lambda k: None)
    lst.start()
    time.sleep(3)
    lst.stop()
    print("UNPATCHED-SURVIVED")
""")
print(f"Negativkontrolle (ungepatcht): returncode={neg.returncode} "
      f"survived={'UNPATCHED-SURVIVED' in neg.stdout}")
if neg.returncode != 0:
    print("  -> Runner REPRODUZIERT den Abbruch (negativer Code = Signal, -5 SIGTRAP / -6 SIGABRT)")
    tail = (neg.stderr.strip().splitlines() or ["<kein stderr>"])[-1]
    print("  " + tail[:300])

# --- 2) Unser Backend: TIS nur auf dem Main-Thread ---------------------------
pos = run("""
    import contextlib, threading, time
    import pynput._util.darwin as pud
    calls = []
    _orig = pud.keycode_context

    @contextlib.contextmanager
    def spy():
        calls.append(threading.current_thread() is threading.main_thread())
        with _orig() as ctx:
            yield ctx
    pud.keycode_context = spy          # VOR unserem Patch: zaehlt echte TIS-Laeufe

    import Quartz
    from pynput import keyboard
    from localflow.platform.darwin import hotkey

    class Ctl:
        mode = "both"
        def combo_down(self, owner=None): pass
        def combo_up(self, owner=None): pass

    ptt = hotkey.PynputPtt("ctrl+win", Ctl())
    ptt.start()                        # Main-Thread: liest TIS, startet Listener-Thread
    lst = ptt._kb_listener
    assert lst is not None, "Tastatur-Listener wurde deaktiviert (Selbstpruefung schlug fehl?)"
    assert type(lst).__name__ == "SafeListener" and isinstance(lst, keyboard.Listener)
    nsd = Quartz.CGEventMaskBit(14)    # NSSystemDefined
    assert not (type(lst)._EVENTS & nsd), "NSSystemDefined noch in der Event-Maske"
    hk = hotkey.add_hotkey("ctrl+alt+space", lambda: None)
    assert type(hk).__name__ == "SafeGlobalHotKeys"
    out = {}

    def from_foreign_thread():         # wie der Dashboard-Thread beim Hotkey-Wechsel
        p2 = hotkey.PynputPtt("shift+y", Ctl())   # Zeichentaste: braucht den Layout-Kontext
        p2.start(); time.sleep(0.5); p2.stop()
        out["capture"] = hotkey.capture_combo(timeout=0.5)
    t = threading.Thread(target=from_foreign_thread); t.start(); t.join(30)
    assert not t.is_alive(), "Fremd-Thread haengt"
    time.sleep(2.5)
    ptt.stop(); hotkey.remove_hotkey(hk)
    import pynput.keyboard._darwin as pkd
    assert pkd.keycode_context is pud.keycode_context, "Guard-Patch nicht in beiden Modulen"
    assert calls and all(calls), f"TIS abseits des Main-Threads gelesen: {calls}"
    assert out.get("capture", "x") is None
    print(f"PATCHED-OK tis_calls={len(calls)} all_main={all(calls)}")
""")
print(f"Unser Backend: returncode={pos.returncode}")
print(pos.stdout.strip()[-400:])
if pos.returncode != 0:
    print(pos.stderr.strip()[-2000:])
assert pos.returncode == 0, f"Hotkey-Backend brach ab (returncode {pos.returncode})"
assert "PATCHED-OK" in pos.stdout

# --- 3) run_on_main: Fremd-Thread -> Main-Thread ------------------------------
rom = run("""
    import threading, time
    import AppKit, Foundation
    from localflow.platform.darwin import integration
    AppKit.NSApplication.sharedApplication()
    seen = {}
    def fn():
        seen["main"] = threading.current_thread() is threading.main_thread()
    t = threading.Thread(target=lambda: integration.run_on_main(fn)); t.start(); t.join(5)
    end = time.time() + 2.0
    rl = Foundation.NSRunLoop.currentRunLoop()
    while time.time() < end and "main" not in seen:
        rl.runMode_beforeDate_(Foundation.NSDefaultRunLoopMode,
                               Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
    assert seen.get("main") is True, seen
    direct = {}
    integration.run_on_main(lambda: direct.setdefault("ok", True))   # im Main-Thread: sofort
    assert direct.get("ok") is True
    print("RUN-ON-MAIN-OK")
""")
print(f"run_on_main: returncode={rom.returncode} {rom.stdout.strip()[-60:]}")
if rom.returncode != 0:
    print(rom.stderr.strip()[-1500:])
assert rom.returncode == 0 and "RUN-ON-MAIN-OK" in rom.stdout

print("\nDARWIN HOTKEY CI TEST PASSED")
