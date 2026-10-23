"""Power and status commands."""

from __future__ import annotations

from typing import Any

from ..bulb import Bulb
from ..protocol import LightBulb
from ..types import CommandResult
from .base import Command, error_result, read_properties


class TurnOnCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb) -> None:
        self._bulb = bulb

    def execute(self) -> CommandResult:
        try:
            self._bulb.turn_on()
            return CommandResult(True, "Lamp turned on", data={"power": "on"})
        except Exception as exc:
            return error_result(exc, "Failed to turn on")


class TurnOffCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb) -> None:
        self._bulb = bulb

    def execute(self) -> CommandResult:
        try:
            self._bulb.turn_off()
            return CommandResult(True, "Lamp turned off", data={"power": "off"})
        except Exception as exc:
            return error_result(exc, "Failed to turn off")


class ToggleCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb) -> None:
        self._bulb = bulb

    def execute(self) -> CommandResult:
        try:
            target: Any = self._bulb
            toggle = getattr(target, "toggle", None)
            if callable(toggle):
                toggle()
            else:
                power = read_properties(target).get("power")
                if power == "on":
                    target.turn_off()
                elif power == "off":
                    target.turn_on()
                else:
                    return CommandResult(
                        False,
                        f"Lamp returned an invalid power state: {power!r}",
                        error_code="device_error",
                    )
            power = read_properties(self._bulb).get("power", "unknown")
            return CommandResult(
                True, f"Lamp toggled to {power}", data={"power": power}
            )
        except Exception as exc:
            return error_result(exc, "Failed to toggle")


class GetStatusCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb) -> None:
        self._bulb = bulb

    def execute(self) -> CommandResult:
        try:
            props = read_properties(self._bulb)
            address = getattr(self._bulb, "address", None)
            data = {"properties": props}
            if address:
                data["ip"] = address
            return CommandResult(True, "Status retrieved", data=data)
        except Exception as exc:
            return error_result(exc, "Failed to get status")
