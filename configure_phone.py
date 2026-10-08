from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

from dotenv import dotenv_values, set_key


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def lan_ipv4() -> list[str]:
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


def main() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(EXAMPLE_FILE, ENV_FILE)

    settings = dotenv_values(ENV_FILE)
    token = settings.get("YEELIGHT_API_TOKEN", "").strip()
    if not token:
        token = secrets.token_urlsafe(32)

    set_key(ENV_FILE, "YEELIGHT_HOST", "0.0.0.0")
    set_key(ENV_FILE, "YEELIGHT_API_TOKEN", token)

    try:
        port = int(settings.get("YEELIGHT_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise SystemExit("YEELIGHT_PORT in .env must be between 1 and 65535") from exc

    addresses = lan_ipv4()
    print("Phone access is configured in .env (server binds to the local network).")
    if addresses:
        print("Server URL candidates (use the address on the same Wi-Fi/LAN as the phone):")
        for address in addresses:
            print(f"  http://{address}:{port}")
    else:
        print(f"Server listens on port {port}. Find the computer IPv4 address with ipconfig.")
    print("Enter the URL above and the YEELIGHT_API_TOKEN from .env in the Flet app.")
    print("Allow Python through Windows Firewall for Private networks only.")
    print("Restart the server for the new settings to take effect.")


if __name__ == "__main__":
    main()
