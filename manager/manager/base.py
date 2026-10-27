"""Константы и утилиты manager: без состояния, без связи с лампами."""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from pathlib import Path

# Прошивка отвечает "client quota exceeded" при частых командах (около 60 в минуту).
PACE_SECONDS = 1.05
MAX_MODE_FAILURES = 10
MAX_UNDO = 20
LOG_LINES = 200
DEFAULT_CONFIG = {
    "server_url": "",
    "access_key": "",
    "poll_interval": 1.0,
    "monitor_interval": 10,
    "offline_timeout": 60,
}


def bundle_dir() -> Path:
    """Папка с default_modes.json: рядом с модулем или внутри PyInstaller-сборки."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def data_dir() -> Path:
    """Папка с config.json, bulbs.json, modes.json: рядом с exe или в текущей папке."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def read_json(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def valid_ipv4(value):
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except ValueError as ex:
        raise ValueError(f"неверный IPv4-адрес: {value!r}") from ex
