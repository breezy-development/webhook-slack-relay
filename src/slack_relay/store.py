"""SQLite delivery log: dedupes GitHub redeliveries and keeps failures for retry."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    id          TEXT PRIMARY KEY,          -- X-GitHub-Delivery
    event       TEXT NOT NULL,
    received_at TEXT NOT NULL,
    status      TEXT NOT NULL,             -- queued | delivered | dry_run | skipped | failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    message     TEXT                       -- Slack payload (JSON) when there is one
);
CREATE INDEX IF NOT EXISTS deliveries_status ON deliveries (status);
"""


@dataclass
class Delivery:
    id: str
    event: str
    received_at: str
    status: str
    attempts: int
    last_error: str | None
    message: dict | None


class DeliveryStore:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)

    def claim(self, delivery_id: str, event: str, message: dict | None) -> bool:
        """Record a new delivery. Returns False if this delivery id was already seen."""
        status = "queued" if message else "skipped"
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO deliveries (id, event, received_at, status, message)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    delivery_id,
                    event,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    status,
                    json.dumps(message) if message else None,
                ),
            )
            return cur.rowcount == 1

    def finish(self, delivery_id: str, status: str, attempts: int, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE deliveries SET status = ?, attempts = attempts + ?, last_error = ?"
                " WHERE id = ?",
                (status, attempts, error, delivery_id),
            )

    def get(self, delivery_id: str) -> Delivery | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,)).fetchone()
        return self._row(row) if row else None

    def by_status(self, status: str) -> list[Delivery]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliveries WHERE status = ? ORDER BY received_at", (status,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, limit: int = 20) -> list[Delivery]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM deliveries ORDER BY received_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> Delivery:
        return Delivery(
            id=row["id"],
            event=row["event"],
            received_at=row["received_at"],
            status=row["status"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            message=json.loads(row["message"]) if row["message"] else None,
        )
