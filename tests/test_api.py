import unittest
import time
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from yeelight_logic import YeelightController
from yeelight_network.api import create_app
from yeelight_network.miio import MiIOError


class FakeBulb:
    def turn_on(self) -> None:
        pass

    def turn_off(self) -> None:
        pass

    def get_properties(self) -> dict[str, str]:
        return {"power": "on"}

    def set_brightness(self, brightness: int) -> None:
        pass

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        pass

    def set_color_temp(self, temperature: int) -> None:
        pass


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        controller = YeelightController(
            ["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()
        )
        self.client = TestClient(create_app(controller, api_token="test-token"))
        self.headers = {"X-API-Token": "test-token"}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_home_serves_web_client(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Yeelight Console", response.text)
        self.assertIn('id="command-form"', response.text)
        self.assertIn('id="reconnect"', response.text)
        self.assertIn('class="wifi-fields"', response.text)
        self.assertIn('class="wifi-confirm"', response.text)
        self.assertIn('id="lan-control-form"', response.text)
        self.assertIn("Отдельно включить LAN Control", response.text)
        self.assertIn('/static/css/app.css', response.text)
        self.assertIn('/static/js/app.js', response.text)

    def test_static_frontend_modules_are_served(self) -> None:
        scripts = {
            "/static/js/app.js": "async function saveMode(event)",
            "/static/js/api.js": "function formatError(detail)",
            "/static/js/bulbs.js": "class BulbList",
            "/static/js/mode-editor.js": "class ModeEditor",
            "/static/js/modes.js": "class ModeList",
            "/static/js/mode-presets.js": "Фиолетовое переливание",
            "/static/css/app.css": ".task-controls",
        }
        for path, expected_content in scripts.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_content, response.text)
        app_script = self.client.get("/static/js/app.js")
        self.assertIn("async function submitLanControl(event)", app_script.text)

    def test_lan_control_form_intercepts_submit_and_restores_button(self) -> None:
        html = self.client.get("/").text
        script = self.client.get("/static/js/app.js").text
        self.assertIn('id="lan-control-form"', html)
        self.assertIn('id="lan-control-ip"', html)
        self.assertIn('id="lan-control-confirm"', html)
        self.assertIn('id="lan-control-submit"', html)
        self.assertIn('id="lan-control-result"', html)
        self.assertIn(
            '$("#lan-control-form").addEventListener("submit", submitLanControl)',
            script,
        )

        handler = script[script.index("async function submitLanControl(event)"):]
        self.assertLess(
            handler.index("event.preventDefault();"),
            handler.index("if (lanControlSubmitting) return;"),
        )
        self.assertIn('apiRequest("/api/provisioning/lan-control"', handler)
        self.assertIn('result.textContent = "Выполняется…"', handler)
        self.assertIn("lanControlSubmitting = false;", handler)
        self.assertIn("submit.disabled = false;", handler)

    def test_health_check_is_public_and_does_not_expose_configuration(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_api_requires_token(self) -> None:
        protected_requests = (
            ("GET", "/api/bulbs", None),
            ("GET", "/api/settings", None),
            ("GET", "/api/modes", None),
            ("POST", "/api/commands", {"command": "list"}),
            (
                "POST",
                "/api/provisioning/wifi",
                {"ip": "192.168.13.1", "ssid": "POCO F4", "password": "test-pass-123"},
            ),
            (
                "POST",
                "/api/provisioning/lan-control",
                {"ip": "192.168.1.45"},
            ),
            ("POST", "/api/modes", {
                "name": "test",
                "steps": [{"action": "on", "values": []}],
            }),
            ("DELETE", "/api/modes/test", None),
            ("POST", "/api/modes/test/start", {"ip": "192.168.1.45"}),
            ("POST", "/api/modes/test/stop", None),
        )
        for method, path, payload in protected_requests:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=payload)
                self.assertEqual(response.status_code, 401)

    def test_command_and_bulb_listing(self) -> None:
        response = self.client.post(
            "/api/commands",
            json={"command": "on 192.168.1.45"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        response = self.client.get("/api/bulbs", headers=self.headers)
        self.assertEqual(len(response.json()["bulbs"]), 1)
        self.assertEqual(response.json()["bulbs"][0]["ip"], "192.168.1.45")
        self.assertTrue(response.json()["bulbs"][0]["online"])

    def test_wifi_provisioning_is_loopback_only_and_does_not_return_credentials(self) -> None:
        payload = {
            "ip": "192.168.13.1",
            "ssid": "POCO F4",
            "password": "test-pass-123",
        }
        remote_client = TestClient(create_app(), client=("192.168.1.20", 1234))
        denied = remote_client.post(
            "/api/provisioning/wifi", json=payload, headers=self.headers
        )
        self.assertEqual(denied.status_code, 403)

        local_client = TestClient(create_app(), client=("127.0.0.1", 1234))
        with patch("yeelight_network.api.configure_wifi", return_value="sent_unconfirmed") as configure:
            response = local_client.post(
                "/api/provisioning/wifi", json=payload, headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("test-pass-123", response.text)
        self.assertNotIn("password", response.text)
        configure.assert_called_once_with("192.168.13.1", "POCO F4", "test-pass-123")

        invalid = local_client.post(
            "/api/provisioning/wifi",
            json={**payload, "password": "short"},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("short", invalid.text)

    def test_lan_control_is_explicit_loopback_only_and_reports_unverified_status(self) -> None:
        payload = {"ip": "192.168.1.45", "confirmed": True}
        remote_client = TestClient(
            create_app(), client=("192.168.1.20", 1234)
        )
        denied = remote_client.post(
            "/api/provisioning/lan-control",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(denied.status_code, 403)

        local_client = TestClient(
            create_app(), client=("127.0.0.1", 1234)
        )
        with patch(
            "yeelight_network.api.enable_lan_control",
            return_value="responded_unverified",
        ) as enable:
            response = local_client.post(
                "/api/provisioning/lan-control",
                json=payload,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "responded_unverified")
        self.assertIn("does not yet confirm LAN Control", response.json()["message"])
        enable.assert_called_once_with("192.168.1.45")

    def test_lan_control_requires_explicit_confirmation(self) -> None:
        local_client = TestClient(
            create_app(), client=("127.0.0.1", 1234)
        )
        with patch("yeelight_network.api.enable_lan_control") as enable:
            response = local_client.post(
                "/api/provisioning/lan-control",
                json={"ip": "192.168.1.45"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 422)
        enable.assert_not_called()

    def test_lan_control_api_reports_device_errors(self) -> None:
        local_client = TestClient(
            create_app(), client=("127.0.0.1", 1234)
        )
        with patch(
            "yeelight_network.api.enable_lan_control",
            side_effect=MiIOError("The device did not answer the miIO handshake."),
        ):
            response = local_client.post(
                "/api/provisioning/lan-control",
                json={"ip": "192.168.1.45", "confirmed": True},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "The device did not answer the miIO handshake.",
        )

    def test_added_bulbs_are_persisted_via_api(self) -> None:
        storage_path = Path(self.temp_dir.name) / "bulbs.json"
        controller = YeelightController(storage_path=storage_path)
        client = TestClient(create_app(controller))
        response = client.post(
            "/api/commands",
            json={"command": "add 192.168.1.45"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(storage_path.is_file())

        restarted = YeelightController(storage_path=storage_path)
        self.assertEqual(restarted.known_bulbs(), [{"ip": "192.168.1.45"}])

    def test_bulb_storage_failure_is_reported_by_api(self) -> None:
        invalid_parent = Path(self.temp_dir.name) / "not-a-directory"
        invalid_parent.write_text("file", encoding="utf-8")
        client = TestClient(
            create_app(YeelightController(storage_path=invalid_parent / "bulbs.json"))
        )
        response = client.post(
            "/api/commands",
            json={"command": "add 192.168.1.45"},
        )
        self.assertEqual(response.status_code, 500)
        self.assertIn("Could not save lamp addresses", response.json()["detail"])

    def test_remove_lamp_and_manage_looping_mode(self) -> None:
        mode_file = Path(self.temp_dir.name) / "modes.json"
        client = TestClient(
            create_app(
                YeelightController(
                    ["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()
                ),
                api_token="test-token",
                modes_path=mode_file,
            )
        )
        with client:
            response = client.post(
                "/api/modes",
                json={
                    "name": "Вечер",
                    "steps": [
                        {"action": "on", "values": []},
                        {"action": "brightness", "values": [50]},
                        {"action": "color", "values": [0, 128, 255]},
                    ],
                    "delay_seconds": 0.1,
                },
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(mode_file.is_file())
            listed_modes = client.get("/api/modes", headers=self.headers).json()["modes"]
            self.assertEqual(len(listed_modes), 1)
            self.assertNotIn("192.168.1.45", str(listed_modes[0]["steps"]))
            start_response = client.post(
                "/api/modes/Вечер/start",
                json={"ip": "192.168.1.45"},
                headers=self.headers,
            )
            self.assertEqual(start_response.status_code, 200)
            self.assertEqual(start_response.json()["ip"], "192.168.1.45")
            self.assertEqual(
                client.post("/api/modes/Вечер/stop", headers=self.headers).status_code,
                200,
            )
            response = client.post(
                "/api/commands",
                json={"command": "remove 192.168.1.45"},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                client.get("/api/bulbs", headers=self.headers).json()["bulbs"],
                [],
            )

    def test_saved_legacy_mode_is_migrated_to_ip_independent_steps(self) -> None:
        mode_file = Path(self.temp_dir.name) / "legacy-modes.json"
        mode_file.write_text(
            json.dumps(
                {
                    "Старый режим": {
                        "commands": [
                            "on 192.168.1.45",
                            "brightness 192.168.1.45 50",
                            "color 192.168.1.45 #0080ff",
                        ],
                        "delay_seconds": 1,
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        client = TestClient(
            create_app(
                YeelightController(
                    ["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()
                ),
                api_token="test-token",
                modes_path=mode_file,
            )
        )
        modes = client.get("/api/modes", headers=self.headers).json()["modes"]
        self.assertEqual(
            modes[0]["steps"],
            [
                {"action": "on", "values": []},
                {"action": "brightness", "values": [50]},
                {"action": "color", "values": [0, 128, 255]},
            ],
        )
        self.assertNotIn("192.168.1.45", str(modes[0]["steps"]))

    def test_editing_saved_mode_replaces_and_persists_its_tasks(self) -> None:
        mode_file = Path(self.temp_dir.name) / "editable-modes.json"
        controller = YeelightController(
            ["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()
        )
        with TestClient(create_app(controller, modes_path=mode_file)) as client:
            headers = {}
            initial = client.post(
                "/api/modes",
                json={
                    "name": "Вечер",
                    "steps": [{"action": "on", "values": []}],
                    "delay_seconds": 1,
                },
                headers=headers,
            )
            self.assertEqual(initial.status_code, 200)
            updated = client.post(
                "/api/modes",
                json={
                    "name": "Вечер",
                    "steps": [
                        {"action": "brightness", "values": [35]},
                        {"action": "color", "values": [10, 20, 30]},
                        {"action": "off", "values": []},
                    ],
                    "delay_seconds": 2,
                },
                headers=headers,
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(len(client.get("/api/modes").json()["modes"]), 1)

        saved = json.loads(mode_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["Вечер"]["delay_seconds"], 2)
        self.assertEqual(
            saved["Вечер"]["steps"],
            [
                {"action": "brightness", "values": [35]},
                {"action": "color", "values": [10, 20, 30]},
                {"action": "off", "values": []},
            ],
        )
        reloaded = TestClient(create_app(controller, modes_path=mode_file))
        persisted = reloaded.get("/api/modes").json()["modes"]
        self.assertEqual(persisted[0]["steps"], saved["Вечер"]["steps"])

    def test_unresponsive_bulb_is_removed_after_configured_timeout(self) -> None:
        class OfflineBulb(FakeBulb):
            def get_properties(self):
                raise OSError("offline")

        controller = YeelightController(
            ["192.168.1.45"], bulb_factory=lambda _address: OfflineBulb()
        )
        client = TestClient(
            create_app(
                controller,
                api_token="test-token",
                poll_interval=0.01,
                offline_timeout=0.03,
            )
        )
        with client:
            time.sleep(0.08)
            response = client.get("/api/bulbs", headers=self.headers)
            self.assertEqual(response.json()["bulbs"], [])

    def test_invalid_command_returns_client_error(self) -> None:
        response = self.client.post(
            "/api/commands", json={"command": "unknown"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
