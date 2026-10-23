from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support import APITestCase, login
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class AuthTests(APITestCase):
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

    def test_health_is_public(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_login_and_me(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-test-password"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["username"], "admin")
        self.assertIn("csrf_token", body)
        self.assertIn("expires_at", body)
        self.assertIn("yl_session", response.headers.get("set-cookie", ""))

        csrf = body["csrf_token"]
        response = self.client.get(
            "/api/v1/auth/me", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "admin")

    def test_login_rejects_wrong_password(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookie(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "logged_out"})

    def test_csrf_required_for_state_changing(self) -> None:
        login(self.client)
        response = self.client.post(
            "/api/v1/commands",
            json={"manager_id": "mgr_x", "action": "status", "ip": "1.2.3.4"},
        )
        self.assertEqual(response.status_code, 403)

    def test_session_cookie_is_httponly_and_samesite(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-test-password"},
        )
        cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)

    def test_secure_cookie_flag_when_enabled(self) -> None:
        settings = Settings(
            host=self.settings.host,
            port=self.settings.port,
            db_path=Path(self.tmpdir) / "secure.db",
            admin_username=self.settings.admin_username,
            admin_password=self.settings.admin_password,
            secure_cookies=True,
        )
        app = create_app(settings)
        client = self._enter_client(app)
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-test-password"},
        )
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("Secure", cookie)


class AdminCreationTests(APITestCase):
    def test_no_password_on_empty_database_fails(self) -> None:
        settings = Settings(
            host="127.0.0.1",
            port=8000,
            db_path=Path(tempfile.mkdtemp()) / "server.db",
            admin_username="admin",
            admin_password="",
        )
        app = create_app(settings)
        with self.assertRaises(RuntimeError):
            with TestClient(app, follow_redirects=False):
                pass


if __name__ == "__main__":
    unittest.main()
