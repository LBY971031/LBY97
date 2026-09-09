from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/app.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly_report (
    hour_start   TEXT    NOT NULL,
    version      INTEGER NOT NULL,
    generated_at TEXT    NOT NULL,
    superseded   INTEGER NOT NULL DEFAULT 0,
    payload      TEXT    NOT NULL,
    PRIMARY KEY (hour_start, version)
);
CREATE INDEX IF NOT EXISTS idx_hour ON hourly_report(hour_start, superseded);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save(conn: sqlite3.Connection, payload: dict) -> int:
    """Append a new version of one hour's report. Never overwrites."""
    hour = payload["hour_start"]
    prev = conn.execute(
        "SELECT MAX(version) FROM hourly_report WHERE hour_start = ?", (hour,)
    ).fetchone()[0]
    version = (prev or 0) + 1
    payload = dict(payload, version=version)
    conn.execute(
        "UPDATE hourly_report SET superseded = 1 WHERE hour_start = ?", (hour,))
    conn.execute(
        "INSERT INTO hourly_report (hour_start, version, generated_at, payload)"
        " VALUES (?, ?, ?, ?)",
        (hour, version, payload["generated_at"],
         json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    return version


def load(conn, hour_start: str, version: int | None = None) -> dict | None:
    if version is None:
        sql = ("SELECT payload FROM hourly_report"
               " WHERE hour_start = ? AND superseded = 0")
        args = (hour_start,)
    else:
        sql = "SELECT payload FROM hourly_report WHERE hour_start = ? AND version = ?"
        args = (hour_start, version)
    row = conn.execute(sql, args).fetchone()
    return json.loads(row[0]) if row else None


def load_range(conn, ts_from: str, ts_to: str) -> list[dict]:
    rows = conn.execute(
        "SELECT payload FROM hourly_report"
        " WHERE hour_start >= ? AND hour_start < ? AND superseded = 0"
        " ORDER BY hour_start", (ts_from, ts_to)).fetchall()
    return [json.loads(r[0]) for r in rows]
