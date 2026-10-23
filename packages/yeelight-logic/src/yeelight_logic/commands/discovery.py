"""Discovery command."""

from __future__ import annotations

from ..controller import YeelightController
from ..types import CommandResult
from .base import Command, error_result


class DiscoverBulbsCommand(Command):
    def __init__(self, controller: YeelightController) -> None:
        self._controller = controller

    def execute(self) -> CommandResult:
        try:
            bulbs = self._controller.discover()
            return CommandResult(
                True,
                f"Discovered {len(bulbs)} bulb(s)",
                data={"bulbs": bulbs},
            )
        except Exception as exc:
            return error_result(exc, "Discovery failed")
