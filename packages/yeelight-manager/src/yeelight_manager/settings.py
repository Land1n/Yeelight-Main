"""Manager configuration and local state paths."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - declared dependency
    load_dotenv = None


def _default_home() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "YeelightManager"


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


def normalize_server_url(value: str) -> str:
    """Validate and canonicalise the relay server URL."""

    value = (value or "").strip()
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Server URL must look like http://host:8000 or https://host (no path)"
        )
    port = parts.port
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}"


def websocket_url(server_url: str, path: str = "/api/v1/managers/ws") -> str:
    parts = urlsplit(normalize_server_url(server_url))
    scheme = "wss" if parts.scheme == "https" else "ws"
    host = parts.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parts.port
    netloc = host if port is None else f"{host}:{port}"
    return f"{scheme}://{netloc}{path}"


@dataclass(frozen=True)
class ManagerSettings:
    home: Path = field(default_factory=_default_home)
    server_url: str = "http://127.0.0.1:8000"
    manager_name: str = field(
        default_factory=lambda: os.getenv("YEELIGHT_MANAGER_NAME", "").strip()
        or socket.gethostname()
        or "Yeelight Manager"
    )
    local_api_enabled: bool = True
    local_api_host: str = "127.0.0.1"
    local_api_port: int = 8765
    ui_enabled: bool = True
    poll_interval_seconds: float = 30.0
    discovery_timeout_seconds: float = 2.0
    command_timeout_seconds: float = 30.0
    verify_tls: bool = True
    log_level: str = "INFO"

    @property
    def state_file(self) -> Path:
        return self.home / "state.json"

    @property
    def token_file(self) -> Path:
        return self.home / "token.bin"

    @property
    def bulbs_file(self) -> Path:
        return self.home / "bulbs.json"

    @property
    def websocket_path(self) -> str:
        return "/api/v1/managers/ws"

    @classmethod
    def from_env(cls) -> "ManagerSettings":
        base = Path.cwd()
        env_file = base / ".env"
        if load_dotenv is not None and env_file.is_file():
            load_dotenv(env_file, override=False)
        home_value = os.getenv("YEELIGHT_MANAGER_HOME", "").strip()
        home = Path(home_value).expanduser() if home_value else _default_home()
        if not home.is_absolute():
            home = base / home
        server_url = normalize_server_url(
            os.getenv("YEELIGHT_SERVER_URL", "http://127.0.0.1:8000")
        )
        local_host = os.getenv("YEELIGHT_MANAGER_LOCAL_HOST", "127.0.0.1").strip()
        if local_host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(
                "YEELIGHT_MANAGER_LOCAL_HOST must be a loopback address "
                "(127.0.0.1, ::1 or localhost)"
            )
        return cls(
            home=home,
            server_url=server_url,
            manager_name=os.getenv("YEELIGHT_MANAGER_NAME", "").strip()
            or socket.gethostname()
            or "Yeelight Manager",
            local_api_enabled=_env_bool("YEELIGHT_MANAGER_LOCAL_API", True),
            local_api_host=local_host,
            local_api_port=_env_int("YEELIGHT_MANAGER_LOCAL_PORT", 8765, 1, 65535),
            ui_enabled=_env_bool("YEELIGHT_MANAGER_UI", True),
            poll_interval_seconds=_env_float(
                "YEELIGHT_MANAGER_POLL_SECONDS", 30.0, 5.0, 3600.0
            ),
            discovery_timeout_seconds=_env_float(
                "YEELIGHT_MANAGER_DISCOVERY_TIMEOUT_SECONDS", 2.0, 0.5, 30.0
            ),
            command_timeout_seconds=_env_float(
                "YEELIGHT_MANAGER_COMMAND_TIMEOUT_SECONDS", 30.0, 5.0, 120.0
            ),
            verify_tls=_env_bool("YEELIGHT_MANAGER_VERIFY_TLS", True),
            log_level=os.getenv("YEELIGHT_MANAGER_LOG_LEVEL", "INFO").upper(),
        )


__all__ = [
    "ManagerSettings",
    "normalize_server_url",
    "websocket_url",
]
