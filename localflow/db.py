"""SQLite-Persistenz: History und Dictionary (inkl. Snippets).

Schema angelehnt an Wispr Flows flow.sqlite, reduziert auf das Wesentliche.
"""

import logging
import os
import sqlite3
import threading
import time
import uuid

from .settings import APP_DIR

log = logging.getLogger("localflow.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    asr_text TEXT,
    formatted_text TEXT,
    pasted_text TEXT,
    language TEXT,
    app TEXT,
    window_title TEXT,
    duration_s REAL,
    latency_ms REAL,
    stt_ms REAL,
    cleanup_ms REAL,
    num_words INTEGER,
    status TEXT DEFAULT 'ok'
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON history(timestamp DESC);

CREATE TABLE IF NOT EXISTS dictionary (
    id TEXT PRIMARY KEY,
    phrase TEXT NOT NULL,
    replacement TEXT,
    is_snippet INTEGER DEFAULT 0,
    created_at REAL,
    last_used REAL,
    frequency_used INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(APP_DIR, "localflow.sqlite")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._local = threading.local()
        with self._conn() as con:
            con.executescript(SCHEMA)
            # Breadcrumb fuer die Diagnose: Datenordner + Eintragszahl beim
            # Start. Faellt die Zahl unerwartet (z.B. weil die App aus einem
            # sandboxed Kontext mit umgeleitetem %APPDATA% gestartet wurde und
            # so auf einen anderen, leeren Datenordner zeigt), steht das
            # sofort im Log statt tagelang unbemerkt zu bleiben.
            try:
                n = con.execute("SELECT COUNT(*) FROM history").fetchone()[0]
                log.info("DB bereit: %d History-Eintraege in %s", n, self.path)
            except sqlite3.Error:
                log.debug("History-Zaehlung beim Start fehlgeschlagen", exc_info=True)

    def _conn(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            self._local.con = con
        return con

    # --- History ---

    def add_history(self, **kw) -> str:
        hid = str(uuid.uuid4())
        with self._conn() as con:
            con.execute(
                """INSERT INTO history (id, timestamp, asr_text, formatted_text, pasted_text,
                       language, app, window_title, duration_s, latency_ms, stt_ms, cleanup_ms,
                       num_words, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hid, kw.get("timestamp", time.time()), kw.get("asr_text"),
                 kw.get("formatted_text"), kw.get("pasted_text"), kw.get("language"),
                 kw.get("app"), kw.get("window_title"), kw.get("duration_s"),
                 kw.get("latency_ms"), kw.get("stt_ms"), kw.get("cleanup_ms"),
                 kw.get("num_words"), kw.get("status", "ok")))
        return hid

    # Nur die vom Frontend/Code tatsaechlich genutzten Spalten - kein SELECT *
    # (pasted_text/window_title etc. werden nie gelesen, blaehen den Payload).
    _HIST_COLS = ("id, timestamp, asr_text, formatted_text, language, app, "
                  "latency_ms, stt_ms, cleanup_ms")

    def get_history(self, limit: int = 100, offset: int = 0, search: str | None = None):
        q = f"SELECT {self._HIST_COLS} FROM history"
        args: list = []
        if search:
            q += " WHERE asr_text LIKE ? OR formatted_text LIKE ? OR app LIKE ?"
            args += [f"%{search}%"] * 3
        q += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [dict(r) for r in self._conn().execute(q, args)]

    def get_stats(self) -> dict:
        con = self._conn()
        # "Zeit gespart": Tippzeit-Schaetzung (40 Woerter/min = 1,5 s/Wort,
        # uebliche Durchschnitts-Tippgeschwindigkeit) minus tatsaechliche
        # Sprechdauer, pro Diktat bei 0 gedeckelt (kurze, langsam gesprochene
        # Diktate "kosten" nichts).
        row = con.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(num_words),0) words,
                      COALESCE(AVG(latency_ms),0) avg_latency,
                      COALESCE(SUM(duration_s),0) total_audio_s,
                      COALESCE(SUM(MAX(COALESCE(num_words,0) * 1.5
                                       - COALESCE(duration_s,0), 0)), 0) time_saved_s
               FROM history WHERE status IN ('ok','imported')""").fetchone()
        # Lokale Mitternacht (nicht UTC) - passt zum "Heute"-Label im Frontend.
        import time as _t
        local_midnight = _t.mktime(_t.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        # Gleicher Status-Filter wie oben - sonst zaehlen error/empty-Zeilen
        # (und frisch importierte Wispr-Eintraege mit heutigem Timestamp)
        # in "Woerter heute" mit.
        today = con.execute(
            """SELECT COALESCE(SUM(num_words),0) w FROM history
               WHERE timestamp >= ? AND status IN ('ok','imported')""",
            (local_midnight,)).fetchone()
        return {"dictations": row["n"], "total_words": row["words"],
                "avg_latency_ms": row["avg_latency"], "total_audio_s": row["total_audio_s"],
                "time_saved_s": row["time_saved_s"], "words_today": today["w"]}

    def add_history_bulk(self, rows: list[dict]):
        """Viele History-Eintraege in EINER Transaktion (Import)."""
        params = [
            (str(uuid.uuid4()), r.get("timestamp", time.time()), r.get("asr_text"),
             r.get("formatted_text"), r.get("pasted_text"), r.get("language"),
             r.get("app"), r.get("window_title"), r.get("duration_s"),
             r.get("latency_ms"), r.get("stt_ms"), r.get("cleanup_ms"),
             r.get("num_words"), r.get("status", "ok"))
            for r in rows
        ]
        with self._conn() as con:
            con.executemany(
                """INSERT INTO history (id, timestamp, asr_text, formatted_text, pasted_text,
                       language, app, window_title, duration_s, latency_ms, stt_ms, cleanup_ms,
                       num_words, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", params)

    def delete_history(self, hid: str):
        with self._conn() as con:
            con.execute("DELETE FROM history WHERE id=?", (hid,))

    def count_history(self, status: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM history"
        args: list = []
        if status is not None:
            q += " WHERE status=?"
            args.append(status)
        return self._conn().execute(q, args).fetchone()[0]

    # --- Dictionary ---

    def add_dictionary(self, phrase: str, replacement: str | None = None,
                       is_snippet: bool = False) -> str:
        did = str(uuid.uuid4())
        with self._conn() as con:
            con.execute(
                """INSERT INTO dictionary (id, phrase, replacement, is_snippet, created_at)
                   VALUES (?,?,?,?,?)""",
                (did, phrase, replacement or None, int(is_snippet), time.time()))
        return did

    def get_dictionary(self, include_deleted: bool = False):
        q = "SELECT * FROM dictionary"
        if not include_deleted:
            q += " WHERE is_deleted=0"
        q += " ORDER BY created_at DESC"
        return [dict(r) for r in self._conn().execute(q)]

    def update_dictionary(self, did: str, **kw):
        allowed = {"phrase", "replacement", "is_snippet", "is_deleted"}
        sets = {k: v for k, v in kw.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        with self._conn() as con:
            con.execute(f"UPDATE dictionary SET {cols} WHERE id=?", (*sets.values(), did))

    def mark_dictionary_used(self, did: str):
        with self._conn() as con:
            con.execute(
                "UPDATE dictionary SET last_used=?, frequency_used=frequency_used+1 WHERE id=?",
                (time.time(), did))
