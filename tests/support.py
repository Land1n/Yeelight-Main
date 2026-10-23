"""Shared fakes and helpers for the test suite (no hardware required)."""

from __future__ import annotations

import os
import socket
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from yeelight_logic import (
    CommandError,
    CommandResult,
    ProvisioningResult,
    YeelightController,
)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-test-password"
MANAGER_TOKEN = "ylm_test_manager_token"


class APITestCase(unittest.TestCase):
    """Base class for server tests that enter the TestClient lifespan."""

    def setUp(self) -> None:
        self.client: TestClient | None = None

    def _enter_client(self, app) -> TestClient:
        client = TestClient(app, follow_redirects=False)
        client.__enter__()
        self.client = client
        return client

    def tearDown(self) -> None:
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None


class FakeBulb:
    """In-memory implementation of the ``LightBulb`` protocol."""

    def __init__(self, address: str, **properties: Any) -> None:
        self.address = address
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False
        self.failures: dict[str, Exception] = {}
        self.properties: dict[str, Any] = {
            "power": "off",
            "bright": "50",
            "ct": "4000",
            "rgb": "0",
            "color_mode": "2",
            "name": f"Lamp {address}",
            **properties,
        }

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        failure = self.failures.pop(name, None)
        if failure is not None:
            raise failure

    def turn_on(self) -> None:
        self._record("turn_on")
        self.properties["power"] = "on"

    def turn_off(self) -> None:
        self._record("turn_off")
        self.properties["power"] = "off"

    def toggle(self) -> None:
        self._record("toggle")
        self.properties["power"] = (
            "off" if self.properties.get("power") == "on" else "on"
        )

    def get_properties(self) -> dict[str, Any]:
        self._record("get_properties")
        return dict(self.properties)

    def set_brightness(self, brightness: int) -> None:
        self._record("set_brightness", brightness)
        self.properties["bright"] = str(brightness)

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        self._record("set_rgb", red, green, blue)
        self.properties["rgb"] = str((red << 16) | (green << 8) | blue)
        self.properties["color_mode"] = "1"

    def set_color_temperature(self, temperature: int) -> None:
        self._record("set_color_temperature", temperature)
        self.properties["ct"] = str(temperature)
        self.properties["color_mode"] = "2"

    def close(self) -> None:
        self.closed = True


def make_controller(
    addresses: tuple[str, ...] = ("192.168.1.10",),
    *,
    discovery_result: list[dict[str, Any]] | None = None,
    storage_path: Path | None = None,
) -> tuple[YeelightController, dict[str, FakeBulb]]:
    """Build a controller with fake lamps and no network access."""

    bulbs: dict[str, FakeBulb] = {
        address: fake_lamp(address) for address in addresses
    }

    def factory(address: str) -> FakeBulb:
        bulb = bulbs.get(address)
        if bulb is None:
            bulb = fake_lamp(address)
            bulbs[address] = bulb
        return bulb

    controller = YeelightController(
        addresses,
        bulb_factory=factory,
        discovery=(lambda: list(discovery_result or [])),
        storage_path=storage_path,
        min_command_interval=0.0,
        socket_idle_timeout=0.0,
    )
    return controller, bulbs


def fake_lamp(address: str, **properties: Any) -> FakeBulb:
    return FakeBulb(address, **properties)


def manager_settings(
    home: Path,
    *,
    local_api_enabled: bool = False,
    ui_enabled: bool = False,
) -> Any:
    from yeelight_manager.settings import ManagerSettings

    return ManagerSettings(
        home=home,
        server_url="http://127.0.0.1:8000",
        manager_name="Test manager",
        local_api_enabled=local_api_enabled,
        local_api_host="127.0.0.1",
        local_api_port=8765,
        ui_enabled=ui_enabled,
        poll_interval_seconds=30.0,
        discovery_timeout_seconds=0.5,
        command_timeout_seconds=5.0,
    )


def server_settings(
    tmp_path: Path,
    *,
    admin_password: str = ADMIN_PASSWORD,
    legacy_modes_file: Path | None = None,
    secure_cookies: bool = False,
) -> Any:
    from yeelight_server.config import Settings

    return Settings(
        host="127.0.0.1",
        port=8000,
        db_path=tmp_path / "server.db",
        admin_username=ADMIN_USERNAME,
        admin_password=admin_password,
        session_ttl_seconds=3600,
        secure_cookies=secure_cookies,
        command_timeout_seconds=2.0,
        max_command_wait_seconds=3.0,
        heartbeat_interval_seconds=10,
        legacy_modes_file=legacy_modes_file,
    )


