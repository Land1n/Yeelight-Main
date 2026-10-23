from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yeelight_server.security.tokens import hash_password
from yeelight_server.storage import Database


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(Path(self.tmpdir) / "server.db")

    def tearDown(self) -> None:
        self.db.close()

    def test_user_and_session(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        self.assertEqual(user["username"], "admin")
        self.assertEqual(self.db.count_users(), 1)

        session = self.db.create_session(
            user_id=user["id"],
            token_hash="abcd",
            csrf_token="csrf",
            expires_at=9999999999,
        )
        got = self.db.get_session("abcd")
        self.assertIsNotNone(got)
        self.assertEqual(got["user_id"], user["id"])
        self.assertEqual(got["csrf_token"], "csrf")

        self.db.delete_session(session["id"])
        self.assertIsNone(self.db.get_session("abcd"))

    def test_expired_session_is_purged(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        self.db.create_session(
            user_id=user["id"],
            token_hash="expired",
            csrf_token="csrf",
            expires_at=1,
        )
        self.assertEqual(self.db.purge_expired_sessions(), 1)
        self.assertIsNone(self.db.get_session("expired"))

    def test_manager_pairing_flow(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        record = self.db.create_pairing_code(user["id"], "hash", 600)
        manager = self.db.consume_pairing_code(
            code_hash="hash",
            manager_name="Home",
            manager_token_hash="tokenhash",
            version="0.2.0",
        )
        self.assertEqual(manager["name"], "Home")
        self.assertEqual(manager["user_id"], user["id"])

        used = self.db.consume_pairing_code(
            code_hash="hash",
            manager_name="Home2",
            manager_token_hash="tokenhash2",
            version=None,
        )
        self.assertIsNone(used)

        managers = self.db.get_managers(user["id"])
        self.assertEqual(len(managers), 1)
        self.assertTrue(self.db.delete_manager(manager["id"], user["id"]))
        self.assertEqual(len(self.db.get_managers(user["id"])), 0)

    def test_lamps_replace(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        self.db.create_pairing_code(user["id"], "hash", 600)
        manager = self.db.consume_pairing_code(
            code_hash="hash",
            manager_name="Home",
            manager_token_hash="tokenhash",
            version=None,
        )
        self.db.replace_lamps(
            manager["id"],
            [{"ip": "192.168.1.10"}, {"ip": "192.168.1.11", "name": "Lamp"}],
        )
        lamps = self.db.get_lamps(manager["id"])
        self.assertEqual(len(lamps), 2)

        # Replace drops the removed lamp and updates the kept one.
        self.db.replace_lamps(
            manager["id"],
            [{"ip": "192.168.1.10", "name": "Updated"}],
        )
        lamps = self.db.get_lamps(manager["id"])
        self.assertEqual(len(lamps), 1)
        self.assertEqual(lamps[0]["name"], "Updated")

    def test_command_lifecycle(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        self.db.create_pairing_code(user["id"], "hash", 600)
        manager = self.db.consume_pairing_code(
            code_hash="hash",
            manager_name="Home",
            manager_token_hash="tokenhash",
            version=None,
        )
        command = self.db.create_command(
            user_id=user["id"],
            manager_id=manager["id"],
            action="power",
            ip="192.168.1.10",
            params={"state": "on"},
            timeout_seconds=15.0,
        )
        self.assertEqual(command["status"], "pending")

        delivered = self.db.mark_command_delivered(command["id"])
        self.assertEqual(delivered["status"], "delivered")

        finished = self.db.finish_command(
            command["id"],
            "completed",
            result={"power": "on"},
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["result"], {"power": "on"})

    def test_mode_crud(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        mode = self.db.upsert_mode(
            user_id=user["id"],
            name="Blink",
            steps=[{"action": "on", "values": []}],
            delay_seconds=1.0,
        )
        self.assertEqual(mode["name"], "Blink")

        got = self.db.get_mode(mode["id"], user["id"])
        self.assertEqual(got["steps"], [{"action": "on", "values": []}])

        updated = self.db.upsert_mode(
            user_id=user["id"],
            name="Blink",
            steps=[{"action": "off", "values": []}],
            delay_seconds=2.0,
        )
        self.assertEqual(updated["id"], mode["id"])
        self.assertEqual(updated["delay_seconds"], 2.0)

        self.assertTrue(self.db.delete_mode(mode["id"], user["id"]))
        self.assertIsNone(self.db.get_mode(mode["id"], user["id"]))

    def test_audit(self) -> None:
        user = self.db.create_user("admin", hash_password("secret"))
        self.db.audit(
            actor_type="user",
            actor_id=user["id"],
            action="login",
            target=user["id"],
            outcome="success",
        )
        events = self.db.list_audit(user["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "login")


if __name__ == "__main__":
    unittest.main()
