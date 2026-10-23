"""Cyclic lighting modes: validation, persistence facade and executor."""

from __future__ import annotations

import asyncio
import json
import math
import re
import shlex
from pathlib import Path
from typing import Any

from ..storage import Database
from .commands import CommandService, CommandServiceError

MODE_ACTIONS = frozenset(
    {"on", "off", "toggle", "status", "brightness", "color", "temp"}
)
MIN_DELAY_SECONDS = 0.1
MAX_DELAY_SECONDS = 3600.0
MAX_MODE_FAILURES = 10


def _parse_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def normalize_step(step: Any) -> dict[str, Any]:
    """Normalize a mode task to ``{"action": ..., "values": [...]}``."""

    if not isinstance(step, dict):
        raise ValueError("Mode contains an invalid task")
    action = step.get("action")
    if action not in MODE_ACTIONS:
        raise ValueError(f"Unsupported task: {action}")
    values = step.get("values", [])
    if not isinstance(values, list):
        raise ValueError("Task values must be a list")
    expected = (
        3
        if action == "color"
        else 1
        if action in {"brightness", "temp"}
        else 0
    )
    if len(values) != expected:
        raise ValueError(f"Invalid values for task: {action}")
    if action == "brightness":
        values = [_parse_int(values[0], "brightness", 1, 100)]
    elif action == "temp":
        values = [_parse_int(values[0], "temperature", 1700, 6500)]
    elif action == "color":
        values = [
            _parse_int(value, channel, 0, 255)
            for value, channel in zip(values, ("red", "green", "blue"))
        ]
    return {"action": action, "values": values}


