from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yeelight_logic import CommandError, CommandResult

from tests.support import FakeBulb, FakeRuntime, make_controller, manager_settings


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = manager_settings(tempfile.mkdtemp())
        self.runtime = FakeRuntime()

    def test_known_ips_union(self) -> None:
        controller, _ = make_controller(("192.168.1.10", "192.168.1.11"))
        runtime = manager_settings(tempfile.mkdtemp())
        from yeelight_manager.runtime import ManagerRuntime

        real = ManagerRuntime(self.settings, controller=controller)
        self.assertEqual(real.known_ips(), ["192.168.1.10", "192.168.1.11"])
        real.close()

    def test_add_lamp_updates_cache(self) -> None:
        self.runtime.add_lamp("192.168.1.10")
        self.assertEqual(self.runtime.known_ips(), ["192.168.1.10"])
        states = self.runtime.lamp_states()
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["ip"], "192.168.1.10")

    def test_remove_lamp_removes_from_cache(self) -> None:
        self.runtime.add_lamp("192.168.1.10")
        self.runtime.remove_lamp("192.168.1.10")
        self.assertEqual(self.runtime.known_ips(), [])
        self.assertEqual(self.runtime.lamp_states(), [])

    def test_action_updates_state_cache(self) -> None:
        def handler(action, ip, params):
            return CommandResult(True, "done", data={"power": "on"})

        self.runtime.action_handler = handler
        result = self.runtime.run_action("power", "192.168.1.10", {"state": "on"})
        self.assertTrue(result.ok)
        state = self.runtime.lamp_states()[0]
        self.assertEqual(state["ip"], "192.168.1.10")
        self.assertEqual(state["power"], "on")
        self.assertTrue(state["online"])

    def test_command_error_does_not_mark_offline(self) -> None:
        def handler(action, ip, params):
            return CommandResult(False, "bad params", error_code="command_error")

        self.runtime.action_handler = handler
        self.runtime.add_lamp("192.168.1.10")
        self.runtime.run_action("brightness", "192.168.1.10", {"value": 0})
        state = self.runtime.lamp_states()[0]
        self.assertEqual(state["online"], True)

    def test_device_error_marks_offline(self) -> None:
        def handler(action, ip, params):
            return CommandResult(False, "device error", error_code="device_error")

        self.runtime.action_handler = handler
        self.runtime.add_lamp("192.168.1.10")
        self.runtime.run_action("power", "192.168.1.10", {"state": "on"})
        state = self.runtime.lamp_states()[0]
        self.assertEqual(state["online"], False)

    def test_discover_uses_handler_and_emit(self) -> None:
        emitted = []
        self.runtime.add_listener(lambda reason: emitted.append(reason))
        self.runtime.discovery_bulbs = [{"ip": "192.168.1.20"}]
        result = self.runtime.discover()
        self.assertTrue(result.ok)
        self.assertEqual(emitted, ["discover"])
        self.assertTrue(any(lamp["ip"] == "192.168.1.20" for lamp in self.runtime.lamp_states()))

    def test_listeners_notify_on_change(self) -> None:
        emitted = []
        self.runtime.add_listener(lambda reason: emitted.append(reason))
        self.runtime.run_action("power", "192.168.1.10", {"state": "on"})
        self.assertEqual(emitted, ["state"])

    def test_provisioning_requires_confirmation(self) -> None:
        with self.assertRaises(CommandError):
            self.runtime.provision_wifi("192.168.13.1", "Home", "pass", confirm=False)
        with self.assertRaises(CommandError):
            self.runtime.provision_lan_control("192.168.1.10", confirm=False)

    def test_close_stops_monitor(self) -> None:
        self.runtime.start_monitor()
        self.assertTrue(self.runtime.monitor_started)
        self.runtime.close()
        self.assertTrue(self.runtime.closed)
        self.assertFalse(self.runtime.monitor_started)


class FakeRuntimeApplicabilityTests(unittest.TestCase):
    def test_fake_runtime_implements_runtime_methods(self) -> None:
        runtime = FakeRuntime()
        runtime.add_listener(lambda reason: None)
        runtime.run_action("status", "192.168.1.10", {})
        runtime.discover()
        runtime.add_lamp("192.168.1.10")
        runtime.remove_lamp("192.168.1.10")
        runtime.refresh_states()
        runtime.start_monitor()
        runtime.stop_monitor()
        runtime.close()


if __name__ == "__main__":
    unittest.main()
