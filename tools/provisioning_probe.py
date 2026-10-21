from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import platform
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from yeelight_network.miio import (
    MiIOError,
    request_device_details,
    validate_private_ipv4,
)


def _probe_target(ip: str) -> str:
    try:
        return validate_private_ipv4(ip)
    except MiIOError as exc:
        raise RuntimeError(str(exc)) from exc



def _run(command: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def _bluetooth_report() -> dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue "
            "| Select-Object -ExpandProperty FriendlyName",
        ]
    elif system == "Linux":
        command = ["bluetoothctl", "list"]
    elif system == "Darwin":
        command = ["system_profiler", "SPBluetoothDataType"]
    else:
        return {
            "status": "unsupported",
            "message": f"Bluetooth adapter check is not implemented for {system}.",
        }

    try:
        result = _run(command)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": f"Could not inspect Bluetooth: {exc}"}

    if result.returncode != 0:
        message = result.stderr.strip() or "System Bluetooth query failed."
        return {"status": "error", "message": message}

    if system == "Windows":
        devices = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
            and re.search(r"adapter|radio|wireless", line, flags=re.IGNORECASE)
            and not re.search(r"enumerator", line, flags=re.IGNORECASE)
        ]
    elif system == "Linux":
        devices = [
            match.group(1).strip()
            for match in re.finditer(
                r"^Controller\s+[0-9A-F:]{17}\s+(.+?)(?:\s+\[default\])?$",
                result.stdout,
                flags=re.IGNORECASE | re.MULTILINE,
            )
        ]
    else:
        devices = ["Bluetooth Controller"] if "Bluetooth Controller:" in result.stdout else []
    return {
        "status": "detected" if devices else "not_detected",
        "present_adapters": devices,
        "message": (
            "A Bluetooth adapter was reported by the operating system; BLE support "
            "for the lamp is not confirmed."
            if devices
            else "No Bluetooth adapter was reported by the operating system."
        ),
    }


