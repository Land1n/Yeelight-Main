from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from tests.support import FakeRuntime, FakeService, login, auth_headers
from yeelight_manager.local_api import create_local_app


class LocalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = FakeRuntime()
        self.service = FakeService(runtime=self.runtime)
        self.app = create_local_app(
            self.service, allow_clients={"127.0.0.1", "::1", "localhost", "testclient"}
        )
        self.client = TestClient(self.app)

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_status(self) -> None:
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["manager_name"], "Test manager")

    def test_lamps(self) -> None:
        self.runtime.add_lamp("192.168.1.10")
        response = self.client.get("/api/lamps")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["lamps"][0]["ip"], "192.168.1.10")

    def test_read_endpoints_do_not_require_manager_header(self) -> None:
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.assertEqual(self.client.get("/api/lamps").status_code, 200)

    def test_discover_requires_manager_header(self) -> None:
        response = self.client.post("/api/lamps/discover")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/api/lamps/discover", headers={"X-Yeelight-Manager": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_add_and_remove_lamp_requires_manager_header(self) -> None:
        response = self.client.post("/api/lamps", json={"ip": "192.168.1.10"})
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/lamps",
            json={"ip": "192.168.1.10"},
            headers={"X-Yeelight-Manager": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn(
            ("add", "192.168.1.10", {"ip": "192.168.1.10"}), self.runtime.actions
        )

        response = self.client.delete(
            "/api/lamps/192.168.1.10", headers={"X-Yeelight-Manager": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            ("remove", "192.168.1.10", {"ip": "192.168.1.10"}), self.runtime.actions
        )

    def test_run_command_requires_manager_header(self) -> None:
        response = self.client.post(
            "/api/lamps/192.168.1.10/command",
            json={"action": "power", "params": {"state": "on"}},
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/lamps/192.168.1.10/command",
            json={"action": "power", "params": {"state": "on"}},
            headers={"X-Yeelight-Manager": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            ("power", "192.168.1.10", {"state": "on"}), self.runtime.actions
        )

    def test_command_returns_400_on_failure(self) -> None:
        from yeelight_logic import CommandResult

        self.runtime.action_handler = lambda action, ip, params: CommandResult(
            False, "bad brightness", error_code="command_error"
        )
        response = self.client.post(
            "/api/lamps/192.168.1.10/command",
            json={"action": "brightness", "params": {"value": 0}},
            headers={"X-Yeelight-Manager": "1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])


class LocalApiProvisioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = FakeRuntime()
        self.service = FakeService(runtime=self.runtime)
        self.app = create_local_app(
            self.service, allow_clients={"127.0.0.1", "::1", "localhost", "testclient"}
        )
        self.client = TestClient(self.app)

    def _headers(self):
        return {"X-Yeelight-Manager": "1"}

    def test_wifi_without_confirm_is_400(self) -> None:
        response = self.client.post(
            "/api/provisioning/wifi",
            json={"ip": "192.168.13.1", "ssid": "Home", "password": "pass1234"},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_wifi_with_confirm(self) -> None:
        response = self.client.post(
            "/api/provisioning/wifi",
            json={
                "ip": "192.168.13.1",
                "ssid": "Home",
                "password": "pass1234",
                "enable_lan_control": True,
                "confirm": True,
            },
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(
            self.runtime.provision_calls[-1],
            {
                "kind": "wifi",
                "ip": "192.168.13.1",
                "ssid": "Home",
                "password": "pass1234",
                "enable_lan_control": True,
                "confirm": True,
            },
        )

    def test_lan_control_without_confirm_is_400(self) -> None:
        response = self.client.post(
            "/api/provisioning/lan-control",
            json={"ip": "192.168.1.10"},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_lan_control_with_confirm(self) -> None:
        response = self.client.post(
            "/api/provisioning/lan-control",
            json={"ip": "192.168.1.10", "confirm": True},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(
            self.runtime.provision_calls[-1],
            {"kind": "lan-control", "ip": "192.168.1.10", "confirm": True},
        )

    def test_password_is_not_echoed(self) -> None:
        response = self.client.post(
            "/api/provisioning/wifi",
            json={"ip": "192.168.13.1", "ssid": "Home", "password": "secret1234", "confirm": True},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("secret1234", str(body))


class LocalApiPairingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeService()
        self.app = create_local_app(
            self.service, allow_clients={"127.0.0.1", "::1", "localhost", "testclient"}
        )
        self.client = TestClient(self.app)

    def test_pair_and_unpair(self) -> None:
        self.service.paired = False
        response = self.client.post(
            "/api/pair",
            json={"code": "ABCD1234", "name": "Home"},
            headers={"X-Yeelight-Manager": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(self.service.paired)

        response = self.client.post(
            "/api/unpair", headers={"X-Yeelight-Manager": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["was_paired"])
        self.assertTrue(self.service.unpaired)

    def test_pair_failure_returns_502(self) -> None:
        from yeelight_manager.pairing import PairingError

        self.service.pair_error = PairingError("code expired", status_code=401)
        response = self.client.post(
            "/api/pair",
            json={"code": "BAD", "name": "Home"},
            headers={"X-Yeelight-Manager": "1"},
        )
        self.assertEqual(response.status_code, 401)

    def test_reconnect(self) -> None:
        response = self.client.post(
            "/api/reconnect", headers={"X-Yeelight-Manager": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.reconnects, 1)


if __name__ == "__main__":
    unittest.main()
