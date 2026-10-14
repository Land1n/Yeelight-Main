import argparse
import unittest
from unittest.mock import MagicMock, patch

from tools import lan_control_probe


class LanControlProbeTests(unittest.TestCase):
    def test_reports_tcp_ssdp_and_get_prop_success(self) -> None:
        tcp_connection = MagicMock()
        tcp_connection.__enter__.return_value = tcp_connection
        bulb = MagicMock()
        bulb.get_properties.return_value = {"power": "on"}
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                return_value=tcp_connection,
            ) as create_connection,
            patch.object(
                lan_control_probe,
                "discover_bulbs",
                return_value=[{"ip": "192.168.1.45", "port": 55443}],
            ) as discover,
            patch.object(lan_control_probe, "Bulb", return_value=bulb),
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(
            result,
            {
                "ip": "192.168.1.45",
                "tcp_55443": "open",
                "ssdp_1982": "found",
                "get_prop": "ok",
            },
        )
        create_connection.assert_called_once_with(("192.168.1.45", 55443), timeout=2.0)
        discover.assert_called_once_with(timeout=2.0)
        bulb.get_properties.assert_called_once_with(["power"])

    def test_reports_tcp_ssdp_and_get_prop_failures_without_device_data(self) -> None:
        bulb = MagicMock()
        bulb.get_properties.return_value = {}
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                side_effect=TimeoutError,
            ),
            patch.object(lan_control_probe, "discover_bulbs", return_value=[]),
            patch.object(lan_control_probe, "Bulb", return_value=bulb),
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(result["tcp_55443"], "failed (TimeoutError)")
        self.assertEqual(result["ssdp_1982"], "not_found")
        self.assertEqual(result["get_prop"], "unexpected_response")
        self.assertNotIn("power", result)

    def test_reports_library_no_response_bug_as_failed_get_prop(self) -> None:
        bulb = MagicMock()
        bulb.get_properties.side_effect = UnboundLocalError
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
            ),
            patch.object(lan_control_probe, "discover_bulbs", return_value=[]),
            patch.object(lan_control_probe, "Bulb", return_value=bulb),
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(result["get_prop"], "failed (UnboundLocalError)")

    def test_rejects_non_private_or_invalid_targets(self) -> None:
        for ip in ("not-an-ip", "8.8.8.8", "2001:db8::1"):
            with self.subTest(ip=ip):
                with self.assertRaises(argparse.ArgumentTypeError):
                    lan_control_probe._target(ip)


if __name__ == "__main__":
    unittest.main()
