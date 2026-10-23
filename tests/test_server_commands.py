from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import APITestCase, login, pair_test_manager
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class CommandTests(APITestCase):
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
        self.manager_id, self.manager_token = pair_test_manager(self.client)

    def test_command_when_manager_offline(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={
                "manager_id": self.manager_id,
                "action": "discover",
                "wait": True,
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["message"], "Manager is not connected")

    def test_command_wait_false_is_accepted(self) -> None:
        csrf = login(self.client)
        with self.client.websocket_connect(
            "/api/v1/managers/ws",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        ) as ws:
            json.loads(ws.receive_text())  # hello
            response = self.client.post(
                "/api/v1/commands",
                json={
                    "manager_id": self.manager_id,
                    "action": "discover",
                    "wait": False,
                },
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["command"]["status"], "delivered")

    def test_invalid_action_is_rejected(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={
                "manager_id": self.manager_id,
                "action": "wifi",
                "ip": "192.168.1.10",
                "params": {},
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_lamp_is_rejected(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={
                "manager_id": self.manager_id,
                "action": "power",
                "ip": "192.168.1.99",
                "params": {"state": "on"},
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 404)

    def test_add_requires_ip(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={"manager_id": self.manager_id, "action": "add"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_discover_rejects_ip(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={
                "manager_id": self.manager_id,
                "action": "discover",
                "ip": "192.168.1.10",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_command_history_endpoint(self) -> None:
        csrf = login(self.client)
        response = self.client.get("/api/v1/commands", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertIn("commands", response.json())


if __name__ == "__main__":
    unittest.main()
