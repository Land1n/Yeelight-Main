from __future__ import annotations

import os
import socket
import subprocess


def get_lan_addresses() -> list[str]:
    """Return usable local IPv4 addresses, preferring active physical adapters."""
    if os.name == "nt":
        command = (
            "$physical = Get-NetAdapter -Physical | "
            "Where-Object Status -eq 'Up' | "
            "Select-Object -ExpandProperty Name; "
            "Get-NetIPConfiguration | "
            "Where-Object { $_.InterfaceAlias -in $physical -and $_.IPv4DefaultGateway } | "
            "ForEach-Object { $_.IPv4Address | ForEach-Object IPAddress }"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                capture_output=True,
                check=True,
                text=True,
                timeout=10,
            )
            addresses = list(
                dict.fromkeys(
                    address
                    for line in result.stdout.splitlines()
                    if (address := line.strip()) and not address.startswith("127.")
                )
            )
            if addresses:
                return addresses
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            address = probe.getsockname()[0]
            return [address] if not address.startswith("127.") else []
    except OSError:
        return []
