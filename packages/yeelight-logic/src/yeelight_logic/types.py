"""Public data types returned by ``yeelight-logic``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BulbInfo:
    """Information about a discovered or known lamp."""

    ip: str
    port: int = 55443
    model: str | None = None
    name: str | None = None
    power: str | None = None
    brightness: int | None = None
    color_mode: str | None = None
    color_temperature: int | None = None
    rgb: tuple[int, int, int] | None = None
    online: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "model": self.model,
            "name": self.name,
            "power": self.power,
            "brightness": self.brightness,
            "color_mode": self.color_mode,
            "color_temperature": self.color_temperature,
            "rgb": list(self.rgb) if self.rgb else None,
            "online": self.online,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class CommandResult:
    """Uniform result of an executed command."""

    ok: bool
    message: str
    data: dict[str, Any] | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "data": self.data,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ProvisioningResult:
    """Outcome of Wi-Fi / LAN Control setup.

    ``wifi_status`` and ``lan_control_status`` are intentionally separate:
    Wi-Fi may succeed while LAN Control remains unconfirmed.
    """

    wifi_status: str
    wifi_message: str
    wifi_error: str | None = None
    lan_control_status: str = "not_requested"
    lan_control_message: str = "LAN Control was not requested."
    lan_control_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "wifi_status": self.wifi_status,
            "wifi_message": self.wifi_message,
            "wifi_error": self.wifi_error,
            "lan_control_status": self.lan_control_status,
            "lan_control_message": self.lan_control_message,
            "lan_control_error": self.lan_control_error,
        }
