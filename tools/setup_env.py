"""Prepare the repository ``.env`` file for a first run.

The script preserves existing values and comments, appends keys added by the
new three-package layout, and generates an administrator password only when the
database has no users yet.  The password is written to ``.env`` and is never
printed to the console.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
PASSWORD_KEY = "YEELIGHT_SERVER_ADMIN_PASSWORD"
OBSOLETE_KEYS = (
    "YEELIGHT_HOST",
    "YEELIGHT_PORT",
    "YEELIGHT_API_TOKEN",
    "YEELIGHT_BULBS",
    "YEELIGHT_POLL_INTERVAL_SECONDS",
    "YEELIGHT_UNRESPONSIVE_TIMEOUT_SECONDS",
    "YEELIGHT_MODES_FILE",
    "YEELIGHT_BULBS_FILE",
)
PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_password(length: int = 24) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _key_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(key)}\s*=")


def get_value(lines: list[str], key: str) -> str:
    pattern = _key_pattern(key)
    value = ""
    for line in lines:
        if pattern.match(line):
            value = _clean_value(line.split("=", 1)[1])
    return value


def set_value(lines: list[str], key: str, value: str) -> list[str]:
    """Replace the first occurrence and drop duplicate assignments."""

    pattern = _key_pattern(key)
    result: list[str] = []
    replaced = False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                result.append(f"{key}={value}")
                replaced = True
            continue
        result.append(line)
    if not replaced:
        result.append(f"{key}={value}")
    return result


def _database_path(lines: list[str]) -> Path:
    raw = get_value(lines, "YEELIGHT_SERVER_DB") or "data/server.db"
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _database_has_users(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return bool(row and int(row[0]) > 0)
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def main() -> int:
    if not EXAMPLE.is_file():
        print(f"Не найден шаблон {EXAMPLE}", file=sys.stderr)
        return 1

    if ENV_FILE.is_file():
        text = ENV_FILE.read_text(encoding="utf-8")
    else:
        text = EXAMPLE.read_text(encoding="utf-8")
        print("Создан .env на основе .env.example.")

    lines = text.splitlines()
    example_lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    existing_keys = {
        line.split("=", 1)[0].strip()
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    added: list[str] = []
    for line in example_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key not in existing_keys:
            lines.append(line)
            existing_keys.add(key)
            added.append(key)
    if added:
        print("Добавлены новые ключи: " + ", ".join(added))

    database = _database_path(lines)
    has_users = _database_has_users(database)
    password = get_value(lines, PASSWORD_KEY)
    if has_users:
        print(
            f"База {database} уже содержит пользователей; "
            "пароль из .env для входа не используется."
        )
    elif password:
        print("Пароль администратора уже задан в .env.")
    else:
        lines = set_value(lines, PASSWORD_KEY, _new_password())
        print(
            "Сгенерирован пароль администратора и записан в .env. "
            "Откройте .env, чтобы узнать имя пользователя и пароль."
        )

    obsolete = [key for key in OBSOLETE_KEYS if key in existing_keys]
    if obsolete:
        print(
            "Устаревшие ключи оставлены без изменений и не используются: "
            + ", ".join(obsolete)
        )

    content = "\n".join(lines).rstrip() + "\n"
    temporary = ENV_FILE.with_name(f".{ENV_FILE.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, ENV_FILE)
    if os.name != "nt":
        try:
            os.chmod(ENV_FILE, 0o600)
        except OSError:
            pass

    print(f"Файл настроек: {ENV_FILE}")
    print("Проверьте .env перед первым запуском сервера.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
