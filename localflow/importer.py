"""Einmal-Import von Wispr-Flow-Daten (Dictionary + History) aus flow.sqlite."""

import logging
import os
import shutil
import sqlite3
import tempfile

log = logging.getLogger("localflow.importer")

WISPR_DIR = os.path.join(os.environ.get("APPDATA", ""), "Wispr Flow")


def _parse_ts(value) -> float:
    """Wispr speichert Timestamps mal als ISO-String, mal als Epoch(ms)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return value / 1000.0 if value > 1e11 else float(value)
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def import_wispr_data(db, include_history: bool = True) -> dict:
    src = os.path.join(WISPR_DIR, "flow.sqlite")
    if not os.path.exists(src):
        raise FileNotFoundError("Wispr Flow Datenbank nicht gefunden: " + src)

    # Kopie ziehen (Original kann von Wispr gesperrt/WAL-offen sein)
    tmpdir = tempfile.mkdtemp(prefix="wispr_import_")
    con = None
    try:
        for ext in ["", "-wal", "-shm"]:
            f = src + ext
            if os.path.exists(f):
                shutil.copy2(f, os.path.join(tmpdir, os.path.basename(f)))
        con = sqlite3.connect(os.path.join(tmpdir, "flow.sqlite"))
        con.row_factory = sqlite3.Row

        existing_phrases = {e["phrase"].lower() for e in db.get_dictionary(include_deleted=True)}
        dict_count = 0
        for r in con.execute("SELECT phrase, replacement, isSnippet FROM Dictionary WHERE isDeleted=0"):
            if (r["phrase"] or "").lower() in existing_phrases:
                continue
            db.add_dictionary(r["phrase"], r["replacement"], bool(r["isSnippet"]))
            dict_count += 1

        hist_count = 0
        if include_history:
            rows = con.execute("""
                SELECT asrText, formattedText, timestamp, app, duration, numWords,
                       detectedLanguage, e2eLatency
                FROM History WHERE asrText IS NOT NULL AND isArchived=0""").fetchall()
            # Guard gegen Doppel-Import (z.B. Doppelklick auf "Importieren")
            if db.count_history(status="imported") == 0:
                batch = [{
                    "timestamp": _parse_ts(r["timestamp"]),
                    "asr_text": r["asrText"],
                    "formatted_text": r["formattedText"],
                    "language": r["detectedLanguage"],
                    "app": r["app"],
                    "duration_s": r["duration"],
                    "latency_ms": r["e2eLatency"],
                    "num_words": r["numWords"],
                    "status": "imported",
                } for r in rows]
                db.add_history_bulk(batch)   # eine Transaktion statt tausender Einzel-Commits
                hist_count = len(batch)
    finally:
        if con is not None:
            con.close()
        # Die Kopie enthaelt die KOMPLETTE Diktat-History im Klartext -
        # nicht im Temp-Ordner liegen lassen.
        shutil.rmtree(tmpdir, ignore_errors=True)
    log.info("Wispr-Import: %s Dictionary, %s History", dict_count, hist_count)
    return {"dictionary": dict_count, "history": hist_count}
