"""Sound-Backend fuer macOS: Synthese geteilt, Playback via afplay.
(EXPERIMENTELL/ungetestet auf Hardware; afplay ist Systembestandteil.)"""

import logging
import os
import subprocess

from ...sounds import SOUND_DIR, ensure_sounds  # noqa: F401 - Synthese geteilt

log = logging.getLogger("localflow.darwin")


def play(name: str):
    path = os.path.join(SOUND_DIR, f"{name}.wav")
    if not os.path.exists(path):
        return
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:  # noqa: BLE001 - Sounds duerfen nie das Diktat stoeren
        log.debug("afplay fehlgeschlagen", exc_info=True)