def normalize_delay(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Mode delay must be a number")
    try:
        delay = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mode delay must be a number") from exc
    if not math.isfinite(delay) or not MIN_DELAY_SECONDS <= delay <= MAX_DELAY_SECONDS:
        raise ValueError(
            f"Mode delay must be between {MIN_DELAY_SECONDS} and "
            f"{MAX_DELAY_SECONDS:g} seconds"
        )
    return delay


def legacy_steps(commands: Any) -> list[dict[str, Any]]:
    """Convert the old line-based mode format to typed steps."""

    if not isinstance(commands, list):
        raise ValueError("Legacy mode must contain a list of commands")
    steps = []
    for command in commands:
        parts = shlex.split(str(command))
        if len(parts) < 2:
            raise ValueError("Legacy mode contains an invalid command")
        action = parts[0]
        args = parts[2:]
        if action == "color" and len(args) == 1 and re.fullmatch(
            r"#?[0-9a-fA-F]{6}", args[0]
        ):
            rgb = int(args[0].lstrip("#"), 16)
            args = [(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255]
        elif action == "color" and len(args) == 3:
            args = [int(value) for value in args]
        elif args:
            args = [int(args[0]) if str(args[0]).isdigit() else args[0]]
        steps.append({"action": action, "values": args})
    return steps


def step_to_command(step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map a stored mode step to a typed remote action."""

    action = step["action"]
    values = step["values"]
    if action == "on":
        return "power", {"state": "on"}
    if action == "off":
        return "power", {"state": "off"}
    if action == "toggle":
        return "power", {"state": "toggle"}
    if action == "status":
        return "status", {}
    if action == "brightness":
        return "brightness", {"value": values[0]}
    if action == "color":
        return "color", {"rgb": values}
    if action == "temp":
        return "color_temperature", {"value": values[0]}
    raise ValueError(f"Unsupported mode step: {action}")


class ModeService:
    """Execute modes by relaying typed commands to a manager."""

    def __init__(self, db: Database, commands: CommandService) -> None:
        self.db = db
        self.commands = commands
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._runtime: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_modes(self, user_id: str) -> list[dict[str, Any]]:
        modes = self.db.list_modes(user_id)
        return [self._with_runtime(mode) for mode in modes]

    def get_mode(self, mode_id: str, user_id: str) -> dict[str, Any] | None:
        mode = self.db.get_mode(mode_id, user_id)
        return None if mode is None else self._with_runtime(mode)

    def put_mode(
        self,
        user_id: str,
        *,
        name: str,
        steps: list[dict[str, Any]],
        delay_seconds: float,
    ) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 60:
            raise ValueError("Mode name must contain 1 to 60 characters")
        if "/" in name or "\\" in name:
            raise ValueError("Mode name cannot contain path separators")
        normalized = [normalize_step(step) for step in steps]
        if not normalized:
            raise ValueError("Mode must contain at least one task")
        delay = normalize_delay(delay_seconds)
        existing = self.db.get_mode_by_name(name, user_id)
        if existing is not None and self.is_running(existing["id"]):
            raise ValueError("Stop the mode before editing it")
        mode = self.db.upsert_mode(
            user_id=user_id,
            name=name,
            steps=normalized,
            delay_seconds=delay,
        )
        return self._with_runtime(mode)

    def delete_mode(self, mode_id: str, user_id: str) -> None:
        if self.is_running(mode_id):
            raise ValueError("Stop the mode before deleting it")
        if not self.db.delete_mode(mode_id, user_id):
            raise KeyError(mode_id)

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    def is_running(self, mode_id: str) -> bool:
        task = self._tasks.get(mode_id)
        return task is not None and not task.done()

    async def start(
        self,
        *,
        mode: dict[str, Any],
        manager_id: str,
        ip: str,
    ) -> dict[str, Any]:
        if self.is_running(mode["id"]):
            raise ValueError("Mode is already running")
        lamp = self.db.get_lamp(manager_id, ip)
        if lamp is None:
            raise ValueError("Lamp is not known to the selected manager")
        state = {
            "running_ip": ip,
            "manager_id": manager_id,
            "last_error": None,
        }
        self._runtime[mode["id"]] = state
        self._tasks[mode["id"]] = asyncio.create_task(
            self._run(mode, manager_id, ip), name=f"mode-{mode['id']}"
        )
        return self._with_runtime(mode)

    async def stop(self, mode_id: str) -> None:
        task = self._tasks.pop(mode_id, None)
        self._runtime.pop(mode_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        self._runtime.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self, mode: dict[str, Any], manager_id: str, ip: str
    ) -> None:
        failures = 0
        state = self._runtime.setdefault(mode["id"], {})
        try:
            while True:
                for step in mode["steps"]:
                    action, params = step_to_command(step)
                    try:
                        command = await self.commands.create_and_deliver(
                            user_id=mode["user_id"],
                            manager_id=manager_id,
                            action=action,
                            ip=ip,
                            params=params,
                        )
                        result = await self.commands.wait(command["id"])
                        if result["status"] != "completed":
                            raise RuntimeError(
                                result.get("error") or "Command failed"
                            )
                    except (CommandServiceError, RuntimeError) as exc:
                        failures += 1
                        state["last_error"] = str(exc)
                        if failures >= MAX_MODE_FAILURES:
                            return
                        await asyncio.sleep(max(mode["delay_seconds"], 1.0))
                        continue
                    failures = 0
                    state["last_error"] = None
                    await asyncio.sleep(mode["delay_seconds"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the mode loop from crashing the server
            state["last_error"] = str(exc)
        finally:
            self._tasks.pop(mode["id"], None)
            self._runtime.pop(mode["id"], None)

    def _with_runtime(self, mode: dict[str, Any]) -> dict[str, Any]:
        state = self._runtime.get(mode["id"], {})
        return {
            **mode,
            "running": self.is_running(mode["id"]),
            "running_ip": state.get("running_ip"),
            "manager_id": state.get("manager_id"),
            "last_error": state.get("last_error"),
        }


def import_legacy_modes(
    db: Database, user_id: str, path: Path | None
) -> int:
    """Import ``data/modes.json`` once, preserving the old format semantics."""

    if path is None or not path.is_file():
        return 0
    marker = f"legacy_modes_imported:{path}"
    if db.get_metadata(marker) == "1":
        return 0
    if db.list_modes(user_id):
        db.set_metadata(marker, "1")
        return 0
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(loaded, dict):
        return 0
    imported = 0
    for name, raw in loaded.items():
        if not isinstance(raw, dict):
            continue
        try:
            steps = raw.get("steps")
            if steps is None:
                steps = legacy_steps(raw.get("commands"))
            normalized = [normalize_step(step) for step in steps]
            delay = normalize_delay(raw.get("delay_seconds", 1.0))
            if not normalized:
                continue
            db.upsert_mode(
                user_id=user_id,
                name=str(name)[:60],
                steps=normalized,
                delay_seconds=delay,
            )
            imported += 1
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    db.set_metadata(marker, "1")
    return imported


__all__ = [
    "MODE_ACTIONS",
    "ModeService",
    "import_legacy_modes",
    "legacy_steps",
    "normalize_delay",
    "normalize_step",
    "step_to_command",
]
