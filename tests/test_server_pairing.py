from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import APITestCase, login
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class PairingTests(APITestCase):
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

    def _create_pairing_code(self, name="Test manager"):
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/managers/pairing-codes",
            json={"name": name},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["code"]

    def test_create_and_consume_pairing_code(self) -> None:
        code = self._create_pairing_code()
        response = self.client.post(
            "/api/v1/managers/pair",
            json={"code": code, "name": "Test manager", "version": "0.2.0"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("token", body)
        self.assertTrue(body["token"].startswith("ylm_"))
        self.assertEqual(body["manager"]["name"], "Test manager")
        self.assertEqual(body["ws_path"], "/api/v1/managers/ws")

    def test_pairing_code_is_single_use(self) -> None:
        code = self._create_pairing_code()
        self.client.post(
            "/api/v1/managers/pair",
            json={"code": code, "name": "Test manager"},
        )
        response = self.client.post(
            "/api/v1/managers/pair",
            json={"code": code, "name": "Test manager 2"},
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_pairing_code(self) -> None:
        response = self.client.post(
            "/api/v1/managers/pair",
            json={"code": "BADCODE", "name": "Test manager"},
        )
        self.assertEqual(response.status_code, 401)

    def test_pairing_code_requires_name(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/managers/pairing-codes",
            json={},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201)

    def test_pairing_code_missing_csrf(self) -> None:
        login(self.client)
        response = self.client.post(
            "/api/v1/managers/pairing-codes", json={"name": "x"}
        )
        self.assertEqual(response.status_code, 403)

    def test_duplicate_manager_name_conflict(self) -> None:
        code = self._create_pairing_code("First")
        self.client.post(
            "/api/v1/managers/pair",
            json={"code": code, "name": "Same Name"},
        )
        code2 = self._create_pairing_code("Second")
        response = self.client.post(
            "/api/v1/managers/pair",
            json={"code": code2, "name": "Same Name"},
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