def _yeelight_network_report() -> dict[str, Any]:
    if platform.system() != "Windows":
        return {
            "status": "unsupported",
            "message": "Temporary Yeelight Wi-Fi network detection is currently Windows-only.",
        }

    try:
        result = _run(["netsh.exe", "wlan", "show", "networks", "mode=bssid"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": f"Could not scan visible Wi-Fi networks: {exc}"}

    if result.returncode != 0:
        message = result.stderr.strip() or "Windows Wi-Fi scan failed."
        return {"status": "error", "message": message}

    networks = sorted(
        {
            match.group(1).strip()
            for match in re.finditer(
                r"^\s*SSID\s+\d+\s*:\s*(.*?)\s*$",
                result.stdout,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            if match.group(1).strip().lower().startswith("yeelink-light-")
        }
    )
    return {
        "status": "detected" if networks else "not_detected",
        "yeelight_setup_networks": networks,
        "message": (
            "A Wi-Fi network with the Yeelight setup prefix is visible. "
            "This does not confirm the bulb model or provisioning protocol."
            if networks
            else "No visible Wi-Fi network with the Yeelight setup prefix was found."
        ),
    }


def collect_report() -> dict[str, Any]:
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "bleak_installed": importlib.util.find_spec("bleak") is not None,
        "bluetooth": _bluetooth_report(),
        "yeelight_setup_wifi": _yeelight_network_report(),
        "limitations": [
            "This diagnostic does not identify a bulb model from its name, CMIIT ID, or MAC address.",
            "Detecting Bluetooth or a setup Wi-Fi network does not establish that credentials can be sent.",
            "No Wi-Fi credentials are requested, sent, or stored.",
        ],
    }


def probe_miio(ip: str, timeout: float = 3.0) -> dict[str, Any]:
    target = _probe_target(ip)

    packet = bytes.fromhex(
        "21310020ffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(timeout)
            client.sendto(packet, (target, 54321))
            response, source = client.recvfrom(1024)
    except OSError:
        return {
            "target_ip": target,
            "status": "no_response",
            "message": "No miIO handshake response was received.",
        }

    if (
        source[0] != target
        or len(response) != 32
        or response[:2] != b"!1"
        or int.from_bytes(response[2:4], "big") != 32
    ):
        return {
            "target_ip": target,
            "status": "unexpected_response",
            "message": "The target replied, but the packet was not a valid miIO handshake.",
        }

    token = response[16:32]
    token_available = token not in (bytes(16), b"\xff" * 16)
    return {
        "target_ip": target,
        "status": "miio_device_responded",
        "device_id": int.from_bytes(response[8:12], "big"),
        "token_available": token_available,
        "message": (
            "The miIO device returned a usable token in its handshake; the token "
            "itself is deliberately not displayed."
            if token_available
            else "The miIO device responded, but its handshake does not expose a usable token."
        ),
        "warning": (
            "This read-only handshake does not confirm Wi-Fi provisioning support. "
            "No configuration command or credentials were sent."
        ),
    }



_INFO_ERROR_STATUS = {
    "handshake_timeout": (
        "no_response",
        "The device did not answer the read-only miIO handshake.",
    ),
    "handshake_invalid": (
        "unexpected_response",
        "The target did not return a valid miIO handshake.",
    ),
    "token_unavailable": (
        "token_unavailable",
        "The miIO handshake did not provide a usable token.",
    ),
    "info_timeout": (
        "no_response",
        "The device did not answer the read-only miIO info request.",
    ),
    "info_rejected": (
        "device_error",
        "The device rejected the read-only miIO info request.",
    ),
    "invalid_device_info": (
        "unsupported",
        "The device did not return standard miIO info fields.",
    ),
    "transport_error": (
        "no_response",
        "The device did not answer the read-only miIO info request.",
    ),
}


def _redact_error_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[0-9a-fA-F]{32,}", "[redacted]", value[:200])


def probe_miio_info(ip: str, timeout: float = 3.0) -> dict[str, Any]:
    target = _probe_target(ip)
    try:
        info, device_id = request_device_details(target, timeout)
    except MiIOError as exc:
        status, message = _INFO_ERROR_STATUS.get(
            exc.code,
            (
                "unexpected_response",
                "The device returned an unreadable or unrelated miIO info response.",
            ),
        )
        result = {
            "target_ip": target,
            "status": status,
            "message": message,
            "warning": "No Wi-Fi configuration command or credentials were sent.",
        }
        if exc.code == "info_rejected":
            error = exc.details if isinstance(exc.details, dict) else {}
            result["error"] = {
                "code": error.get("code"),
                "message": _redact_error_message(error.get("message")),
            }
        return result

    return {
        "target_ip": target,
        "status": "device_info_received" if info else "unsupported",
        "device_id": device_id,
        "device_info": info,
        "message": (
            "Read-only device information received."
            if info
            else "The device response did not contain model or version information."
        ),
        "warning": "No Wi-Fi configuration command or credentials were sent.",
    }


async def scan_ble(timeout: float = 8.0) -> dict[str, Any]:
    try:
        from bleak import BleakScanner
        from bleak.exc import BleakError
    except ImportError as exc:
        raise RuntimeError(
            'BLE scanning requires the optional dependency. Install it with '
            'python -m pip install -e ".[diagnostics]".'
        ) from exc

    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except (BleakError, OSError, asyncio.TimeoutError) as exc:
        raise RuntimeError(f"BLE scan failed: {exc}") from exc
    devices = []
    for device, advertisement in found.values():
        devices.append(
            {
                "name": advertisement.local_name or device.name,
                "address": device.address,
                "rssi": advertisement.rssi,
                "service_uuids": sorted(advertisement.service_uuids or []),
                "manufacturer_data": {
                    str(company_id): bytes(payload).hex()
                    for company_id, payload in advertisement.manufacturer_data.items()
                },
            }
        )
    return {
        "scan_seconds": timeout,
        "devices": sorted(devices, key=lambda item: (item["name"] or "", item["address"])),
        "warning": (
            "BLE advertisements are diagnostic only and do not confirm a Wi-Fi "
            "provisioning protocol."
        ),
    }


async def inspect_gatt(address: str, timeout: float = 10.0) -> dict[str, Any]:
    try:
        from bleak import BleakClient
        from bleak.exc import BleakError
    except ImportError as exc:
        raise RuntimeError(
            'GATT inspection requires the optional dependency. Install it with '
            'python -m pip install -e ".[diagnostics]".'
        ) from exc

    try:
        async with BleakClient(address, timeout=timeout) as client:
            services = [
                {
                    "uuid": service.uuid,
                    "characteristics": [
                        {
                            "uuid": characteristic.uuid,
                            "properties": sorted(characteristic.properties),
                        }
                        for characteristic in service.characteristics
                    ],
                }
                for service in client.services
            ]
    except (BleakError, OSError, asyncio.TimeoutError) as exc:
        raise RuntimeError(f"GATT inspection failed: {exc}") from exc
    return {
        "address": address,
        "services": services,
        "warning": "GATT inspection is read-only; no characteristic values are read or written.",
    }


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostics for Yeelight Wi-Fi provisioning research."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--report", action="store_true", help="inspect OS, Bluetooth and visible setup Wi-Fi")
    modes.add_argument("--ble-scan", action="store_true", help="scan nearby BLE advertisements")
    modes.add_argument("--gatt-address", help="read GATT service and characteristic metadata only")
    modes.add_argument("--miio-probe", metavar="IP", help="send one read-only miIO handshake to this IPv4 address")
    modes.add_argument("--miio-info", metavar="IP", help="request read-only miIO model and firmware details")
    parser.add_argument("--output", type=Path, help="also save the diagnostic JSON to this path")
    args = parser.parse_args()

    try:
        if args.report:
            report = collect_report()
        elif args.ble_scan:
            report = asyncio.run(scan_ble())
        elif args.miio_probe:
            report = probe_miio(args.miio_probe)
        elif args.miio_info:
            report = probe_miio_info(args.miio_info)
        else:
            report = asyncio.run(inspect_gatt(args.gatt_address))
        _write_report(report, args.output)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Diagnostic failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
