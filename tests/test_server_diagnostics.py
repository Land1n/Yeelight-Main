from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import APITestCase, login, pair_test_manager
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class DiagnosticsTests(APITestCase):
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
        self.manager_id, _ = pair_test_manager(self.client)

    def test_settings_are_safe(self) -> None:
        csrf = login(self.client)
        response = self.client.get("/api/v1/settings", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        settings = response.json()["settings"]
        self.assertFalse(settings["features"]["direct_lamp_access"])
        self.assertFalse(settings["features"]["wifi_provisioning"])
        self.assertTrue(settings["features"]["manager_relay"])

    def test_diagnostics(self) -> None:
        csrf = login(self.client)
        response = self.client.get("/api/v1/diagnostics", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)
        self.assertIn("uptime_seconds", data)
        self.assertIn("managers", data)
        self.assertIn("commands", data)
        self.assertIn("recent_audit", data)

    def test_audit(self) -> None:
        csrf = login(self.client)
        response = self.client.get("/api/v1/audit", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertIn("events", response.json())

    def test_diagnostics_requires_auth(self) -> None:
        self.client.cookies.clear()
        response = self.client.get("/api/v1/diagnostics")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
