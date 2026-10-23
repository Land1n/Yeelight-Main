"""yeelight-logic — independent Yeelight LAN control library.

Public API::

    from yeelight_logic import Bulb, YeelightController
    from yeelight_logic.commands import TurnOnCommand, SetBrightnessCommand
    from yeelight_logic.provisioning import connect_to_wifi, enable_lan_control

The package has no dependency on Flet, FastAPI or any remote-server concept.
"""

from __future__ import annotations

from .actions import REMOTE_ACTIONS, execute_action, validate_action_params
from .bulb import (
    MAX_BRIGHTNESS,
    MAX_COLOR_TEMP,
    MIN_BRIGHTNESS,
    MIN_COLOR_TEMP,
    Bulb,
)
from .controller import YeelightController, parse_int
from .discovery import discover_bulbs
from .exceptions import (
    CommandError,
    ConnectionError,
    DeviceError,
    DiscoveryError,
    LanControlError,
    ProvisioningError,
    StorageError,
    UnsupportedModelError,
    YeelightLogicError,
)
from .protocol import LightBulb, RealBulb
from .provisioning import connect_to_wifi, enable_lan_control
from .storage import read_json_atomic, write_json_atomic
from .types import BulbInfo, CommandResult, ProvisioningResult

__all__ = [
    "Bulb",
    "YeelightController",
    "LightBulb",
    "RealBulb",
    "discover_bulbs",
    "connect_to_wifi",
    "enable_lan_control",
    "execute_action",
    "validate_action_params",
    "REMOTE_ACTIONS",
    "BulbInfo",
    "CommandResult",
    "ProvisioningResult",
    "YeelightLogicError",
    "CommandError",
    "DeviceError",
    "ConnectionError",
    "DiscoveryError",
    "StorageError",
    "ProvisioningError",
    "LanControlError",
    "UnsupportedModelError",
    "parse_int",
    "read_json_atomic",
    "write_json_atomic",
    "MIN_BRIGHTNESS",
    "MAX_BRIGHTNESS",
    "MIN_COLOR_TEMP",
    "MAX_COLOR_TEMP",
]
