from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import APITestCase, login, pair_test_manager
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class ManagerWebSocketTests(APITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.settings = Settings(
            host="127.0.0.1",
            port=8000,
            db_path=Path(self.tmpdir) / "server.db",
            admin_username="admin",
            admin_password="admin-test-password",
            session_ttl_seconds=3600,
            secure_cookies=False,
            command_timeout_seconds=2.0,
            max_command_wait_seconds=3.0,
            heartbeat_interval_seconds=10,
        )
        self.app = create_app(self.settings)
        self.client = self._enter_client(self.app)
        self.manager_id, self.token = pair_test_manager(self.client)

    def test_connect_sends_hello(self) -> None:
        with self.client.websocket_connect(
            "/api/v1/managers/ws",
            headers={"Authorization": f"Bearer {self.token}"},
        ) as ws:
            data = json.loads(ws.receive_text())
            self.assertEqual(data["type"], "hello")
            self.assertEqual(data["manager_id"], self.manager_id)

    def test_invalid_token_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            self.client.websocket_connect(
                "/api/v1/managers/ws",
                headers={"Authorization": "Bearer bad-token"},
            )

    def test_hello_and_lamps_from_manager(self) -> None:
        with self.client.websocket_connect(
            "/api/v1/managers/ws",
            headers={"Authorization": f"Bearer {self.token}"},
        ) as ws:
            json.loads(ws.receive_text())  # hello
            ws.send_text(
                json.dumps(
                    {
                        "type": "hello",
                        "version": "0.2.0",
                        "lamps": [
                            {
                                "ip": "192.168.1.10",
                                "name": "Lamp",
                                "model": "yeelink.light.color1",
                                "online": True,
                            }
                        ],
                    }
                )
            )
            # After hello, manager is online. Verify via API.
            csrf = login(self.client)
            response = self.client.get(
                f"/api/v1/managers/{self.manager_id}/lamps",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 200)
            lamps = response.json()["lamps"]
            self.assertEqual(len(lamps), 1)
            self.assertEqual(lamps[0]["ip"], "192.168.1.10")

    def test_command_result_updates_command(self) -> None:
        # Connect the manager and report a lamp so it is online and the lamp
        # is known to the server.
        with self.client.websocket_connect(
            "/api/v1/managers/ws",
            headers={"Authorization": f"Bearer {self.token}"},
        ) as ws:
            json.loads(ws.receive_text())  # hello
            ws.send_text(
                json.dumps(
                    {
                        "type": "hello",
                        "version": "0.2.0",
                        "lamps": [
                            {
                                "ip": "192.168.1.10",
                                "name": "Lamp",
                                "model": "yeelink.light.color1",
                                "online": True,
                            }
                        ],
                    }
                )
            )

            csrf = login(self.client)
            command_response = self.client.post(
                "/api/v1/commands",
                json={
                    "manager_id": self.manager_id,
                    "action": "status",
                    "ip": "192.168.1.10",
                    "wait": False,
                },
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(command_response.status_code, 202)
            command_id = command_response.json()["command"]["id"]

            ws.send_text(
                json.dumps(
                    {
                        "type": "command_result",
                        "command_id": command_id,
                        "ok": True,
                        "result": {"power": "on"},
                    }
                )
            )

        response = self.client.get(
            f"/api/v1/commands/{command_id}", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["command"]["status"], "completed")
        self.assertEqual(response.json()["command"]["result"], {"power": "on"})

    def test_invalid_token_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            with self.client.websocket_connect(
                "/api/v1/managers/ws",
                headers={"Authorization": "Bearer bad-token"},
            ) as ws:
                ws.receive_text()
