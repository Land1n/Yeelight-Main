"""SQLite storage for users, managers, lamps, commands, modes and audit log.

The project targets a single-user prototype; this module deliberately uses the
Python standard library instead of an ORM.  All writes are short and guarded by
a lock, which is sufficient for a single-process FastAPI deployment.  Move to a
real database before scaling horizontally.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS managers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    version TEXT,
    created_at REAL NOT NULL,
    last_seen_at REAL,
    online INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS managers_user_name
    ON managers(user_id, name);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS pairing_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL,
    manager_id TEXT
);

CREATE TABLE IF NOT EXISTS lamps (
    manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    ip TEXT NOT NULL,
    name TEXT,
    model TEXT,
    online INTEGER,
    last_seen REAL,
    PRIMARY KEY (manager_id, ip)
);

CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    manager_id TEXT NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    ip TEXT,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    error_code TEXT,
    idempotency_key TEXT,
    created_at REAL NOT NULL,
    delivered_at REAL,
    completed_at REAL,
    timeout_seconds REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS commands_idempotency
    ON commands(manager_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS commands_created ON commands(created_at DESC);
CREATE INDEX IF NOT EXISTS commands_manager ON commands(manager_id, created_at DESC);

CREATE TABLE IF NOT EXISTS modes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    delay_seconds REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS modes_user_name ON modes(user_id, name);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    action TEXT NOT NULL,
    target TEXT,
    outcome TEXT NOT NULL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS audit_created ON audit_log(created_at DESC);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

FINAL_COMMAND_STATUSES = {
    "completed",
    "failed",
    "timed_out",
    "manager_unavailable",
    "cancelled",
}


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _command_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "manager_id": row["manager_id"],
        "action": row["action"],
        "ip": row["ip"],
        "params": _json_loads(row["params_json"], {}),
        "status": row["status"],
        "result": _json_loads(row["result_json"]),
        "error": row["error"],
        "error_code": row["error_code"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
        "completed_at": row["completed_at"],
        "timeout_seconds": row["timeout_seconds"],
    }


def _manager_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "version": row["version"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "online": bool(row["online"]),
    }


def _lamp_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "manager_id": row["manager_id"],
        "ip": row["ip"],
        "name": row["name"],
        "model": row["model"],
        "online": None if row["online"] is None else bool(row["online"]),
        "last_seen": row["last_seen"],
    }


def _mode_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "steps": _json_loads(row["steps_json"], []),
        "delay_seconds": row["delay_seconds"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.path) if str(self.path) != ":memory:" else ":memory:",
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Users and sessions
    # ------------------------------------------------------------------

    def count_users(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, password_hash: str) -> dict[str, Any]:
        user_id = new_id("usr_")
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO users(id, username, password_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, now),
            )
        return {
            "id": user_id,
            "username": username,
            "created_at": now,
        }

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return None if row is None else dict(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def get_first_user(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users ORDER BY created_at LIMIT 1"
            ).fetchone()
        return None if row is None else dict(row)

    def set_user_password(self, user_id: str, password_hash: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
            return cursor.rowcount > 0

    def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_token: str,
        expires_at: float,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        session_id = new_id("ses_")
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions(id, user_id, token_hash, csrf_token, "
                "created_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    token_hash,
                    csrf_token,
                    now,
                    expires_at,
                    (user_agent or "")[:300],
                ),
            )
        return {
            "id": session_id,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "created_at": now,
            "expires_at": expires_at,
        }

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT s.*, u.username FROM sessions s "
                "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= now:
                self._conn.execute(
                    "DELETE FROM sessions WHERE id = ?", (row["id"],)
                )
                self._conn.commit()
                return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "csrf_token": row["csrf_token"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "username": row["username"],
        }

    def delete_session(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def purge_expired_sessions(self) -> int:
        now = time.time()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (now,)
            )
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Manager pairing and management
    # ------------------------------------------------------------------

    def create_pairing_code(
        self, user_id: str, code_hash: str, ttl_seconds: float
    ) -> dict[str, Any]:
        code_id = new_id("pair_")
        now = time.time()
        expires = now + ttl_seconds
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO pairing_codes(id, user_id, code_hash, created_at, "
                "expires_at) VALUES (?, ?, ?, ?, ?)",
                (code_id, user_id, code_hash, now, expires),
            )
        return {
            "id": code_id,
            "created_at": now,
            "expires_at": expires,
        }

    def consume_pairing_code(
        self,
        *,
        code_hash: str,
        manager_name: str,
        manager_token_hash: str,
        version: str | None,
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT * FROM pairing_codes WHERE code_hash = ?",
                    (code_hash,),
                ).fetchone()
                if (
                    row is None
                    or row["used_at"] is not None
                    or float(row["expires_at"]) <= now
                ):
                    self._conn.rollback()
                    return None
                existing = self._conn.execute(
                    "SELECT 1 FROM managers WHERE user_id = ? AND name = ?",
                    (row["user_id"], manager_name),
                ).fetchone()
                if existing is not None:
                    self._conn.rollback()
                    raise ValueError("A manager with this name already exists")
                manager_id = new_id("mgr_")
                self._conn.execute(
                    "INSERT INTO managers(id, user_id, name, token_hash, version, "
                    "created_at, online) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (
                        manager_id,
                        row["user_id"],
                        manager_name,
                        manager_token_hash,
                        version,
                        now,
                    ),
                )
                self._conn.execute(
                    "UPDATE pairing_codes SET used_at = ?, manager_id = ? "
                    "WHERE id = ?",
                    (now, manager_id, row["id"]),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            manager_row = self._conn.execute(
                "SELECT * FROM managers WHERE id = ?", (manager_id,)
            ).fetchone()
        return _manager_dict(manager_row)

    def get_managers(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM managers WHERE user_id = ? ORDER BY name COLLATE NOCASE",
                (user_id,),
            ).fetchall()
        return [_manager_dict(row) for row in rows]

    def get_manager(
        self, manager_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._lock:
            if user_id is None:
                row = self._conn.execute(
                    "SELECT * FROM managers WHERE id = ?", (manager_id,)
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM managers WHERE id = ? AND user_id = ?",
                    (manager_id, user_id),
                ).fetchone()
        return None if row is None else _manager_dict(row)

    def get_manager_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM managers WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return None if row is None else _manager_dict(row)

    def set_manager_online(self, manager_id: str, online: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE managers SET online = ?, last_seen_at = ? WHERE id = ?",
                (1 if online else 0, time.time(), manager_id),
            )

    def mark_all_managers_offline(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE managers SET online = 0")

    def touch_manager(self, manager_id: str, version: str | None = None) -> None:
        with self._lock, self._conn:
            if version:
                self._conn.execute(
                    "UPDATE managers SET last_seen_at = ?, online = 1, version = ? "
                    "WHERE id = ?",
                    (time.time(), version, manager_id),
                )
            else:
                self._conn.execute(
                    "UPDATE managers SET last_seen_at = ?, online = 1 WHERE id = ?",
                    (time.time(), manager_id),
                )

    def delete_manager(self, manager_id: str, user_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM managers WHERE id = ? AND user_id = ?",
                (manager_id, user_id),
            )
            return cursor.rowcount > 0

    def replace_lamps(
        self, manager_id: str, lamps: Iterable[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        now = time.time()
        normalized: list[tuple[str, str | None, str | None, int | None]] = []
        for lamp in lamps:
            if not isinstance(lamp, dict):
                continue
            ip = str(lamp.get("ip", "")).strip()
            if not ip or len(ip) > 45:
                continue
            name = lamp.get("name")
            model = lamp.get("model")
            online = lamp.get("online")
            normalized.append(
                (
                    ip,
                    str(name)[:120] if name is not None else None,
                    str(model)[:120] if model is not None else None,
                    None if online is None else int(bool(online)),
                )
            )
        ips = {item[0] for item in normalized}
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT ip FROM lamps WHERE manager_id = ?", (manager_id,)
            ).fetchall()
            for row in existing:
                if row["ip"] not in ips:
                    self._conn.execute(
                        "DELETE FROM lamps WHERE manager_id = ? AND ip = ?",
                        (manager_id, row["ip"]),
                    )
            for ip, name, model, online in normalized:
                self._conn.execute(
                    "INSERT INTO lamps(manager_id, ip, name, model, online, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(manager_id, ip) DO UPDATE SET "
                    "name = excluded.name, model = excluded.model, "
                    "online = excluded.online, last_seen = excluded.last_seen",
                    (manager_id, ip, name, model, online, now),
                )
        return self.get_lamps(manager_id)

    def get_lamps(self, manager_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM lamps WHERE manager_id = ? ORDER BY ip",
                (manager_id,),
            ).fetchall()
        return [_lamp_dict(row) for row in rows]

    def get_lamp(self, manager_id: str, ip: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM lamps WHERE manager_id = ? AND ip = ?",
                (manager_id, ip),
            ).fetchone()
        return None if row is None else _lamp_dict(row)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def create_command(
        self,
        *,
        user_id: str,
        manager_id: str,
        action: str,
        ip: str | None,
        params: dict[str, Any],
        timeout_seconds: float,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        command_id = new_id("cmd_")
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO commands(id, user_id, manager_id, action, ip, "
                "params_json, status, idempotency_key, created_at, "
                "timeout_seconds) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    command_id,
                    user_id,
                    manager_id,
                    action,
                    ip,
                    _json_dumps(params),
                    idempotency_key,
                    now,
                    timeout_seconds,
                ),
            )
        return self.get_command(command_id)  # type: ignore[return-value]

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM commands WHERE id = ?", (command_id,)
            ).fetchone()
        return None if row is None else _command_dict(row)

    def get_command_for_user(
        self, command_id: str, user_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM commands WHERE id = ? AND user_id = ?",
                (command_id, user_id),
            ).fetchone()
        return None if row is None else _command_dict(row)

    def get_command_by_idempotency(
        self, manager_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM commands WHERE manager_id = ? AND idempotency_key = ?",
                (manager_id, idempotency_key),
            ).fetchone()
        return None if row is None else _command_dict(row)

    def list_commands(
        self,
        user_id: str,
        *,
        manager_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._lock:
            if manager_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM commands WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM commands WHERE user_id = ? AND manager_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, manager_id, limit),
                ).fetchall()
        return [_command_dict(row) for row in rows]

    def mark_command_delivered(self, command_id: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE commands SET status = 'delivered', delivered_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (now, command_id),
            )
        return self.get_command(command_id)

    def finish_command(
        self,
        command_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE commands SET status = ?, result_json = ?, error = ?, "
                "error_code = ?, completed_at = ? "
                "WHERE id = ? AND status IN ('pending', 'delivered')",
                (
                    status,
                    _json_dumps(result) if result is not None else None,
                    error,
                    error_code,
                    now,
                    command_id,
                ),
            )
        return self.get_command(command_id)

    def command_stats(self, user_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS count FROM commands "
                "WHERE user_id = ? GROUP BY status",
                (user_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def fail_inflight_commands(
        self, manager_id: str, *, error: str, error_code: str
    ) -> list[str]:
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM commands WHERE manager_id = ? "
                "AND status IN ('pending', 'delivered')",
                (manager_id,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                with self._conn:
                    self._conn.execute(
                        f"UPDATE commands SET status = 'manager_unavailable', "
                        f"error = ?, error_code = ?, completed_at = ? "
                        f"WHERE id IN ({placeholders})",
                        (error, error_code, now, *ids),
                    )
        return ids

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------

    def list_modes(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM modes WHERE user_id = ? ORDER BY name COLLATE NOCASE",
                (user_id,),
            ).fetchall()
        return [_mode_dict(row) for row in rows]

    def get_mode(self, mode_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM modes WHERE id = ? AND user_id = ?",
                (mode_id, user_id),
            ).fetchone()
        return None if row is None else _mode_dict(row)

    def get_mode_by_name(self, name: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM modes WHERE name = ? AND user_id = ?",
                (name, user_id),
            ).fetchone()
        return None if row is None else _mode_dict(row)

    def upsert_mode(
        self,
        *,
        user_id: str,
        name: str,
        steps: list[dict[str, Any]],
        delay_seconds: float,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM modes WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if row is None:
                mode_id = new_id("mode_")
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO modes(id, user_id, name, steps_json, "
                        "delay_seconds, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            mode_id,
                            user_id,
                            name,
                            _json_dumps(steps),
                            delay_seconds,
                            now,
                            now,
                        ),
                    )
            else:
                mode_id = row["id"]
                with self._conn:
                    self._conn.execute(
                        "UPDATE modes SET steps_json = ?, delay_seconds = ?, "
                        "updated_at = ? WHERE id = ?",
                        (_json_dumps(steps), delay_seconds, now, mode_id),
                    )
        return self.get_mode(mode_id, user_id)  # type: ignore[return-value]

    def delete_mode(self, mode_id: str, user_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM modes WHERE id = ? AND user_id = ?",
                (mode_id, user_id),
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Audit and metadata
    # ------------------------------------------------------------------

    def audit(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        action: str,
        target: str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_log(created_at, actor_type, actor_id, action, "
                "target, outcome, details_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    actor_type,
                    actor_id,
                    action,
                    target,
                    outcome,
                    _json_dumps(details) if details else None,
                ),
            )

    def list_audit(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return audit events created by this user or about their managers."""

        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_log WHERE actor_id = ? OR actor_id IN "
                "(SELECT id FROM managers WHERE user_id = ?) "
                "OR target IN (SELECT id FROM managers WHERE user_id = ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, user_id, user_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "actor_type": row["actor_type"],
                "actor_id": row["actor_id"],
                "action": row["action"],
                "target": row["target"],
                "outcome": row["outcome"],
                "details": _json_loads(row["details_json"], {}),
            }
            for row in rows
        ]

    def get_metadata(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
