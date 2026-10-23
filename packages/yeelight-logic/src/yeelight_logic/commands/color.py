"""Brightness, RGB and colour-temperature commands."""

from __future__ import annotations

from ..bulb import Bulb
from ..exceptions import CommandError
from ..protocol import LightBulb
from ..types import CommandResult
from .base import Command, error_result, set_color_temperature


class SetBrightnessCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb, brightness: int) -> None:
        self._bulb = bulb
        self._brightness = brightness

    def execute(self) -> CommandResult:
        if not isinstance(self._brightness, int) or isinstance(
            self._brightness, bool
        ):
            return CommandResult(
                False, "Brightness must be an integer", error_code="command_error"
            )
        if not 1 <= self._brightness <= 100:
            return CommandResult(
                False,
                "Brightness must be between 1 and 100",
                error_code="command_error",
            )
        try:
            self._bulb.set_brightness(self._brightness)
            return CommandResult(
                True,
                f"Brightness set to {self._brightness}",
                data={"brightness": self._brightness},
            )
        except Exception as exc:
            return error_result(exc, "Failed to set brightness")


class SetColorCommand(Command):
    def __init__(
        self, bulb: Bulb | LightBulb, red: int, green: int, blue: int
    ) -> None:
        self._bulb = bulb
        self._red = red
        self._green = green
        self._blue = blue

    def execute(self) -> CommandResult:
        channels = (
            ("red", self._red),
            ("green", self._green),
            ("blue", self._blue),
        )
        for name, value in channels:
            if not isinstance(value, int) or isinstance(value, bool):
                return CommandResult(
                    False, f"{name} must be an integer", error_code="command_error"
                )
            if not 0 <= value <= 255:
                return CommandResult(
                    False,
                    f"{name} must be between 0 and 255",
                    error_code="command_error",
                )
        try:
            self._bulb.set_rgb(self._red, self._green, self._blue)
            return CommandResult(
                True,
                f"Color set to RGB({self._red}, {self._green}, {self._blue})",
                data={"rgb": [self._red, self._green, self._blue]},
            )
        except Exception as exc:
            return error_result(exc, "Failed to set color")


class SetColorTemperatureCommand(Command):
    def __init__(self, bulb: Bulb | LightBulb, temperature: int) -> None:
        self._bulb = bulb
        self._temperature = temperature

    def execute(self) -> CommandResult:
        if not isinstance(self._temperature, int) or isinstance(
            self._temperature, bool
        ):
            return CommandResult(
                False,
                "Colour temperature must be an integer",
                error_code="command_error",
            )
        if not 1700 <= self._temperature <= 6500:
            return CommandResult(
                False,
                "Colour temperature must be between 1700 and 6500 K",
                error_code="command_error",
            )
        try:
            set_color_temperature(self._bulb, self._temperature)
            return CommandResult(
                True,
                f"Color temperature set to {self._temperature} K",
                data={"color_temperature": self._temperature},
            )
        except Exception as exc:
            return error_result(exc, "Failed to set color temperature")
