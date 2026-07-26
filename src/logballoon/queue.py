"""SQLite-backed offline queue."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

# When over capacity, drop these kinds first (oldest within each kind).
# crash / user are retained preferentially over routine traffic.
_DROP_PRIORITY = ("event", "startup", "user", "crash")


class OfflineQueue:
    """Persist outbound messages until the server accepts them."""

    def __init__(self, db_path: Path, *, max_items: int = 1000) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._db_path = db_path
        self._max_items = max_items
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # closing() is required: `with sqlite3.connect(...)` commits but never
        # closes, which keeps the file handle open (breaks cleanup on Windows).
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, closing(self._connect()) as conn:
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
        """Append an item. If over capacity, drop low-priority oldest rows first."""
        now = time.time()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, closing(self._connect()) as conn:
            cur = conn.execute(
                "INSERT INTO queue (kind, payload, created_at, attempts) VALUES (?, ?, ?, 0)",
                (kind, body, now),
            )
            item_id = int(cur.lastrowid)
            row = conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()
            overflow = int(row["n"]) - self._max_items
            if overflow > 0:
                self._drop_overflow(conn, overflow)
            conn.commit()
            return item_id

    def _drop_overflow(self, conn: sqlite3.Connection, overflow: int) -> None:
        remaining = overflow
        for kind in _DROP_PRIORITY:
            if remaining <= 0:
                break
            rows = conn.execute(
                "SELECT id FROM queue WHERE kind = ? ORDER BY id ASC LIMIT ?",
                (kind, remaining),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM queue WHERE id IN ({placeholders})", ids)
            remaining -= len(ids)
        # Absolute last resort: drop oldest regardless of kind.
        if remaining > 0:
            conn.execute(
                "DELETE FROM queue WHERE id IN ("
                "SELECT id FROM queue ORDER BY id ASC LIMIT ?"
                ")",
                (remaining,),
            )

    def peek(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
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
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE queue SET attempts = attempts + 1 WHERE id = ?",
                (item_id,),
            )
            conn.commit()

    def delete(self, item_id: int) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM queue WHERE id = ?", (item_id,))
            conn.commit()

    def count(self) -> int:
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()
            return int(row["n"])
