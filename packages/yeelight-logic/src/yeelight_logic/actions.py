"""Typed action dispatcher shared by the manager and legacy controller facade.

The remote command protocol never carries arbitrary shell-like text.  The
server sends a typed action with parameters; this module validates those
parameters and maps them to the command classes.  Provisioning operations are
intentionally absent: they must only be triggered locally with confirmation.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from .commands import (
    AddBulbCommand,
    DiscoverBulbsCommand,
    GetStatusCommand,
    RemoveBulbCommand,
    SetBrightnessCommand,
    SetColorCommand,
    SetColorTemperatureCommand,
    ToggleCommand,
    TurnOffCommand,
    TurnOnCommand,
)
from .controller import YeelightController
from .exceptions import CommandError
from .protocol import LightBulb
from .types import CommandResult

#: Actions that a remote manager may execute.  Wi-Fi and LAN Control are not
#: present here by design.
REMOTE_ACTIONS = frozenset(
    {
        "power",
        "brightness",
        "color",
        "color_temperature",
        "status",
        "discover",
        "add",
        "remove",
        "list",
    }
)

LAMP_ACTIONS = frozenset(
    {"power", "brightness", "color", "color_temperature", "status"}
)


def _validate_ip(address: str) -> str:
    address = str(address).strip()
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise CommandError(f"Invalid IP address: {address}") from exc
    if parsed.version != 4:
        raise CommandError("Only IPv4 lamp addresses are supported")
    return address


def _as_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise CommandError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise CommandError(f"{name} must be between {minimum} and {maximum}")
    return result


def validate_action_params(action: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize parameters for a remote action."""

    if action not in REMOTE_ACTIONS:
        raise CommandError(f"Unsupported action: {action}")
    params = params or {}
    if not isinstance(params, dict):
        raise CommandError("Command parameters must be an object")

    if action == "power":
        state = params.get("state")
        if state not in {"on", "off", "toggle"}:
            raise CommandError("Power state must be 'on', 'off' or 'toggle'")
        return {"state": state}
    if action == "brightness":
        return {"value": _as_int(params.get("value"), "brightness", 1, 100)}
    if action == "color_temperature":
        return {
            "value": _as_int(params.get("value"), "temperature", 1700, 6500)
        }
    if action == "color":
        if "rgb" in params:
            rgb = params["rgb"]
            if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
                raise CommandError("RGB must be a list of three integers")
            return {
                "rgb": [
                    _as_int(value, name, 0, 255)
                    for value, name in zip(rgb, ("red", "green", "blue"))
                ]
            }
        hex_color = params.get("hex")
        if isinstance(hex_color, str):
            match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
            if match:
                value = int(match.group(1), 16)
                return {
                    "rgb": [
                        (value >> 16) & 255,
                        (value >> 8) & 255,
                        value & 255,
                    ]
                }
        raise CommandError("Color requires an rgb list or a #RRGGBB value")
    if action in {"status", "discover", "list"}:
        return {}
    # add / remove
    if "ip" not in params and "address" not in params:
        raise CommandError(f"Action '{action}' requires an ip")
    return {"ip": _validate_ip(params.get("ip", params.get("address")))}


def execute_action(
    controller: YeelightController,
    action: str,
    address: str | None = None,
    params: dict[str, Any] | None = None,
    *,
    bulb: LightBulb | None = None,
) -> CommandResult:
    """Validate and execute one typed action through command classes."""

    try:
        normalized = validate_action_params(action, params)
        if address is not None:
            address = _validate_ip(address)
    except CommandError as exc:
        return CommandResult(False, str(exc), error_code=exc.code)

    if action == "discover":
        return DiscoverBulbsCommand(controller).execute()
    if action == "list":
        return CommandResult(
            True,
            f"Known lamps: {len(controller.known_bulbs())}",
            data={"bulbs": controller.known_bulbs()},
        )
    if action == "add":
        return AddBulbCommand(controller, normalized["ip"]).execute()
    if action == "remove":
        return RemoveBulbCommand(controller, normalized["ip"]).execute()

    assert address is not None
    if bulb is None and not controller.is_known(address):
        return CommandResult(
            False,
            f"Unknown lamp {address}; add it first",
            error_code="command_error",
        )

    command = _command_for(action, address, normalized, bulb or controller.bulb_for(address))
    result = command.execute()
    # A stale socket is a common first failure: the lamp closes idle
    # connections.  Retry once for idempotent actions only.
    if (
        not result.ok
        and result.error_code == "device_error"
        and _is_transport_error(result.message)
        and not (action == "power" and normalized.get("state") == "toggle")
    ):
        result = command.execute()
    return result


def _command_for(
    action: str,
    address: str,
    params: dict[str, Any],
    bulb: LightBulb,
):
    if action == "power":
        if params["state"] == "on":
            return TurnOnCommand(bulb)
        if params["state"] == "off":
            return TurnOffCommand(bulb)
        return ToggleCommand(bulb)
    if action == "brightness":
        return SetBrightnessCommand(bulb, params["value"])
    if action == "color":
        red, green, blue = params["rgb"]
        return SetColorCommand(bulb, red, green, blue)
    if action == "color_temperature":
        return SetColorTemperatureCommand(bulb, params["value"])
    return GetStatusCommand(bulb)


def _is_transport_error(message: str) -> bool:
    lowered = message.lower()
    return "socket" in lowered or "closed the connection" in lowered
