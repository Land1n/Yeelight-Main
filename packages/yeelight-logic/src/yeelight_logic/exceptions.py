"""Typed exceptions shared by every part of ``yeelight-logic``.

All exceptions derive from :class:`YeelightLogicError`.  Each instance carries
an :class:`ErrorInfo` record so callers (the manager, local API, tests) can map
errors to stable codes instead of parsing messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorInfo:
    """Structured information about a library error."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class YeelightLogicError(Exception):
    """Base exception of the library."""

    def __init__(
        self,
        message: str,
        code: str = "logic_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.info = ErrorInfo(code=code, message=message, details=details)

    @property
    def code(self) -> str:
        return self.info.code


class CommandError(YeelightLogicError):
    """The command has an invalid format or requests an unsupported operation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="command_error", details=details)


class DeviceError(YeelightLogicError):
    """A lamp action could not be performed (network error or device refusal)."""

    def __init__(
        self,
        message: str,
        code: str = "device_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class StorageError(YeelightLogicError):
    """The list of lamps could not be loaded or saved."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="storage_error", details=details)


class DiscoveryError(YeelightLogicError):
    """Lamp discovery failed."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="discovery_error", details=details)


class ProvisioningError(YeelightLogicError):
    """Wi-Fi or LAN Control setup failed."""

    def __init__(
        self,
        message: str,
        code: str = "provisioning_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class LanControlError(ProvisioningError):
    """LAN Control could not be enabled."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="lan_control_error", details=details)


class UnsupportedModelError(ProvisioningError):
    """The detected lamp model does not support the requested setup operation."""

    def __init__(self, model: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            f"Model '{model}' does not support this provisioning operation.",
            code="unsupported_model",
            details=details,
        )


class ConnectionError(DeviceError):
    """A connection to the lamp could not be established."""

    def __init__(
        self,
        message: str,
        address: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="connection_error", details=details)
        self.address = address
