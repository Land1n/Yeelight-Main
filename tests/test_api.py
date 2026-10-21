import unittest
import time
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from yeelight_logic import YeelightController
from yeelight_network.api import create_app
from yeelight_network.miio import MiIOError, WifiSetupResult


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
        self.assertIn('id="reconnect"', response.text)
        self.assertIn('id="api-token"', response.text)
        self.assertIn('id="summary-bulbs"', response.text)
        self.assertIn('<a href="/bulbs"', response.text)
        self.assertIn('<a href="/modes"', response.text)
        self.assertIn('<a href="/console"', response.text)
        self.assertIn('<a href="/setup"', response.text)
        self.assertIn('<a href="/help"', response.text)
        self.assertIn("/static/css/app.css", response.text)
        self.assertIn("/static/js/page-home.js", response.text)

    def test_every_page_has_the_same_navigation(self) -> None:
        pages = {
            "/": "home",
            "/bulbs": "bulbs",
            "/modes": "modes",
            "/console": "console",
            "/setup": "setup",
            "/help": "help",
        }
        for path, page in pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'data-page="{page}"', response.text)
                self.assertEqual(
                    response.text.count('<nav class="topnav"'), 1
                )
                for link in ("/bulbs", "/modes", "/console", "/setup", "/help"):
                    self.assertIn(f'href="{link}"', response.text)
                self.assertEqual(
                    response.text.count('aria-current="page"'),
                    1,
                    f"{path} should mark exactly one active page",
                )

    def test_pages_hold_their_own_controls(self) -> None:
        bulbs = self.client.get("/bulbs")
        self.assertIn('id="bulbs"', bulbs.text)
        self.assertIn('id="discover"', bulbs.text)
        self.assertIn('id="monitor-settings"', bulbs.text)
        self.assertNotIn('id="wifi-form"', bulbs.text)

        modes = self.client.get("/modes")
        self.assertIn('id="mode-form"', modes.text)
        self.assertIn('id="task-list"', modes.text)
        self.assertIn('id="mode-presets"', modes.text)

        console = self.client.get("/console")
        self.assertIn('id="command-form"', console.text)
        self.assertIn('id="output"', console.text)

        setup = self.client.get("/setup")
        self.assertIn('class="wifi-fields"', setup.text)
        self.assertIn('class="wifi-confirm"', setup.text)
        self.assertIn(
            '<input id="wifi-enable-lan-control" type="checkbox">',
            setup.text,
        )
        self.assertIn('id="wifi-lan-control-result"', setup.text)
        self.assertIn('id="lan-control-form"', setup.text)
        self.assertIn("Отдельно включить LAN Control", setup.text)
        self.assertIn('minlength="8"', setup.text)
        self.assertIn("field-hint", setup.text)

        help_page = self.client.get("/help")
        self.assertIn('class="steps"', help_page.text)
        self.assertIn('class="faq"', help_page.text)

    def test_token_panel_is_shared_and_hidden_until_needed(self) -> None:
        for path in ("/bulbs", "/modes", "/console", "/setup"):
            with self.subTest(path=path):
                page = self.client.get(path)
                self.assertIn('id="token-panel"', page.text)
                self.assertIn('<input id="api-token"', page.text)
                self.assertIn('hidden>', page.text)

    def test_static_frontend_modules_are_served(self) -> None:
        scripts = {
            "/static/js/page.js": "export function startPage",
            "/static/js/api.js": "function formatError(detail)",
            "/static/js/page-home.js": "async function refreshSummary",
            "/static/js/page-bulbs.js": "new BulbList(",
            "/static/js/page-modes.js": "async function saveMode(context, event)",
            "/static/js/page-console.js": "runCommand(context, text)",
            "/static/js/page-setup.js": "async function submitWifiSetup(event)",
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
        setup_script = self.client.get("/static/js/page-setup.js")
        self.assertIn("async function submitLanControl()", setup_script.text)
        self.assertIn(
            "enable_lan_control: enableLanControl",
            setup_script.text,
        )

    def test_lan_control_button_does_not_submit_form_and_restores_state(self) -> None:
        html = self.client.get("/setup").text
        script = self.client.get("/static/js/page-setup.js").text.replace("\r\n", "\n")
        self.assertIn('id="lan-control-form"', html)
        self.assertIn('id="lan-control-ip"', html)
        self.assertIn('id="lan-control-confirm"', html)
        self.assertIn('id="lan-control-submit"', html)
        self.assertIn('id="lan-control-result"', html)
        self.assertIn(
            'id="lan-control-submit" class="primary wifi-submit" type="button"',
            html,
        )
        self.assertIn(
            '$("#lan-control-submit").addEventListener("click", submitLanControl)',
            script,
        )

        self.assertIn(
            '$("#lan-control-form").addEventListener("submit", (event) => {\n'
            '      event.preventDefault();\n'
            "      submitLanControl();\n"
            "    });",
            script,
        )
        handler = script[script.index("async function submitLanControl()"):]
        self.assertIn("if (lanControlSubmitting) return;", handler)
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
            "/api/provisioning/wifi",
            json={**payload, "enable_lan_control": True},
            headers=self.headers,
        )
        self.assertEqual(denied.status_code, 403)

        local_client = TestClient(create_app(), client=("127.0.0.1", 1234))
        with patch(
            "yeelight_network.api.configure_wifi",
            return_value=WifiSetupResult("sent_unconfirmed", "not_requested"),
        ) as configure:
            response = local_client.post(
                "/api/provisioning/wifi", json=payload, headers=self.headers
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sent_unconfirmed")
        self.assertEqual(response.json()["lan_control_status"], "not_requested")
        self.assertIn("не запрашивалась", response.json()["lan_control_message"])
        self.assertNotIn("test-pass-123", response.text)
        self.assertNotIn("password", response.text)
        configure.assert_called_once_with(
            "192.168.13.1",
            "POCO F4",
            "test-pass-123",
            enable_lan_control=False,
        )

        invalid = local_client.post(
            "/api/provisioning/wifi",
            json={**payload, "password": "short"},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("short", invalid.text)

    def test_wifi_setup_reports_mixed_wifi_and_lan_control_outcomes(self) -> None:
        local_client = TestClient(create_app(), client=("127.0.0.1", 1234))
        payload = {
            "ip": "192.168.13.1",
            "ssid": "POCO F4",
            "password": "test-pass-123",
            "enable_lan_control": True,
        }
        with patch(
            "yeelight_network.api.configure_wifi",
            return_value=WifiSetupResult(
                "responded_unverified",
                "sent_unconfirmed",
            ),
        ) as configure:
            response = local_client.post(
                "/api/provisioning/wifi",
                json=payload,
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "responded_unverified")
        self.assertEqual(
            response.json()["lan_control_status"],
            "sent_unconfirmed",
        )
        self.assertIn("не подтверждено", response.json()["lan_control_message"])
        configure.assert_called_once_with(
            "192.168.13.1",
            "POCO F4",
            "test-pass-123",
            enable_lan_control=True,
        )

    def test_wifi_setup_token_error_is_clear_and_does_not_claim_success(self) -> None:
        local_client = TestClient(create_app(), client=("127.0.0.1", 1234))
        with patch(
            "yeelight_network.api.configure_wifi",
            side_effect=MiIOError(
                "The device did not provide a usable miIO token.",
                code="token_unavailable",
            ),
        ):
            response = local_client.post(
                "/api/provisioning/wifi",
                json={
                    "ip": "192.168.13.1",
                    "ssid": "POCO F4",
                    "password": "test-pass-123",
                    "enable_lan_control": True,
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("не предоставила пригодный токен", detail["message"])
        self.assertEqual(detail["wifi_status"], "not_sent")
        self.assertEqual(detail["lan_control_status"], "not_attempted")
        self.assertNotIn("test-pass-123", response.text)

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
        self.assertIn("ещё не подтверждает LAN Control", response.json()["message"])
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
            side_effect=MiIOError(
                "The device did not answer the miIO handshake.",
                code="handshake_timeout",
            ),
        ):
            response = local_client.post(
                "/api/provisioning/lan-control",
                json={"ip": "192.168.1.45", "confirmed": True},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Лампа не ответила на miIO handshake.",
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

    def test_mode_reuses_bulb_and_recovers_from_transient_failures(self) -> None:
        class FlakyBulb(FakeBulb):
            def __init__(self) -> None:
                self.calls = 0

            def set_rgb(self, red: int, green: int, blue: int) -> None:
                self.calls += 1
                if self.calls <= 2:
                    raise RuntimeError("temporary socket error")

        mode_file = Path(self.temp_dir.name) / "flaky-modes.json"
        controller = YeelightController(
            ["192.168.1.45"], bulb_factory=lambda _address: FlakyBulb()
        )
        with TestClient(
            create_app(controller, api_token="test-token", modes_path=mode_file)
        ) as client:
            client.post(
                "/api/modes",
                json={
                    "name": "Мигание",
                    "steps": [{"action": "color", "values": [120, 0, 200]}],
                    "delay_seconds": 0.1,
                },
                headers=self.headers,
            )
            response = client.post(
                "/api/modes/Мигание/start",
                json={"ip": "192.168.1.45"},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200)
            saw_error = False
            mode = None
            deadline = time.time() + 10
            while time.time() < deadline:
                mode = client.get("/api/modes", headers=self.headers).json()["modes"][0]
                if mode["last_error"]:
                    saw_error = True
                elif saw_error:
                    break
                time.sleep(0.05)
            self.assertTrue(saw_error)
            self.assertIsNone(mode["last_error"])
            self.assertTrue(mode["running"])
            client.post("/api/modes/Мигание/stop", headers=self.headers)

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
            ["192.168.1.45"],
            bulb_factory=lambda _address: OfflineBulb(),
            min_command_interval=0,
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

    def test_mode_with_invalid_values_is_rejected_before_saving(self) -> None:
        mode_file = Path(self.temp_dir.name) / "modes.json"
        client = TestClient(
            create_app(
                YeelightController(["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()),
                api_token="test-token",
                modes_path=mode_file,
            )
        )
        invalid_steps = (
            [{"action": "brightness", "values": [500]}],
            [{"action": "temp", "values": [1000]}],
            [{"action": "color", "values": [0, 0, 256]}],
            [{"action": "color", "values": [True, 0, 0]}],
            [{"action": "on", "values": [1]}],
        )
        for steps in invalid_steps:
            with self.subTest(steps=steps):
                response = client.post(
                    "/api/modes",
                    json={"name": "Плохой", "steps": steps, "delay_seconds": 1},
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 422)
        self.assertFalse(mode_file.exists())

    def test_unknown_wifi_status_does_not_crash_the_error_mapping(self) -> None:
        from yeelight_network.api import _wifi_status_message

        self.assertIn("Неизвестный результат", _wifi_status_message("unexpected"))

    def test_web_client_reports_invalid_api_token_instead_of_connection_error(self) -> None:
        script = self.client.get("/static/js/page.js").text
        self.assertIn("error.httpStatus === 401", script)
        self.assertIn("Неверный API-токен", script)


    def test_mode_storage_failure_is_reported(self) -> None:
        invalid_parent = Path(self.temp_dir.name) / "modes-not-a-directory"
        invalid_parent.write_text("file", encoding="utf-8")
        client = TestClient(
            create_app(modes_path=invalid_parent / "modes.json", api_token="test-token")
        )
        response = client.post(
            "/api/modes",
            json={"name": "Вечер", "steps": [{"action": "on", "values": []}]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Could not save modes")




if __name__ == "__main__":
    unittest.main()
