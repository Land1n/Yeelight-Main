from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from yeelight_logic import CommandResult
from yeelight_manager.agent import ManagerAgent, agent_status_text

from tests.support import FakeAgentSocket, FakeRuntime, manager_settings


class AgentStatusTextTests(unittest.TestCase):
    def test_all_states(self) -> None:
        self.assertEqual(agent_status_text({"state": "connected"}), "Подключён")
        self.assertEqual(agent_status_text({"state": "unpaired"}), "Не привязан")
        self.assertEqual(agent_status_text({"state": "removed"}), "Удалён на сервере")
        self.assertEqual(agent_status_text({"state": "unknown"}), "unknown")


class ManagerAgentCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = manager_settings(tempfile.mkdtemp())
        self.runtime = FakeRuntime()
        self.agent = ManagerAgent(
            self.settings,
            self.runtime,
            token_provider=lambda: "ylm_test_token",
        )

    def test_handle_command_uses_runtime_and_caches_result(self) -> None:
        socket = FakeAgentSocket()
        handler = mock.Mock(
            return_value=CommandResult(True, "ok", data={"power": "on"})
        )
        self.runtime.action_handler = handler

        asyncio.run(
            self.agent._handle_command(
                socket,
                {
                    "type": "command",
                    "command_id": "cmd-1",
                    "action": "power",
                    "ip": "192.168.1.10",
                    "params": {"state": "on"},
                },
            )
        )

        self.assertEqual(len(socket.sent), 1)
        sent = socket.sent[0]
        self.assertEqual(sent["type"], "command_result")
        self.assertEqual(sent["command_id"], "cmd-1")
        self.assertTrue(sent["ok"])
        self.assertEqual(sent["result"], {"power": "on"})
        handler.assert_called_once_with("power", "192.168.1.10", {"state": "on"})

        # Cached result is reused without calling the runtime again.
        socket2 = FakeAgentSocket()
        asyncio.run(
            self.agent._handle_command(
                socket2,
                {
                    "type": "command",
                    "command_id": "cmd-1",
                    "action": "power",
                    "ip": "192.168.1.10",
                    "params": {"state": "on"},
                },
            )
        )
        self.assertEqual(socket2.sent[0]["command_id"], "cmd-1")
        handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
