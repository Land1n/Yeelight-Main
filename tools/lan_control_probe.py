from __future__ import annotations

import argparse
import ipaddress
import json
import socket
from typing import Any

from yeelight import Bulb, BulbException, discover_bulbs


def _target(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Enter a valid private IPv4 address.") from exc
    if address.version != 4 or not address.is_private:
        raise argparse.ArgumentTypeError("Only private IPv4 addresses are allowed.")
    return str(address)


def probe_lan_control(ip: str, timeout: float = 2.0) -> dict[str, Any]:
    target = _target(ip)
    try:
        with socket.create_connection((target, 55443), timeout=timeout):
            tcp_status = "open"
    except OSError as exc:
        tcp_status = f"failed ({type(exc).__name__})"

    try:
        bulbs = discover_bulbs(timeout=timeout)
        ssdp_status = (
            "found" if any(bulb.get("ip") == target for bulb in bulbs) else "not_found"
        )
    except (KeyError, OSError, ValueError) as exc:
        ssdp_status = f"failed ({type(exc).__name__})"

    try:
        properties = Bulb(target, port=55443).get_properties(["power"])
        get_prop_status = (
            "ok" if isinstance(properties.get("power"), str) else "unexpected_response"
        )
    except (BulbException, KeyError, OSError, UnboundLocalError, ValueError) as exc:
        get_prop_status = f"failed ({type(exc).__name__})"

    return {
        "ip": target,
        "tcp_55443": tcp_status,
        "ssdp_1982": ssdp_status,
        "get_prop": get_prop_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only check of Yeelight LAN Control: TCP 55443, "
            "SSDP UDP 239.255.255.250:1982, and get_prop."
        )
    )
    parser.add_argument("ip", type=_target, help="Current private IPv4 address of the bulb")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    result = probe_lan_control(args.ip, timeout=args.timeout)
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