def login(client: Any, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        raise AssertionError(f"Login failed: {response.status_code} {response.text}")
    return str(response.json()["csrf_token"])


def auth_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def pair_test_manager(client: Any) -> tuple[str, str]:
    """Create a pairing code and pair a manager through the public API."""

    csrf = login(client)
    code_response = client.post(
        "/api/v1/managers/pairing-codes",
        json={"name": "Test manager"},
        headers=auth_headers(csrf),
    )
    if code_response.status_code != 201:
        raise AssertionError(
            f"Pairing code creation failed: {code_response.status_code} "
            f"{code_response.text}"
        )
    code = code_response.json()["code"]
    pair_response = client.post(
        "/api/v1/managers/pair",
        json={"code": code, "name": "Test manager", "version": "test"},
    )
    if pair_response.status_code != 200:
        raise AssertionError(
            f"Pairing failed: {pair_response.status_code} {pair_response.text}"
        )
    data = pair_response.json()
    return data["manager"]["id"], data["token"]


class FakeRuntime:
    """Duck-typed manager runtime for UI/API/agent tests."""

    def __init__(self, lamps: list[dict[str, Any]] | None = None) -> None:
        self._lamps = [dict(item) for item in (lamps or [])]
        self.listeners: list[Any] = []
        self.actions: list[tuple[str, str | None, dict[str, Any]]] = []
        self.provision_calls: list[dict[str, Any]] = []
        self.monitor_started = False
        self.closed = False
        self.action_handler: Any = None
        self.discovery_bulbs: list[dict[str, Any]] = []
        self.wifi_result = ProvisioningResult(
            wifi_status="responded_unverified",
            wifi_message="Wi-Fi request answered",
            lan_control_status="not_requested",
        )
        self.lan_result = ProvisioningResult(
            wifi_status="not_sent",
            wifi_message="Wi-Fi setup was not performed.",
            lan_control_status="responded_unverified",
            lan_control_message="LAN Control request answered",
        )

    def add_listener(self, listener: Any) -> None:
        self.listeners.append(listener)

    def _emit(self, reason: str) -> None:
        for listener in list(self.listeners):
            listener(reason)

    def known_ips(self) -> list[str]:
        return sorted(str(item.get("ip")) for item in self._lamps)

    def lamp_states(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._lamps]

    def lamp_reports(self) -> list[dict[str, Any]]:
        return [
            {
                "ip": item.get("ip"),
                "name": item.get("name"),
                "model": item.get("model"),
                "online": item.get("online"),
            }
            for item in self._lamps
        ]

    def discover(self) -> CommandResult:
        self.actions.append(("discover", None, {}))
        for bulb in self.discovery_bulbs:
            ip = bulb.get("ip")
            if ip and not any(item.get("ip") == ip for item in self._lamps):
                self._lamps.append(
                    {
                        "ip": ip,
                        "name": None,
                        "model": None,
                        "online": True,
                    }
                )
        self._emit("discover")
        return CommandResult(
            True,
            f"Discovered {len(self.discovery_bulbs)} bulb(s)",
            data={"bulbs": list(self.discovery_bulbs)},
        )

    def add_lamp(self, ip: str) -> CommandResult:
        self.actions.append(("add", ip, {"ip": ip}))
        found = next((item for item in self._lamps if item.get("ip") == ip), None)
        if found is None:
            found = {"ip": ip, "online": True}
            self._lamps.append(found)
        else:
            found["online"] = True
        return CommandResult(True, f"Added lamp {ip}", data={"ip": ip})

    def remove_lamp(self, ip: str) -> CommandResult:
        self.actions.append(("remove", ip, {"ip": ip}))
        self._lamps = [item for item in self._lamps if item.get("ip") != ip]
        return CommandResult(True, f"Removed lamp {ip}", data={"ip": ip})

    def run_action(
        self,
        action: str,
        ip: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> CommandResult:
        params = params if isinstance(params, dict) else {}
        self.actions.append((action, ip, dict(params)))
        if self.action_handler is not None:
            result = self.action_handler(action, ip, params)
        else:
            result = CommandResult(
                True,
                f"{action} completed",
                data={"power": "on"} if action == "power" else {},
            )
        if ip:
            found = next((item for item in self._lamps if item.get("ip") == ip), None)
            if found is None:
                if not result.ok:
                    return result
                found = {"ip": ip, "online": True}
                self._lamps.append(found)
            if result.ok:
                found["online"] = True
                found["last_seen"] = time.time()
                found["last_error"] = None
                data = result.data or {}
                if action == "power" and data.get("power") in {"on", "off"}:
                    found["power"] = data["power"]
                elif action == "brightness" and data.get("brightness") is not None:
                    found["brightness"] = data["brightness"]
                elif action == "color" and isinstance(
                    data.get("rgb"), (list, tuple)
                ):
                    found["rgb"] = list(data["rgb"])
                elif (
                    action == "color_temperature"
                    and data.get("color_temperature") is not None
                ):
                    found["color_temperature"] = data["color_temperature"]
            elif result.error_code != "command_error":
                found["online"] = False
                found["last_error"] = (result.message or "command failed")[:300]
            else:
                found["last_error"] = (result.message or "command failed")[:300]
        self._emit("state")
        return result

    def refresh_states(self) -> list[dict[str, Any]]:
        return self.lamp_states()

    def start_monitor(self) -> None:
        self.monitor_started = True

    def stop_monitor(self) -> None:
        self.monitor_started = False

    def provision_wifi(
        self,
        ip: str,
        ssid: str,
        password: str,
        *,
        enable_lan_control: bool = False,
        confirm: bool = False,
    ) -> ProvisioningResult:
        self.provision_calls.append(
            {
                "kind": "wifi",
                "ip": ip,
                "ssid": ssid,
                "password": password,
                "enable_lan_control": enable_lan_control,
                "confirm": confirm,
            }
        )
        if not confirm:
            raise CommandError(
                "Wi-Fi setup requires explicit confirmation (confirm=true)."
            )
        return self.wifi_result

    def provision_lan_control(
        self, ip: str, *, confirm: bool = False
    ) -> ProvisioningResult:
        self.provision_calls.append(
            {"kind": "lan-control", "ip": ip, "confirm": confirm}
        )
        if not confirm:
            raise CommandError(
                "LAN Control setup requires explicit confirmation (confirm=true)."
            )
        return self.lan_result

    def close(self) -> None:
        self.closed = True
        self.monitor_started = False


class FakeAgent:
    def __init__(self) -> None:
        self._status = {
            "state": "unpaired",
            "connected": False,
            "error": None,
            "manager_id": None,
        }
        self.reconnects = 0
        self.notifications = 0
        self.stopped = False

    def status(self) -> dict[str, Any]:
        return dict(self._status)

    def request_reconnect(self) -> None:
        self.reconnects += 1

    def notify_state_changed(self) -> None:
        self.notifications += 1

    def stop(self) -> None:
        self.stopped = True
        self._status["state"] = "stopped"


class FakeService:
    """ManagerService-like object for local API tests."""

    def __init__(self, runtime: Any | None = None) -> None:
        from yeelight_manager.pairing import PairingError, PairingOutcome

        self.runtime = runtime or FakeRuntime()
        self.paired = False
        self.pair_error: PairingError | None = None
        self.pair_outcome = PairingOutcome(
            token="ylm_test_token",
            manager_id="mgr_test",
            manager_name="Test manager",
            heartbeat_interval_seconds=20.0,
        )
        self.reconnects = 0
        self.unpaired = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "0.2.0",
            "manager_name": "Test manager",
            "server_url": "http://127.0.0.1:8000",
            "paired": self.paired,
            "token_fingerprint": "abc123" if self.paired else "",
            "agent": {"state": "unpaired"},
            "lamps": self.runtime.lamp_states(),
            "lamp_count": len(self.runtime.lamp_states()),
        }

    def pair(self, code: str, *, name: str | None = None) -> Any:
        if self.pair_error is not None:
            raise self.pair_error
        self.paired = True
        return self.pair_outcome

    def unpair(self) -> bool:
        existed = self.paired
        self.paired = False
        self.unpaired = True
        return existed

    def reconnect(self) -> None:
        self.reconnects += 1


class FakeWebSocket:
    """Async fake used directly by ``ManagerHub`` tests."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.closed: list[tuple[int, str]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


class FakeAgentSocket:
    """Minimal async socket used by ``ManagerAgent._handle_command`` tests."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, value: str) -> None:
        import json

        self.sent.append(json.loads(value))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until(predicate: Any, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())
