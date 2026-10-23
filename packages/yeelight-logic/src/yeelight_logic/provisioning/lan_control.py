"""Standalone LAN Control enabling for an already reachable lamp."""

from __future__ import annotations

import socket

from ..exceptions import ConnectionError
from ..types import ProvisioningResult
from .wifi import (
    MiIOError,
    _device_info,
    _lan_control_outcome,
    _next_request_id,
    _next_timestamp,
    _open_session,
    _require_supported_model,
    _send_lan_control,
    lan_control_status_message,
    validate_private_ipv4,
)


def enable_lan_control(ip: str, timeout: float = 3.0) -> ProvisioningResult:
    """Try to enable LAN Control on a reachable lamp.

    The operation requires an explicit decision by the caller/UI because it
    changes device settings.  A successful miIO answer is reported as
    ``responded_unverified``: it does not prove that TCP 55443 is reachable.
    """

    target = validate_private_ipv4(ip)
    lan_control_status = "not_requested"
    lan_control_error = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            device_id, _stamp, token = _open_session(client, target, timeout)
            info, info_response = _device_info(
                client, target, device_id, _stamp, token, 1, timeout
            )
            _require_supported_model(info, "LAN Control setup")
            response = _send_lan_control(
                client,
                target,
                device_id,
                _next_timestamp(info_response.timestamp),
                token,
                _next_request_id(info_response.payload["id"]),
                timeout,
            )
    except OSError as exc:
        raise ConnectionError(
            "Could not send the LAN Control request to the device.",
            address=ip,
        ) from exc

    try:
        lan_control_status = _lan_control_outcome(
            response, require_confirmation=True
        )
    except MiIOError as exc:
        lan_control_status = "failed"
        lan_control_error = exc.code

    return ProvisioningResult(
        wifi_status="not_sent",
        wifi_message="Wi-Fi setup was not performed.",
        lan_control_status=lan_control_status,
        lan_control_message=lan_control_status_message(
            lan_control_status, lan_control_error
        ),
        lan_control_error=lan_control_error,
    )
