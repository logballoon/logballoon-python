"""SQLite-backed offline queue."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class OfflineQueue:
    """Persist outbound messages until the server accepts them."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def enqueue(self, kind: str, payload: dict[str, Any]) -> int:
        now = time.time()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO queue (kind, payload, created_at, attempts) VALUES (?, ?, ?, 0)",
                (kind, body, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def peek(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, payload, created_at, attempts "
                "FROM queue ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "payload": json.loads(row["payload"]),
                    "created_at": row["created_at"],
                    "attempts": row["attempts"],
                }
            )
        return items

    def mark_attempt(self, item_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE queue SET attempts = attempts + 1 WHERE id = ?",
                (item_id,),
            )
            conn.commit()

    def delete(self, item_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM queue WHERE id = ?", (item_id,))
            conn.commit()

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()
            return int(row["n"])
