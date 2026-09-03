"""Im Spiel / Vollbild pausieren: Gate-Logik der Hooks (pure, ohne OS-Hooks)
und die Win32-Erkennung gegen ein unsichtbares Testfenster.

Die Erkennung selbst laeuft nur unter Windows; die Gate-Logik ist portabel.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.hotkey import DictationController, PushToTalk, _MouseHook  # noqa: E402


class Probe:
    def __init__(self):
        self.events = []
    def start(self): self.events.append("start")
    def stop(self): self.events.append("stop")
    def cancel(self): self.events.append("cancel")
    def lock(self): self.events.append("lock")


# 1) Maus-Hook-Entscheidung: (melden, verschlucken) je nach Gate + suppress
gate_open = [True]
seen = []
mh = _MouseHook({"maus4"}, lambda n, d: seen.append((n, d)), suppress=True,
                gate=lambda: gate_open[0])
# Gate offen: DOWN wird gemeldet UND geschluckt, UP ebenso
assert mh.decide("maus4", True) == (True, True)
assert mh.decide("maus4", False) == (True, True)
# Gate zu (Spiel): DOWN wird weder gemeldet noch geschluckt -> Spiel sieht die Taste
gate_open[0] = False
assert mh.decide("maus4", True) == (False, False)
# UP nach ungeschlucktem DOWN: gemeldet (harmlos), NICHT geschluckt (sonst Down ohne Up)
assert mh.decide("maus4", False) == (True, False)
print("Maus-Hook: im Spiel geht die Seitentaste unverschluckt durch OK")

# 2) Halten ausserhalb, dann ins Spiel wechseln: UP muss durchkommen und
#    geschluckt bleiben (das DOWN wurde ja geschluckt) -> Aufnahme endet sauber.
gate_open[0] = True
assert mh.decide("maus4", True) == (True, True)
gate_open[0] = False
assert mh.decide("maus4", False) == (True, True)
print("Maus-Hook: Loslassen im Spiel beendet gehaltene Aufnahme OK")

# 3) Ohne suppress wird nie geschluckt, Gate wirkt trotzdem auf DOWN
mh2 = _MouseHook({"maus5"}, lambda n, d: None, suppress=False,
                 gate=lambda: gate_open[0])
gate_open[0] = False
assert mh2.decide("maus5", True) == (False, False)
gate_open[0] = True
assert mh2.decide("maus5", True) == (True, False)
assert mh2.decide("maus5", False) == (True, False)
# Gate-Fehler = offen (Erkennung darf das Diktat nie sperren)
def boom():
    raise RuntimeError("kaputt")
mh3 = _MouseHook({"maus5"}, lambda n, d: None, gate=boom)
assert mh3.decide("maus5", True) == (True, False)
print("Maus-Hook: kein suppress / Gate-Fehler = offen OK")

# 4) Tastatur-Pfad: PushToTalk._handler fragt das Gate nur bei DOWN
class Ev:
    def __init__(self, name, et):
        self.name, self.event_type = name, et

p = Probe()
ctrl = DictationController(p.start, p.stop, p.cancel, p.lock, mode="hold")
ptt = PushToTalk("ctrl+win", ctrl, gate=lambda: gate_open[0])
drained = []
ptt._enqueue = lambda part, is_down: drained.append((part, is_down))
gate_open[0] = False
ptt._handler(Ev("ctrl", "down"))
ptt._handler(Ev("left windows", "down"))
assert drained == [], drained
ptt._handler(Ev("ctrl", "up"))          # UP laeuft immer durch
assert drained == [("ctrl", False)], drained
gate_open[0] = True
drained.clear()
ptt._handler(Ev("ctrl", "down"))
assert drained == [("ctrl", True)], drained
print("Tastatur-Hook: DOWN im Spiel ignoriert, UP immer durch OK")

# 5) Ende-zu-Ende durch die Zustandsmaschine: im Spiel loest die volle
#    Kombination nichts aus; danach normal.
p.events.clear()
ptt2 = PushToTalk("maus5", ctrl, gate=lambda: gate_open[0])
def feed(ptt_, part, is_down):
    # so wie der Maus-Hook es taete: decide() -> on_event -> _apply
    report, _ = _MouseHook({part}, None, gate=ptt_.gate).decide(part, is_down)
    if report:
        ptt_._apply(part, is_down)
gate_open[0] = False
feed(ptt2, "maus5", True); feed(ptt2, "maus5", False)
assert p.events == [], p.events
gate_open[0] = True
feed(ptt2, "maus5", True); feed(ptt2, "maus5", False)
assert p.events == ["start", "stop"], p.events
print("Zustandsmaschine: im Spiel kein Diktat, danach normal OK")

# 6) Pure Geometrie-/Klassifikationslogik der Win32-Erkennung
from localflow.platform.win32 import fullscreen as fs  # noqa: E402

MON = (0, 0, 2560, 1440)
assert fs.covers_monitor((0, 0, 2560, 1440), MON)          # exakt
assert fs.covers_monitor((-8, -8, 2568, 1448), MON)        # unsichtbarer Rahmen
assert not fs.covers_monitor((0, 0, 2560, 1400), MON)      # endet an der Taskleiste
assert not fs.covers_monitor((100, 100, 1900, 1000), MON)  # normales Fenster
assert not fs.covers_monitor((0, 0, 2560, 1440), (0, 0, 0, 0))
assert fs.classify(True, has_caption=False, is_zoomed=False, class_name="UnrealWindow", own_process=False)
assert fs.classify(True, has_caption=True, is_zoomed=False, class_name="SDL_app", own_process=False)
assert not fs.classify(True, has_caption=True, is_zoomed=True, class_name="Chrome_WidgetWin_1", own_process=False)
assert not fs.classify(True, has_caption=False, is_zoomed=False, class_name="Progman", own_process=False)
assert not fs.classify(True, has_caption=False, is_zoomed=False, class_name="WorkerW", own_process=False)
assert not fs.classify(True, has_caption=False, is_zoomed=False, class_name="TkTopLevel", own_process=True)
assert not fs.classify(False, has_caption=False, is_zoomed=False, class_name="X", own_process=False)
print("Geometrie/Klassifikation OK")

# 7) Echte Win32-Abfrage gegen ein NIE angezeigtes Testfenster (kein Flackern
#    auf dem Desktop): randloser Popup in Monitorgroesse = Vollbild, kleiner
#    Popup = kein Vollbild. Eigener Prozess wird per own_process ausgenommen -
#    fuer den Test die Regel umgehen, indem classify direkt mit den echten
#    Werten gefuettert wird.
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = ctypes.c_void_p
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    u.DestroyWindow.argtypes = [ctypes.c_void_p]
    WS_POPUP = 0x80000000
    cx, cy = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    # "Static" ist eine System-Fensterklasse - keine eigene Registrierung noetig
    big = u.CreateWindowExW(0, "Static", "lf-test-fullscreen", WS_POPUP, 0, 0, cx, cy,
                            None, None, None, None)
    small = u.CreateWindowExW(0, "Static", "lf-test-small", WS_POPUP, 100, 100, 640, 480,
                              None, None, None, None)
    assert big and small, "Testfenster konnten nicht erzeugt werden"
    try:
        # Geometrie-Pfad isoliert: gleiches Fenster, aber own_process-Regel
        # greift (eigener Prozess) -> False. Deshalb Rechteck selbst holen.
        r = wintypes.RECT()
        u.GetWindowRect(ctypes.c_void_p(big), ctypes.byref(r))
        assert fs.covers_monitor((r.left, r.top, r.right, r.bottom), (0, 0, cx, cy)), \
            (r.left, r.top, r.right, r.bottom)
        assert fs.is_fullscreen_app_active(hwnd=big) is False   # eigener Prozess -> ausgenommen
        assert fs.is_fullscreen_app_active(hwnd=small) is False
        # Fremdprozess simulieren (own_pid ungleich unserer PID)
        assert fs.is_fullscreen_app_active(hwnd=big, own_pid=-1) is True
        assert fs.is_fullscreen_app_active(hwnd=small, own_pid=-1) is False
        # Kosten des VOLLEN Pfads (Fenster bedeckt den Monitor -> alle Abfragen)
        import timeit
        n = 2000
        us = timeit.timeit(lambda: fs.is_fullscreen_app_active(hwnd=big, own_pid=-1),
                           number=n) / n * 1e6
        assert us < 2000, f"Erkennung zu teuer fuer den Hook-Thread: {us:.0f} us"
        print(f"Voller Erkennungspfad: {us:.0f} us/Aufruf")
    finally:
        u.DestroyWindow(big)
        u.DestroyWindow(small)
    # Live-Abfrage auf dem aktuellen Desktop darf nie crashen und liefert bool
    live = fs.is_fullscreen_app_active()
    assert isinstance(live, bool)
    print(f"Win32-Erkennung gegen Testfenster OK (Desktop gerade: {'Vollbild' if live else 'kein Vollbild'})")

print("\nFULLSCREEN GATE TESTS PASSED")
