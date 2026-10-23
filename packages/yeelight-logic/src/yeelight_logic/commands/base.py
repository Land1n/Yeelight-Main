"""Command Pattern contract and helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..exceptions import YeelightLogicError
from ..types import CommandResult


@dataclass(frozen=True)
class CommandOutcome:
    """Low-level command outcome (kept as an alias for compatibility)."""

    result: CommandResult


def error_result(exc: Exception, fallback: str) -> CommandResult:
    """Convert a typed library error into a stable command result."""

    if isinstance(exc, YeelightLogicError):
        return CommandResult(False, str(exc), error_code=exc.info.code)
    return CommandResult(False, f"{fallback}: {exc}", error_code="device_error")


def read_properties(target: Any) -> dict[str, Any]:
    """Read properties from either a :class:`Bulb` wrapper or a raw adapter."""

    get_status = getattr(target, "get_status", None)
    if callable(get_status):
        status = get_status()
        if isinstance(status, dict) and isinstance(status.get("properties"), dict):
            return dict(status["properties"])
        if isinstance(status, dict):
            return status
    get_properties = getattr(target, "get_properties", None)
    if not callable(get_properties):
        raise AttributeError("Lamp target does not expose get_properties()")
    return dict(get_properties())


def set_color_temperature(target: Any, temperature: int) -> Any:
    method = getattr(target, "set_color_temperature", None)
    if callable(method):
        return method(temperature)
    method = getattr(target, "set_color_temp", None)
    if callable(method):
        return method(temperature)
    raise AttributeError("Lamp target does not expose colour-temperature setup")


class Command(ABC):
    """Base class for all commands."""

    @abstractmethod
    def execute(self) -> CommandResult:
        """Execute the command and return a structured result."""
