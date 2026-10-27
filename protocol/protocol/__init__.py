"""Общие pydantic-модели обмена между manager и server."""

from typing import Literal

from pydantic import BaseModel

Kind = Literal[
    "command", "undo", "discover", "add", "remove",
    "mode_save", "mode_delete", "mode_start", "mode_stop",
]


class Action(BaseModel):
    """Действие, которое сайт ставит в очередь для manager."""

    id: int | None = None
    kind: Kind
    ip: str | None = None
    command: dict | None = None  # формат Command.to_dict() из lamp
    mode: dict | None = None  # {"name", "steps": [без ip], "delay_seconds"}
    name: str | None = None


class ActionResult(BaseModel):
    id: int
    ok: bool
    message: str


class LampState(BaseModel):
    ip: str
    online: bool | None
    last_seen: float | None
    props: dict


class ManagerState(BaseModel):
    lamps: list[LampState]
    modes: list[dict]
    log: list[str]


class PollRequest(BaseModel):
    state: ManagerState
    results: list[ActionResult]


class PollResponse(BaseModel):
    actions: list[Action]
