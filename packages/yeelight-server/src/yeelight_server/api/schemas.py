"""Request models for the public JSON API.

The models are deliberately strict: the remote API accepts a closed set of
typed actions and never raw command strings.  ``extra="forbid"`` makes typos in
security-relevant fields (for example ``wait``) fail loudly instead of being
silently ignored.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class PairingCodeRequest(StrictModel):
    name: str | None = Field(default=None, max_length=60)


class ManagerPairRequest(StrictModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=60)
    version: str | None = Field(default=None, max_length=40)


CommandAction = Literal[
    "power",
    "brightness",
    "color",
    "color_temperature",
    "status",
    "discover",
    "add",
    "remove",
    "list",
]


class CommandRequest(StrictModel):
    manager_id: str = Field(min_length=1, max_length=80)
    action: CommandAction
    ip: str | None = Field(default=None, max_length=45)
    params: dict[str, Any] = Field(default_factory=dict)
    wait: bool = True
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=120.0)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ModeStep(StrictModel):
    action: Literal[
        "on", "off", "toggle", "status", "brightness", "color", "temp"
    ]
    values: list[Any] = Field(default_factory=list, max_length=8)


class ModeRequest(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    steps: list[ModeStep] = Field(min_length=1, max_length=200)
    delay_seconds: float = Field(default=1.0, ge=0.1, le=3600.0)


class ModeStartRequest(StrictModel):
    manager_id: str = Field(min_length=1, max_length=80)
    ip: str = Field(min_length=1, max_length=45)


class AuditQuery(StrictModel):
    limit: int = Field(default=100, ge=1, le=500)
