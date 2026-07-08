"""Unit-Tests: Cleaner.ensure_running startet Ollama nie doppelt.

Abgedeckt: (1) gesund -> kein Start, (2) fremder Prozess bootet noch ->
warten statt spawnen, (3) nichts laeuft -> genau EIN Spawn, (4) parallele
Aufrufe -> trotzdem nur ein Spawn, (5) haengender Fremdprozess ->
Spawn-Fallback nach Wartezeit.
"""

import os
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from localflow.cleanup import Cleaner


def make(healthy_after: int | None, proc_running: bool):
    """Cleaner mit gefakter Umgebung. healthy_after: ab dem n-ten
    is_healthy-Aufruf True (None = nie gesund)."""
    c = Cleaner()
    c.BOOT_WAIT_S = 1.5
    calls = {"health": 0}

    def fake_healthy():
        calls["health"] += 1
        return healthy_after is not None and calls["health"] >= healthy_after

    c.is_healthy = fake_healthy
    c._ollama_process_running = lambda: proc_running
    return c


def run_with_spawn_counter(c, threads=1):
    results = []
    with mock.patch("localflow.cleanup.subprocess.Popen") as popen:
        if threads == 1:
            results.append(c.ensure_running())
        else:
            ts = [threading.Thread(target=lambda: results.append(c.ensure_running()))
                  for _ in range(threads)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        return results, popen.call_count


# 1. Server gesund -> True, kein Spawn
c = make(healthy_after=1, proc_running=False)
r, spawns = run_with_spawn_counter(c)
assert r == [True] and spawns == 0, (r, spawns)
print("1. gesund -> kein Start OK")

# 2. Fremder Ollama-Prozess bootet noch -> warten, NICHT spawnen
c = make(healthy_after=3, proc_running=True)
r, spawns = run_with_spawn_counter(c)
assert r == [True] and spawns == 0, (r, spawns)
print("2. fremder Prozess -> gewartet statt gespawnt OK")

# 3. Nichts laeuft -> genau ein Spawn, danach gesund
c = make(healthy_after=3, proc_running=False)
r, spawns = run_with_spawn_counter(c)
assert r == [True] and spawns == 1, (r, spawns)
print("3. nichts laeuft -> genau EIN Spawn OK")

# 4. Zwei parallele Aufrufe (App-Warmup + Settings-Save) -> EIN Spawn
c = make(healthy_after=4, proc_running=False)
r, spawns = run_with_spawn_counter(c, threads=2)
assert r == [True, True] and spawns == 1, (r, spawns)
print("4. parallele Aufrufe -> trotzdem nur EIN Spawn OK")

# 5. Fremdprozess haengt (nie gesund) -> nach Wartezeit Spawn-Fallback
c = make(healthy_after=None, proc_running=True)
r, spawns = run_with_spawn_counter(c)
assert r == [False] and spawns == 1, (r, spawns)
print("5. haengender Fremdprozess -> Fallback-Spawn nach Wartezeit OK")

print("\nCLEANUP START TESTS PASSED")
