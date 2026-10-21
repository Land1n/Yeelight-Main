from __future__ import annotations

import argparse
import json
import socket
import time
from typing import Any

from yeelight import discover_bulbs

from yeelight_network.miio import MiIOError, validate_private_ipv4


def _target(value: str) -> str:
    try:
        return validate_private_ipv4(value)
    except MiIOError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc



def _get_prop(
    target: str,
    timeout: float,
) -> tuple[str, dict[str, Any] | None, str | None]:
    request = (
        json.dumps(
            {"id": 1, "method": "get_prop", "params": ["power"]},
            separators=(",", ":"),
        )
        + "\r\n"
    ).encode("utf-8")
    deadline = time.monotonic() + timeout
    local_address = None
    try:
        with socket.create_connection((target, 55443), timeout=timeout) as client:
            local_address = client.getsockname()[0]
            client.settimeout(timeout)
            client.sendall(request)
            pending = b""
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "timeout", None, local_address
                client.settimeout(remaining)
                chunk = client.recv(4096)
                if not chunk:
                    return "empty_response", None, local_address
                pending += chunk
                while b"\r\n" in pending:
                    raw_line, pending = pending.split(b"\r\n", 1)
                    if not raw_line:
                        continue
                    try:
                        response = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return "invalid_json", None, local_address
                    if not isinstance(response, dict):
                        return "unexpected_response", None, local_address
                    if response.get("method") == "props":
                        continue
                    response_id = response.get("id")
                    if (
                        not isinstance(response_id, int)
                        or isinstance(response_id, bool)
                        or response_id != 1
                    ):
                        return "unexpected_response", None, local_address
                    if isinstance(response.get("error"), dict):
                        error = response["error"]
                        safe_error = {
                            "code": error.get("code"),
                            "message": (
                                error.get("message")[:200]
                                if isinstance(error.get("message"), str)
                                else None
                            ),
                        }
                        return "device_error", safe_error, local_address
                    result = response.get("result")
                    if (
                        isinstance(result, list)
                        and len(result) == 1
                        and isinstance(result[0], str)
                    ):
                        return "ok", {"power": result[0]}, local_address
                    return "unexpected_response", None, local_address
    except socket.timeout:
        return "timeout", None, local_address
    except OSError as exc:
        return f"failed ({type(exc).__name__})", None, local_address


def probe_lan_control(
    ip: str,
    timeout: float = 2.0,
    interface: str | None = None,
) -> dict[str, Any]:
    target = _target(ip)
    tcp_source_address = None
    try:
        with socket.create_connection((target, 55443), timeout=timeout) as client:
            tcp_status = "open"
            tcp_source_address = client.getsockname()[0]
    except OSError as exc:
        tcp_status = f"failed ({type(exc).__name__})"

    try:
        bulbs = (
            discover_bulbs(timeout=timeout)
            if interface is None
            else discover_bulbs(timeout=timeout, interface=interface)
        )
        ssdp_status = (
            "found" if any(bulb.get("ip") == target for bulb in bulbs) else "not_found"
        )
    except (KeyError, OSError, ValueError) as exc:
        ssdp_status = f"failed ({type(exc).__name__})"

    get_prop_status, get_prop_details, get_prop_source_address = _get_prop(
        target,
        timeout,
    )

    result = {
        "ip": target,
        "tcp_55443": tcp_status,
        "tcp_source_address": tcp_source_address,
        "ssdp_1982": ssdp_status,
        "get_prop": get_prop_status,
        "get_prop_source_address": get_prop_source_address,
    }
    if get_prop_details is not None:
        result["get_prop_details"] = get_prop_details
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only check of Yeelight LAN Control: TCP 55443, "
            "SSDP UDP 239.255.255.250:1982, and get_prop."
        )
    )
    parser.add_argument("ip", type=_target, help="Current private IPv4 address of the bulb")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--interface",
        help="Network adapter name (or GUID on Windows) to use for SSDP multicast",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    result = probe_lan_control(
        args.ip,
        timeout=args.timeout,
        interface=args.interface,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(
        result[field] == expected
        for field, expected in (
            ("tcp_55443", "open"),
            ("ssdp_1982", "found"),
            ("get_prop", "ok"),
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
