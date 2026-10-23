from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests.support import APITestCase, login, pair_test_manager
from yeelight_server.app import create_app
from yeelight_server.config import Settings


class ModesTests(APITestCase):
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
            legacy_modes_file=None,
        )
        self.app = create_app(self.settings)
        self.client = self._enter_client(self.app)
        self.manager_id, _ = pair_test_manager(self.client)

    def _create_mode(self, name="Blink", steps=None, delay=1.0):
        if steps is None:
            steps = [
                {"action": "on", "values": []},
                {"action": "brightness", "values": [80]},
                {"action": "off", "values": []},
            ]
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/modes",
            json={"name": name, "steps": steps, "delay_seconds": delay},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["mode"]

    def test_crud_mode(self) -> None:
        mode = self._create_mode()
        mode_id = mode["id"]

        response = self.client.get(f"/api/v1/modes/{mode_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"]["name"], "Blink")

        response = self.client.get("/api/v1/modes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["modes"]), 1)

        response = self.client.post(
            "/api/v1/modes",
            json={
                "name": "Blink",
                "steps": [{"action": "on", "values": []}],
                "delay_seconds": 2.0,
            },
            headers={"X-CSRF-Token": login(self.client)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"]["name"], "Blink")
        self.assertEqual(response.json()["mode"]["delay_seconds"], 2.0)

        response = self.client.delete(f"/api/v1/modes/{mode_id}", headers={"X-CSRF-Token": login(self.client)})
        self.assertEqual(response.status_code, 200)

        response = self.client.get(f"/api/v1/modes/{mode_id}")
        self.assertEqual(response.status_code, 404)

    def test_mode_validation(self) -> None:
        csrf = login(self.client)
        response = self.client.post(
            "/api/v1/modes",
            json={"name": "", "steps": [], "delay_seconds": 1.0},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/v1/modes",
            json={
                "name": "Bad",
                "steps": [{"action": "wifi", "values": []}],
                "delay_seconds": 1.0,
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 422)

    def test_start_and_stop_mode(self) -> None:
        mode = self._create_mode()
        mode_id = mode["id"]
        csrf = login(self.client)

        # The lamp must be known to the manager before a mode can run on it.
        self.app.state.ctx.db.replace_lamps(
            self.manager_id, [{"ip": "192.168.1.10", "name": "Lamp"}]
        )

        response = self.client.post(
            f"/api/v1/modes/{mode_id}/start",
            json={"manager_id": self.manager_id, "ip": "192.168.1.10"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["mode"]["running"])

        response = self.client.post(
            f"/api/v1/modes/{mode_id}/stop", headers={"X-CSRF-Token": csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "stopped")

    def test_cannot_start_unknown_manager_or_lamp(self) -> None:
        mode = self._create_mode()
        mode_id = mode["id"]
        csrf = login(self.client)

        response = self.client.post(
            f"/api/v1/modes/{mode_id}/start",
            json={"manager_id": "mgr_unknown", "ip": "192.168.1.10"},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 404)


class LegacyModesImportTests(unittest.TestCase):
    def test_import_legacy_modes_once(self) -> None:
        import tempfile
        from pathlib import Path

        from yeelight_server.services.modes import import_legacy_modes
        from yeelight_server.storage import Database

        tmpdir = tempfile.mkdtemp()
        db = Database(Path(tmpdir) / "server.db")
        user = db.create_user("admin", "hash")
        modes_file = Path(tmpdir) / "modes.json"
        modes_file.write_text(
            json.dumps(
                {
                    "Old Blink": {
                        "steps": [{"action": "on", "values": []}, {"action": "off", "values": []}],
                        "delay_seconds": 1.0,
                    }
                }
            ),
            encoding="utf-8",
        )
        imported = import_legacy_modes(db, user["id"], modes_file)
        self.assertEqual(imported, 1)
        imported_again = import_legacy_modes(db, user["id"], modes_file)
        self.assertEqual(imported_again, 0)
        modes = db.list_modes(user["id"])
        self.assertEqual(len(modes), 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
