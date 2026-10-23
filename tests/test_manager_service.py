from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yeelight_manager.agent import ManagerAgent
from yeelight_manager.pairing import PairingOutcome
from yeelight_manager.runtime import ManagerRuntime
from yeelight_manager.service import ManagerService

from tests.support import FakeRuntime, manager_settings


class FakeAgent:
    def __init__(self) -> None:
        self.reconnects = 0
        self.stopped = False
        self.status_value = {"state": "unpaired", "connected": False}

    def status(self):
        return dict(self.status_value)

    def request_reconnect(self):
        self.reconnects += 1

    def notify_state_changed(self):
        pass

    def stop(self):
        self.stopped = True


class ManagerServicePairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = manager_settings(Path(tempfile.mkdtemp()))

    def test_pair_stores_token_and_wakes_agent(self) -> None:
        runtime = FakeRuntime()
        agent = FakeAgent()
        service = ManagerService(self.settings, runtime=runtime, agent=agent)
        outcome = PairingOutcome(
            token="ylm_test_token",
            manager_id="mgr_test",
            manager_name="Home",
            heartbeat_interval_seconds=20.0,
        )
        with mock.patch.object(service, "_pair_func", return_value=outcome):
            service.pair("ABCD1234", name="Home")
        self.assertTrue(service.paired)
        self.assertEqual(agent.reconnects, 1)

    def test_unpair_forgets_token(self) -> None:
        service = ManagerService(self.settings, runtime=FakeRuntime(), agent=FakeAgent())
        service._token = "ylm_test_token"
        with mock.patch("yeelight_manager.service.remove_token", return_value=True):
            existed = service.unpair()
        self.assertTrue(existed)
        self.assertFalse(service.paired)
        self.assertEqual(service.agent.reconnects, 1)


class ManagerServiceSnapshotTests(unittest.TestCase):
    def test_snapshot_includes_runtime_and_agent(self) -> None:
        runtime = FakeRuntime()
        runtime.add_lamp("192.168.1.10")
        agent = FakeAgent()
        service = ManagerService(
            manager_settings(Path(tempfile.mkdtemp())),
            runtime=runtime,
            agent=agent,
        )
        snapshot = service.snapshot()
        self.assertEqual(snapshot["lamp_count"], 1)
        self.assertEqual(snapshot["lamps"][0]["ip"], "192.168.1.10")
        self.assertEqual(snapshot["agent"]["state"], "unpaired")
        self.assertEqual(snapshot["manager_name"], "Test manager")


class ManagerServiceLifecycleTests(unittest.TestCase):
    def test_start_and_stop(self) -> None:
        runtime = FakeRuntime()
        agent = FakeAgent()
        service = ManagerService(
            manager_settings(Path(tempfile.mkdtemp())), runtime=runtime, agent=agent
        )
        service.start()
        self.assertTrue(runtime.monitor_started)
        self.assertIsNotNone(service._agent_thread)
        service.stop()
        self.assertFalse(runtime.monitor_started)
        self.assertTrue(agent.stopped)
        runtime.close()


if __name__ == "__main__":
    unittest.main()
