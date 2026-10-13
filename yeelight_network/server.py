from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from yeelight_logic import YeelightController
from yeelight_network.api import create_app
from yeelight_config import PROJECT_ROOT, load_project_env
from yeelight_network_utils import get_lan_addresses


def main() -> None:
    load_project_env()
    host = os.getenv("YEELIGHT_HOST", "127.0.0.1")
    token = os.getenv("YEELIGHT_API_TOKEN")
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise RuntimeError(
            "YEELIGHT_API_TOKEN is required when binding beyond localhost"
        )
    addresses = filter(None, (part.strip() for part in os.getenv("YEELIGHT_BULBS", "").split(",")))
    poll_interval = float(os.getenv("YEELIGHT_POLL_INTERVAL_SECONDS", "10"))
    offline_timeout = float(os.getenv("YEELIGHT_UNRESPONSIVE_TIMEOUT_SECONDS", "60"))
    modes_path = Path(
        os.getenv(
            "YEELIGHT_MODES_FILE",
            str(PROJECT_ROOT / "data" / "modes.json"),
        )
    )
    bulbs_path = Path(
        os.getenv("YEELIGHT_BULBS_FILE", str(PROJECT_ROOT / "data" / "bulbs.json"))
    )
    app = create_app(
        YeelightController(addresses, storage_path=bulbs_path),
        api_token=token,
        poll_interval=poll_interval,
        offline_timeout=offline_timeout,
        modes_path=modes_path,
    )
    port = int(os.getenv("YEELIGHT_PORT", "8000"))
    if host in {"0.0.0.0", "::"}:
        addresses = get_lan_addresses()
        if addresses:
            print("Web interface address candidates (open one on the same Wi-Fi/LAN):")
            for address in addresses:
                print(f"  http://{address}:{port}")
        else:
            print(f"Server listens on all interfaces at port {port}.")
        print("Open one of these addresses in a browser; enter YEELIGHT_API_TOKEN if requested.")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
