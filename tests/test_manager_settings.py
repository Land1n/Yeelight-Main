from __future__ import annotations

import unittest
from pathlib import Path

from yeelight_manager.settings import (
    ManagerSettings,
    normalize_server_url,
    websocket_url,
)


class ManagerSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = ManagerSettings()
        self.assertEqual(settings.server_url, "http://127.0.0.1:8000")
        self.assertEqual(settings.local_api_host, "127.0.0.1")
        self.assertEqual(settings.local_api_port, 8765)
        self.assertTrue(settings.local_api_enabled)
        self.assertTrue(settings.ui_enabled)
        self.assertEqual(settings.websocket_path, "/api/v1/managers/ws")

    def test_state_files_are_under_home(self) -> None:
        home = Path("/home/user/cfg")
        settings = ManagerSettings(home=home)
        self.assertEqual(settings.state_file, home / "state.json")
        self.assertEqual(settings.token_file, home / "token.bin")
        self.assertEqual(settings.bulbs_file, home / "bulbs.json")

    def test_local_host_must_be_loopback(self) -> None:
        import os

        old = os.environ.get("YEELIGHT_MANAGER_LOCAL_HOST")
        os.environ["YEELIGHT_MANAGER_LOCAL_HOST"] = "0.0.0.0"
        try:
            with self.assertRaises(ValueError):
                ManagerSettings.from_env()
        finally:
            if old is None:
                os.environ.pop("YEELIGHT_MANAGER_LOCAL_HOST", None)
            else:
                os.environ["YEELIGHT_MANAGER_LOCAL_HOST"] = old

    def test_normalize_server_url_rejects_invalid(self) -> None:
        for value in (
            "not-a-url",
            "http://",
            "http://user:pass@host",
            "http://host/path",
            "http://host?q=1",
            "ftp://host",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_server_url(value)

    def test_normalize_server_url_canonicalises(self) -> None:
        self.assertEqual(
            normalize_server_url("http://127.0.0.1:8000"),
            "http://127.0.0.1:8000",
        )
        self.assertEqual(
            normalize_server_url("http://[::1]:8000/"),
            "http://[::1]:8000",
        )

    def test_websocket_url(self) -> None:
        self.assertEqual(
            websocket_url("http://127.0.0.1:8000"),
            "ws://127.0.0.1:8000/api/v1/managers/ws",
        )
        self.assertEqual(
            websocket_url("https://192.168.1.10:8443"),
            "wss://192.168.1.10:8443/api/v1/managers/ws",
        )


if __name__ == "__main__":
    unittest.main()
