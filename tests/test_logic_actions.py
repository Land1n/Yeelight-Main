from __future__ import annotations

import unittest
from unittest import mock

from yeelight_logic import REMOTE_ACTIONS, CommandError, execute_action, validate_action_params
from yeelight_logic.commands import (
    ConnectWifiCommand,
    EnableLanControlCommand,
    SetBrightnessCommand,
    TurnOnCommand,
)
from yeelight_logic.types import ProvisioningResult

from tests.support import make_controller


class ValidateActionParamsTests(unittest.TestCase):
    def test_remote_actions_are_closed_and_exclude_provisioning(self) -> None:
        self.assertEqual(
            REMOTE_ACTIONS,
            {
                "power",
                "brightness",
                "color",
                "color_temperature",
                "status",
                "discover",
                "add",
                "remove",
                "list",
            },
        )
        self.assertNotIn("wifi", REMOTE_ACTIONS)
        self.assertNotIn("lan_control", REMOTE_ACTIONS)
        self.assertNotIn("command", REMOTE_ACTIONS)

    def test_power_states(self) -> None:
        for state in ("on", "off", "toggle"):
            self.assertEqual(
                validate_action_params("power", {"state": state}),
                {"state": state},
            )
        with self.assertRaises(CommandError):
            validate_action_params("power", {"state": "blink"})
        with self.assertRaises(CommandError):
            validate_action_params("power", {})

    def test_numeric_ranges_and_booleans(self) -> None:
        self.assertEqual(
            validate_action_params("brightness", {"value": "60"}), {"value": 60}
        )
        self.assertEqual(
            validate_action_params("color_temperature", {"value": 4000}),
            {"value": 4000},
        )
        for action, value in (
            ("brightness", 0),
            ("brightness", 101),
            ("color_temperature", 1699),
            ("color_temperature", 6501),
            ("brightness", True),
            ("brightness", 1.5),
        ):
            with self.subTest(action=action, value=value):
                with self.assertRaises(CommandError):
                    validate_action_params(action, {"value": value})

    def test_color_accepts_rgb_and_hex(self) -> None:
        self.assertEqual(
            validate_action_params("color", {"rgb": [51, 170, 255]}),
            {"rgb": [51, 170, 255]},
        )
        self.assertEqual(
            validate_action_params("color", {"hex": "#33AAFF"}),
            {"rgb": [51, 170, 255]},
        )
        self.assertEqual(
            validate_action_params("color", {"hex": "33aaff"}),
            {"rgb": [51, 170, 255]},
        )
        for payload in (
            {"rgb": [1, 2]},
            {"rgb": [1, 2, 256]},
            {"rgb": [True, 2, 3]},
            {"hex": "red"},
            {},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(CommandError):
                    validate_action_params("color", payload)

    def test_address_actions_validate_ipv4(self) -> None:
        self.assertEqual(
            validate_action_params("add", {"ip": "192.168.1.10"}),
            {"ip": "192.168.1.10"},
        )
        self.assertEqual(
            validate_action_params("remove", {"address": "192.168.1.11"}),
            {"ip": "192.168.1.11"},
        )
        for payload in (
            {"ip": "not-an-ip"},
            {"ip": "::1"},
            {},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(CommandError):
                    validate_action_params("add", payload)

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            validate_action_params("wifi", {"ip": "192.168.1.10"})
        with self.assertRaises(CommandError):
            validate_action_params("on 192.168.1.10", {})


class ExecuteActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller, self.bulbs = make_controller()
        self.bulb = self.bulbs["192.168.1.10"]

    def test_power_brightness_color_and_temperature(self) -> None:
        result = execute_action(
            self.controller, "power", "192.168.1.10", {"state": "on"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"power": "on"})
        self.assertEqual(self.bulb.properties["power"], "on")

        self.assertTrue(
            execute_action(
                self.controller, "brightness", "192.168.1.10", {"value": 65}
            ).ok
        )
        self.assertEqual(self.bulb.properties["bright"], "65")

        result = execute_action(
            self.controller, "color", "192.168.1.10", {"hex": "#33AAFF"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"rgb": [51, 170, 255]})
        self.assertEqual(self.bulb.properties["rgb"], str((51 << 16) | (170 << 8) | 255))

        result = execute_action(
            self.controller,
            "color_temperature",
            "192.168.1.10",
            {"value": 4100},
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.bulb.properties["ct"], "4100")

    def test_toggle_uses_fake_lamp(self) -> None:
        result = execute_action(
            self.controller, "power", "192.168.1.10", {"state": "toggle"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(self.bulb.properties["power"], "on")
        self.assertEqual(result.data, {"power": "on"})

    def test_status_returns_properties_and_ip(self) -> None:
        result = execute_action(self.controller, "status", "192.168.1.10", {})
        self.assertTrue(result.ok)
        self.assertEqual(result.data["ip"], "192.168.1.10")
        self.assertIn("power", result.data["properties"])

    def test_unknown_lamp_is_rejected_without_touching_device(self) -> None:
        result = execute_action(
            self.controller, "power", "192.168.1.99", {"state": "on"}
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "command_error")
        self.assertEqual(self.bulb.calls, [])

    def test_invalid_parameters_return_command_error(self) -> None:
        result = execute_action(
            self.controller, "brightness", "192.168.1.10", {"value": 0}
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "command_error")
        self.assertEqual(self.bulb.calls, [])

    def test_add_list_remove_and_discover(self) -> None:
        result = execute_action(self.controller, "add", params={"ip": "192.168.1.11"})
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"ip": "192.168.1.11"})

        result = execute_action(self.controller, "list")
        self.assertTrue(result.ok)
        self.assertEqual(
            [item["ip"] for item in result.data["bulbs"]],
            ["192.168.1.10", "192.168.1.11"],
        )

        result = execute_action(
            self.controller, "remove", params={"ip": "192.168.1.11"}
        )
        self.assertTrue(result.ok)
        self.assertFalse(self.controller.is_known("192.168.1.11"))

    def test_discovery_uses_injected_discovery(self) -> None:
        controller, _ = make_controller(
            (),
            discovery_result=[
                {"ip": "192.168.1.20", "capabilities": {"model": "yeelink.light.color1"}}
            ],
        )
        result = execute_action(controller, "discover")
        self.assertTrue(result.ok)
        self.assertEqual(len(result.data["bulbs"]), 1)
        self.assertTrue(controller.is_known("192.168.1.20"))
        controller.close()

    def test_transport_error_is_retried_once_for_idempotent_action(self) -> None:
        self.bulb.failures["turn_on"] = OSError("socket closed by peer")
        result = execute_action(
            self.controller, "power", "192.168.1.10", {"state": "on"}
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            [name for name, _ in self.bulb.calls].count("turn_on"), 2
        )

    def test_toggle_is_not_retried(self) -> None:
        self.bulb.failures["toggle"] = OSError("socket closed by peer")
        result = execute_action(
            self.controller, "power", "192.168.1.10", {"state": "toggle"}
        )
        self.assertFalse(result.ok)
        self.assertEqual(
            [name for name, _ in self.bulb.calls].count("toggle"), 1
        )


class CommandClassTests(unittest.TestCase):
    def test_brightness_command_validates_before_calling_lamp(self) -> None:
        controller, bulbs = make_controller()
        bulb = bulbs["192.168.1.10"]
        result = SetBrightnessCommand(bulb, 0).execute()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "command_error")
        self.assertEqual(bulb.calls, [])

    def test_turn_on_command_returns_structured_result(self) -> None:
        controller, bulbs = make_controller()
        result = TurnOnCommand(bulbs["192.168.1.10"]).execute()
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"power": "on"})
        controller.close()

    def test_provisioning_commands_require_confirmation(self) -> None:
        wifi = ConnectWifiCommand(
            "192.168.13.1", "Home", "password123", confirmed=False
        )
        result = wifi.execute()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "confirmation_required")

        lan = EnableLanControlCommand("192.168.1.10", confirmed=False)
        result = lan.execute()
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "confirmation_required")

    def test_wifi_command_clears_password_and_omits_it_from_result(self) -> None:
        provisioning_result = ProvisioningResult(
            wifi_status="responded_unverified",
            wifi_message="The lamp answered the Wi-Fi setup request.",
            lan_control_status="not_requested",
        )
        command = ConnectWifiCommand(
            "192.168.13.1", "Home", "password123", confirmed=True
        )
        with mock.patch(
            "yeelight_logic.commands.provisioning.connect_to_wifi",
            return_value=provisioning_result,
        ) as connect:
            result = command.execute()
        connect.assert_called_once()
        arguments = connect.call_args
        self.assertEqual(arguments.args[:3], ("192.168.13.1", "Home", "password123"))
        self.assertTrue(result.ok)
        self.assertNotIn("password123", str(result.to_dict()))
        self.assertEqual(command._password, "")

    def test_lan_control_command_returns_result(self) -> None:
        provisioning_result = ProvisioningResult(
            wifi_status="not_sent",
            wifi_message="Wi-Fi setup was not performed.",
            lan_control_status="responded_unverified",
            lan_control_message="The lamp answered the LAN Control request.",
        )
        command = EnableLanControlCommand("192.168.1.10", confirmed=True)
        with mock.patch(
            "yeelight_logic.commands.provisioning.enable_lan_control",
            return_value=provisioning_result,
        ):
            result = command.execute()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["lan_control_status"], "responded_unverified")


if __name__ == "__main__":
    unittest.main()
