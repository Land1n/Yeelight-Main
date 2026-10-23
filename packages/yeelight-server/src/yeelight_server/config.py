"""Server configuration loaded from environment variables.

Paths are resolved from the current working directory so the package works both
from a source checkout and after a normal ``pip install``.  The start scripts in
the repository change to the repository root before launching the server.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
    load_dotenv = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _path_from_env(name: str, default: str, base: Path) -> Path:
    raw = os.getenv(name, default).strip() or default
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path


def _load_env() -> Path:
    base = Path.cwd()
    env_file = base / ".env"
    if load_dotenv is not None and env_file.is_file():
        load_dotenv(env_file, override=False)
    return base


@dataclass(frozen=True)
class Settings:
    """Immutable server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    db_path: Path = field(default_factory=lambda: Path.cwd() / "data" / "server.db")
    admin_username: str = "admin"
    admin_password: str = ""
    session_ttl_seconds: int = 12 * 60 * 60
    secure_cookies: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    command_timeout_seconds: float = 15.0
    max_command_wait_seconds: float = 30.0
    heartbeat_interval_seconds: int = 20
    frontend_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "frontend"
    )
    legacy_modes_file: Path | None = field(
        default_factory=lambda: Path.cwd() / "data" / "modes.json"
    )
    manager_offline_grace_seconds: float = 45.0

    @classmethod
    def from_env(cls) -> "Settings":
        base = _load_env()
        project_root = Path(__file__).resolve().parents[4]
        if (
            project_root != base
            and (project_root / "packages" / "yeelight-server").is_dir()
            and load_dotenv is not None
            and (project_root / ".env").is_file()
        ):
            # Running from another directory inside a source checkout.
            load_dotenv(project_root / ".env", override=False)

        db_path = _path_from_env("YEELIGHT_SERVER_DB", "data/server.db", base)
        legacy_value = os.getenv(
            "YEELIGHT_SERVER_LEGACY_MODES_FILE", "data/modes.json"
        ).strip()
        legacy_path: Path | None = None
        if legacy_value:
            legacy_path = Path(legacy_value)
            if not legacy_path.is_absolute():
                legacy_path = base / legacy_path

        tls_cert = os.getenv("YEELIGHT_SERVER_TLS_CERT", "").strip() or None
        tls_key = os.getenv("YEELIGHT_SERVER_TLS_KEY", "").strip() or None
        if tls_cert and tls_key:
            cert_path = Path(tls_cert)
            key_path = Path(tls_key)
            if not cert_path.is_absolute():
                cert_path = base / cert_path
            if not key_path.is_absolute():
                key_path = base / key_path
            tls_cert, tls_key = str(cert_path), str(key_path)
        if bool(tls_cert) != bool(tls_key):
            raise ValueError(
                "YEELIGHT_SERVER_TLS_CERT and YEELIGHT_SERVER_TLS_KEY must be set together"
            )
        secure_cookies_default = bool(tls_cert) or _env_bool(
            "YEELIGHT_SERVER_SECURE_COOKIES", False
        )

        settings = cls(
            host=os.getenv("YEELIGHT_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_env_int("YEELIGHT_SERVER_PORT", 8000, 1, 65535),
            db_path=db_path,
            admin_username=os.getenv("YEELIGHT_SERVER_ADMIN_USER", "admin").strip()
            or "admin",
            admin_password=os.getenv("YEELIGHT_SERVER_ADMIN_PASSWORD", ""),
            session_ttl_seconds=_env_int(
                "YEELIGHT_SERVER_SESSION_TTL_SECONDS", 43200, 300, 30 * 24 * 3600
            ),
            secure_cookies=_env_bool(
                "YEELIGHT_SERVER_SECURE_COOKIES", secure_cookies_default
            ),
            tls_cert=tls_cert,
            tls_key=tls_key,
            command_timeout_seconds=_env_float(
                "YEELIGHT_SERVER_COMMAND_TIMEOUT_SECONDS", 15.0, 1.0, 120.0
            ),
            max_command_wait_seconds=_env_float(
                "YEELIGHT_SERVER_MAX_COMMAND_WAIT_SECONDS", 30.0, 0.0, 60.0
            ),
            heartbeat_interval_seconds=_env_int(
                "YEELIGHT_SERVER_HEARTBEAT_SECONDS", 20, 5, 120
            ),
            legacy_modes_file=legacy_path,
            manager_offline_grace_seconds=_env_float(
                "YEELIGHT_SERVER_MANAGER_GRACE_SECONDS", 45.0, 10.0, 600.0
            ),
        )
        if any(ch.isspace() for ch in settings.admin_username):
            raise ValueError("YEELIGHT_SERVER_ADMIN_USER must not contain spaces")
        return settings

    @property
    def websocket_path(self) -> str:
        return "/api/v1/managers/ws"

    def validate_for_run(self) -> None:
        if self.admin_password and len(self.admin_password) < 8:
            raise RuntimeError(
                "YEELIGHT_SERVER_ADMIN_PASSWORD must contain at least 8 characters."
            )
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.tls_cert:
            import logging

            logging.getLogger(__name__).warning(
                "Server is bound beyond localhost without TLS. "
                "Use a reverse proxy with HTTPS or configure TLS certificates."
            )

    def describe(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "tls": bool(self.tls_cert),
            "db_path": str(self.db_path),
        }


def generate_password(length: int = 24) -> str:
    """Generate a URL-safe password for initial setup scripts."""

    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
