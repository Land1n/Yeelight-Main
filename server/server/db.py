"""SQLite-хранилище: очередь действий и последний снимок состояния manager."""

from __future__ import annotations

import json
import sqlite3
import threading
import time


class Store:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated REAL NOT NULL
            );
            """
        )

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def add_action(self, payload: dict) -> int:
        cur = self._exec(
            "INSERT INTO actions (payload, status, created) VALUES (?, 'pending', ?)",
            (json.dumps(payload, ensure_ascii=False), time.time()),
        )
        return cur.lastrowid

    def get_action(self, action_id: int):
        row = self._exec("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "status": row["status"],
            "result": json.loads(row["result"]) if row["result"] else None,
        }

    def take_pending(self) -> list[dict]:
        """Вернуть ожидающие действия и пометить их как отправленные."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload FROM actions WHERE status = 'pending' ORDER BY id"
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                marks = ",".join("?" * len(ids))
                self._conn.execute(f"UPDATE actions SET status = 'sent' WHERE id IN ({marks})", ids)
            self._conn.commit()
        return [{**json.loads(row["payload"]), "id": row["id"]} for row in rows]

    def apply_results(self, results: list[dict]):
        with self._lock:
            for item in results:
                status = "done" if item["ok"] else "error"
                self._conn.execute(
                    "UPDATE actions SET status = ?, result = ? WHERE id = ?",
                    (status, json.dumps({"ok": item["ok"], "message": item["message"]},
                                        ensure_ascii=False), item["id"]),
                )
            self._conn.commit()

    def save_state(self, payload: dict):
        self._exec(
            "INSERT INTO state (id, payload, updated) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated = excluded.updated",
            (json.dumps(payload, ensure_ascii=False), time.time()),
        )

    def load_state(self):
        row = self._exec("SELECT payload, updated FROM state WHERE id = 1").fetchone()
        if row is None:
            return None, None
        return json.loads(row["payload"]), row["updated"]
