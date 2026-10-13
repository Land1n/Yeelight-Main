from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from dotenv import dotenv_values, set_key

from yeelight_network_utils import get_lan_addresses


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"
lan_ipv4 = get_lan_addresses


def _server_port(settings: dict[str, str | None]) -> int:
    try:
        port = int(settings.get("YEELIGHT_PORT") or "8000")
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise SystemExit("YEELIGHT_PORT in .env must be between 1 and 65535")


def configure_phone_access(
    env_file: Path | None = None,
    example_file: Path | None = None,
) -> int:
    env_file = env_file or ENV_FILE
    example_file = example_file or EXAMPLE_FILE
    if not env_file.exists():
        shutil.copyfile(example_file, env_file)

    settings = dotenv_values(env_file)
    port = _server_port(settings)
    token = (settings.get("YEELIGHT_API_TOKEN") or "").strip()
    if not token:
        token = secrets.token_urlsafe(32)

    set_key(env_file, "YEELIGHT_HOST", "0.0.0.0")
    set_key(env_file, "YEELIGHT_API_TOKEN", token)
    return port


def main() -> None:
    port = configure_phone_access()
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
