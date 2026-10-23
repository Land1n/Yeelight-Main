from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER_URL = "http://127.0.0.1:8000"
ADMIN_PASSWORD = "e2e-test-password-1234"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


class E2ETests(unittest.TestCase):
    """End-to-end checks that start real server and manager processes.

    Enabled only with YEELIGHT_TEST_E2E=1. No hardware lamp is required.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not _env_flag("YEELIGHT_TEST_E2E"):
            raise unittest.SkipTest("Set YEELIGHT_TEST_E2E=1 to run e2e tests.")
        cls.server_proc = None
        cls._start_server()
        cls._wait_for_health()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server_proc is not None:
            cls.server_proc.terminate()
            try:
                cls.server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.server_proc.kill()

    @classmethod
    def _start_server(cls) -> None:
        env = dict(os.environ)
        env["YEELIGHT_SERVER_HOST"] = "127.0.0.1"
        env["YEELIGHT_SERVER_PORT"] = "8000"
        env["YEELIGHT_SERVER_ADMIN_PASSWORD"] = ADMIN_PASSWORD
        env["YEELIGHT_SERVER_DB"] = str(ROOT / "data" / "e2e_server.db")
        cls.server_proc = subprocess.Popen(
            [str(VENV_PY), "-m", "yeelight_server"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _wait_for_health(cls, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            try:
                response = requests.get(f"{SERVER_URL}/api/health", timeout=1.0)
                if response.status_code == 200:
                    return
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.5)
        raise RuntimeError(f"Server did not become healthy: {last_error}")

    def _post_json(self, path, payload):
        return requests.post(f"{SERVER_URL}{path}", json=payload, timeout=5.0)

    def test_login_pairing_and_manager_list(self) -> None:
        response = self._post_json(
            "/api/v1/auth/login",
            {"username": "admin", "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        csrf = response.json()["csrf_token"]
        cookies = response.cookies

        response = requests.post(
            f"{SERVER_URL}/api/v1/managers/pairing-codes",
            json={"name": "E2E Manager"},
            headers={"X-CSRF-Token": csrf, "Cookie": f"yl_session={cookies.get('yl_session')}"},
            timeout=5.0,
        )
        self.assertEqual(response.status_code, 201)
        code = response.json()["code"]

        response = self._post_json(
            "/api/v1/managers/pair",
            {"code": code, "name": "E2E Manager", "version": "0.2.0"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["token"].startswith("ylm_"))

        response = requests.get(
            f"{SERVER_URL}/api/v1/managers",
            headers={"X-CSRF-Token": csrf, "Cookie": f"yl_session={cookies.get('yl_session')}"},
            timeout=5.0,
        )
        self.assertEqual(response.status_code, 200)
        names = [m["name"] for m in response.json()["managers"]]
        self.assertIn("E2E Manager", names)

    def test_command_when_manager_offline(self) -> None:
        response = requests.post(
            f"{SERVER_URL}/api/v1/auth/login",
            json={"username": "admin", "password": ADMIN_PASSWORD},
            timeout=5.0,
        )
        csrf = response.json()["csrf_token"]
        cookies = response.cookies

        response = requests.post(
            f"{SERVER_URL}/api/v1/commands",
            json={
                "manager_id": "mgr_does_not_exist",
                "action": "status",
                "ip": "192.168.1.10",
            },
            headers={"X-CSRF-Token": csrf, "Cookie": f"yl_session={cookies.get('yl_session')}"},
            timeout=5.0,
        )
        self.assertEqual(response.status_code, 404)


@unittest.skipUnless(_env_flag("YEELIGHT_TEST_LAMP_IP"), "Requires YEELIGHT_TEST_LAMP_IP")
class HardwareLampTests(unittest.TestCase):
    """Opt-in checks against a real lamp. Set YEELIGHT_TEST_LAMP_IP."""

    def setUp(self) -> None:
        from yeelight_logic import Bulb

        self.bulb = Bulb(os.getenv("YEELIGHT_TEST_LAMP_IP"))

    def tearDown(self) -> None:
        self.bulb.close()

    def test_status_and_power(self) -> None:
        status = self.bulb.get_status()
        self.assertIn("ip", status)
        self.assertIn("properties", status)

    def test_brightness_and_toggle(self) -> None:
        self.bulb.set_brightness(50)
        self.bulb.turn_on()
        self.bulb.toggle()
        self.assertEqual(self.bulb.properties.get("power"), "off")


if __name__ == "__main__":
    unittest.main()
