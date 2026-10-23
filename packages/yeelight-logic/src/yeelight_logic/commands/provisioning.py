"""Provisioning commands.

These commands never run remotely.  They require an explicit ``confirmed`` flag
because changing Wi-Fi settings can disconnect the lamp from the network.
"""

from __future__ import annotations

from ..provisioning import connect_to_wifi, enable_lan_control
from ..types import CommandResult
from .base import Command, error_result


class ConnectWifiCommand(Command):
    def __init__(
        self,
        ip: str,
        ssid: str,
        password: str,
        *,
        enable_lan_control: bool = False,
        confirmed: bool = False,
    ) -> None:
        self._ip = ip
        self._ssid = ssid
        self._password = password
        self._enable_lan_control = enable_lan_control
        self._confirmed = confirmed

    def execute(self) -> CommandResult:
        if not self._confirmed:
            return CommandResult(
                False,
                "Wi-Fi setup requires explicit confirmation",
                error_code="confirmation_required",
            )
        try:
            result = connect_to_wifi(
                self._ip,
                self._ssid,
                self._password,
                enable_lan_control=self._enable_lan_control,
            )
            return CommandResult(
                True,
                result.wifi_message,
                data=result.to_dict(),
            )
        except Exception as exc:
            return error_result(exc, "Wi-Fi setup failed")
        finally:
            self._password = ""


class EnableLanControlCommand(Command):
    def __init__(self, ip: str, *, confirmed: bool = False) -> None:
        self._ip = ip
        self._confirmed = confirmed

    def execute(self) -> CommandResult:
        if not self._confirmed:
            return CommandResult(
                False,
                "LAN Control setup requires explicit confirmation",
                error_code="confirmation_required",
            )
        try:
            result = enable_lan_control(self._ip)
            return CommandResult(
                True,
                result.lan_control_message,
                data=result.to_dict(),
            )
        except Exception as exc:
            return error_result(exc, "LAN Control setup failed")
