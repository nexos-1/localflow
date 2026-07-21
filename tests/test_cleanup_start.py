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

# --- touch(): Kaltstart-Vorwaermung beim Aufnahme-Start ---
import time  # noqa: E402


def make_touch_cleaner(last_used_age: float):
    c = Cleaner()
    c.is_healthy = lambda: True     # ensure_running -> sofort True
    c._last_used = time.monotonic() - last_used_age
    return c


# 6. Kalt (lange nicht genutzt) -> genau EIN Lade-POST, _last_used frisch
c = make_touch_cleaner(last_used_age=120)
with mock.patch("localflow.cleanup.requests.post") as post:
    c.touch()
assert post.call_count == 1, post.call_count
payload = post.call_args.kwargs["json"]
assert payload == {"model": c.model, "keep_alive": c.keep_alive}, payload
assert time.monotonic() - c._last_used < 5
print("6. touch kalt -> genau EIN Lade-POST OK")

# 6b. Langsames Laden (>1s) -> zusaetzlich EIN Mini-Clean (Erst-Inferenz
#     vorziehen); schnelles Laden (Fall 6) loest KEINEN Clean aus.
c = make_touch_cleaner(last_used_age=120)
cleans = []
c.clean = lambda text, language=None: cleans.append(text)


def slow_load(*a, **kw):
    time.sleep(1.1)
    return mock.Mock()


with mock.patch("localflow.cleanup.requests.post", side_effect=slow_load):
    c.touch()
assert cleans == ["hallo test"], cleans
print("6b. Kaltstart-touch -> Mini-Clean fuer Erst-Inferenz OK")

# 7. Kuerzlich genutzt (< 60s) -> gar kein HTTP-Aufruf
c = make_touch_cleaner(last_used_age=10)
with mock.patch("localflow.cleanup.requests.post") as post:
    c.touch()
assert post.call_count == 0, post.call_count
print("7. touch warm (Ruhezeit) -> kein Aufruf OK")

# 8. Paralleler zweiter touch wird uebersprungen (Single-Flight)
c = make_touch_cleaner(last_used_age=120)
started = threading.Event()
release = threading.Event()


def slow_post(*a, **kw):
    started.set()
    release.wait(3)
    return mock.Mock()


with mock.patch("localflow.cleanup.requests.post", side_effect=slow_post) as post:
    t = threading.Thread(target=c.touch)
    t.start()
    started.wait(3)
    c.touch()          # muss sofort zurueckkehren, ohne zweiten POST
    release.set()
    t.join()
assert post.call_count == 1, post.call_count
print("8. paralleler touch -> Single-Flight OK")

# 9. Verdrahtung: _on_dictate_start startet den touch-Thread
main_src = open(os.path.join(os.path.dirname(__file__), "..",
                             "localflow", "main.py"), encoding="utf-8").read()
start_body = main_src.split("def _on_dictate_start")[1].split("def _abort_recording")[0]
assert "cleaner.touch" in start_body, "touch nicht im Aufnahme-Start verdrahtet"
print("9. touch im Aufnahme-Start verdrahtet OK")

print("\nCLEANUP START TESTS PASSED")
