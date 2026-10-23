"""Controller device-list commands."""

from __future__ import annotations

from ..controller import YeelightController
from ..types import CommandResult
from .base import Command, error_result


class AddBulbCommand(Command):
    def __init__(self, controller: YeelightController, address: str) -> None:
        self._controller = controller
        self._address = address

    def execute(self) -> CommandResult:
        try:
            address = self._controller.add(self._address)
            return CommandResult(
                True, f"Added lamp {address}", data={"ip": address}
            )
        except Exception as exc:
            return error_result(exc, "Failed to add lamp")


class RemoveBulbCommand(Command):
    def __init__(self, controller: YeelightController, address: str) -> None:
        self._controller = controller
        self._address = address

    def execute(self) -> CommandResult:
        try:
            address = self._controller.remove(self._address)
            return CommandResult(
                True, f"Removed lamp {address}", data={"ip": address}
            )
        except Exception as exc:
            return error_result(exc, "Failed to remove lamp")


class ListBulbsCommand(Command):
    def __init__(self, controller: YeelightController) -> None:
        self._controller = controller

    def execute(self) -> CommandResult:
        bulbs = self._controller.known_bulbs()
        return CommandResult(
            True, f"Known lamps: {len(bulbs)}", data={"bulbs": bulbs}
        )
