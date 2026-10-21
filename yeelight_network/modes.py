"""Хранилище циклических режимов и проверка их шагов."""

from __future__ import annotations

import json
import math
import re
import shlex
from pathlib import Path
from typing import Any

from yeelight_logic import CommandError, parse_int, write_json_atomic

MODE_ACTIONS = frozenset(
    {"on", "off", "toggle", "status", "brightness", "color", "temp"}
)
MIN_DELAY_SECONDS = 0.1
MAX_DELAY_SECONDS = 3600.0


def normalize_step(step: Any) -> dict[str, Any]:
    """Привести шаг режима к виду ``{"action": ..., "values": [...]}``."""

    if not isinstance(step, dict):
        raise ValueError("Mode contains an invalid task")
    action = step.get("action")
    if action not in MODE_ACTIONS:
        raise ValueError(f"Unsupported task: {action}")
    values = step.get("values", [])
    if not isinstance(values, list):
        raise ValueError("Task values must be a list")
    expected = 3 if action == "color" else 1 if action in {"brightness", "temp"} else 0
    if len(values) != expected:
        raise ValueError(f"Invalid values for task: {action}")
    if action == "brightness":
        values = [parse_int(values[0], "brightness", 1, 100)]
    elif action == "temp":
        values = [parse_int(values[0], "temperature", 1700, 6500)]
    elif action == "color":
        values = [
            parse_int(value, channel, 0, 255)
            for value, channel in zip(values, ("red", "green", "blue"))
        ]
    return {"action": action, "values": values}


def normalize_delay(value: Any) -> float:
    """Проверить паузу между командами режима."""

    if isinstance(value, bool):
        raise ValueError("Mode delay must be a number")
    try:
        delay = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mode delay must be a number") from exc
    if not math.isfinite(delay) or not MIN_DELAY_SECONDS <= delay <= MAX_DELAY_SECONDS:
        raise ValueError(
            f"Mode delay must be between {MIN_DELAY_SECONDS} and {MAX_DELAY_SECONDS:g} seconds"
        )
    return delay


def _legacy_steps(commands: Any) -> list[dict[str, Any]]:
    if not isinstance(commands, list):
        raise ValueError("Legacy mode must contain a list of commands")
    steps = []
    for command in commands:
        parts = shlex.split(command)
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
            args = [int(args[0]) if args[0].isdigit() else args[0]]
        steps.append({"action": action, "values": args})
    return steps


class ModeStore:
    """Загружает, проверяет и атомарно сохраняет режимы."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.modes: dict[str, dict[str, Any]] = {}
        if self.path is not None and self.path.is_file():
            try:
                self.modes = self._load(self.path)
            except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
                raise RuntimeError(f"Could not load modes from {self.path}: {exc}") from exc

    @staticmethod
    def _load(path: Path) -> dict[str, dict[str, Any]]:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Modes file must contain a JSON object")
        modes = {}
        for name, mode in loaded.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Modes file contains an invalid mode name")
            if "/" in name or "\\" in name:
                raise ValueError("Mode name cannot contain path separators")
            if not isinstance(mode, dict):
                raise ValueError("Modes file contains an invalid mode")
            steps = mode.get("steps")
            if steps is None:
                steps = _legacy_steps(mode.get("commands"))
            if not isinstance(steps, list):
                raise ValueError("Modes file contains an invalid mode")
            try:
                normalized = [normalize_step(step) for step in steps]
            except (CommandError, ValueError) as exc:
                raise ValueError(f"Mode {name!r} contains an invalid task: {exc}") from exc
            modes[name] = {
                "name": name,
                "steps": normalized,
                "delay_seconds": normalize_delay(mode.get("delay_seconds", 1.0)),
                "last_error": None,
                "running_ip": None,
            }
        return modes

    def save(self) -> None:
        if self.path is None:
            return
        write_json_atomic(
            self.path,
            {
                name: {
                    "steps": mode["steps"],
                    "delay_seconds": mode["delay_seconds"],
                }
                for name, mode in self.modes.items()
            },
        )

    def put(
        self,
        name: str,
        steps: list[dict[str, Any]],
        delay_seconds: float,
    ) -> dict[str, Any]:
        mode = {
            "name": name,
            "steps": [normalize_step(step) for step in steps],
            "delay_seconds": normalize_delay(delay_seconds),
            "last_error": None,
            "running_ip": None,
        }
        self.modes[name] = mode
        self.save()
        return mode

    def delete(self, name: str) -> None:
        del self.modes[name]
        self.save()
