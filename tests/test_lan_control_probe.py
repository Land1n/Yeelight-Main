import argparse
import socket
import unittest
from unittest.mock import patch

from tools import lan_control_probe


class LanControlProbeTests(unittest.TestCase):
    class FakeConnection:
        def __init__(self, response: bytes = b"", error: Exception | None = None):
            self.response = response
            self.error = error
            self.sent = b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _timeout):
            pass

        def getsockname(self):
            return ("192.168.1.20", 12345)

        def sendall(self, data):
            self.sent += data

        def recv(self, _size):
            if self.error:
                raise self.error
            return self.response

    def test_reports_tcp_ssdp_and_get_prop_success(self) -> None:
        tcp_connection = self.FakeConnection()
        prop_connection = self.FakeConnection(
            b'{"id":1,"result":["on"]}\r\n'
        )
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                side_effect=[tcp_connection, prop_connection],
            ) as create_connection,
            patch.object(
                lan_control_probe,
                "discover_bulbs",
                return_value=[{"ip": "192.168.1.45", "port": 55443}],
            ) as discover,
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(
            result,
            {
                "ip": "192.168.1.45",
                "tcp_55443": "open",
                "tcp_source_address": "192.168.1.20",
                "ssdp_1982": "found",
                "get_prop": "ok",
                "get_prop_source_address": "192.168.1.20",
                "get_prop_details": {"power": "on"},
            },
        )
        self.assertEqual(create_connection.call_count, 2)
        discover.assert_called_once_with(timeout=2.0)
        self.assertEqual(
            prop_connection.sent,
            b'{"id":1,"method":"get_prop","params":["power"]}\r\n',
        )

    def test_reports_device_error_without_hiding_code_or_message(self) -> None:
        tcp_connection = self.FakeConnection()
        prop_connection = self.FakeConnection(
            b'{"id":1,"error":{"code":-5000,"message":"denied"}}\r\n'
        )
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                side_effect=[tcp_connection, prop_connection],
            ),
            patch.object(lan_control_probe, "discover_bulbs", return_value=[]),
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(result["get_prop"], "device_error")
        self.assertEqual(
            result["get_prop_details"],
            {"code": -5000, "message": "denied"},
        )

    def test_reports_tcp_ssdp_and_get_prop_failures_without_device_data(self) -> None:
        prop_connection = self.FakeConnection(error=socket.timeout())
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                side_effect=[TimeoutError(), prop_connection],
            ),
            patch.object(lan_control_probe, "discover_bulbs", return_value=[]),
        ):
            result = lan_control_probe.probe_lan_control("192.168.1.45")

        self.assertEqual(result["tcp_55443"], "failed (TimeoutError)")
        self.assertEqual(result["ssdp_1982"], "not_found")
        self.assertEqual(result["get_prop"], "timeout")
        self.assertNotIn("power", result)

    def test_reports_empty_and_invalid_get_prop_responses(self) -> None:
        for response, expected in (
            (b"", "empty_response"),
            (b"{not-json}\r\n", "invalid_json"),
            (b'{"id":2,"result":["on"]}\r\n', "unexpected_response"),
        ):
            with self.subTest(expected=expected):
                tcp_connection = self.FakeConnection()
                prop_connection = self.FakeConnection(response)
                with (
                    patch.object(
                        lan_control_probe.socket,
                        "create_connection",
                        side_effect=[tcp_connection, prop_connection],
                    ),
                    patch.object(lan_control_probe, "discover_bulbs", return_value=[]),
                ):
                    result = lan_control_probe.probe_lan_control("192.168.1.45")
                self.assertEqual(result["get_prop"], expected)

    def test_selects_requested_interface_for_ssdp(self) -> None:
        with (
            patch.object(
                lan_control_probe.socket,
                "create_connection",
                side_effect=[
                    self.FakeConnection(),
                    self.FakeConnection(b'{"id":1,"result":["on"]}\r\n'),
                ],
            ),
            patch.object(
                lan_control_probe,
                "discover_bulbs",
                return_value=[],
            ) as discover,
        ):
            result = lan_control_probe.probe_lan_control(
                "192.168.1.45",
                interface="hotspot-adapter",
            )

        self.assertEqual(result["get_prop"], "ok")
        discover.assert_called_once_with(
            timeout=2.0,
            interface="hotspot-adapter",
        )

    def test_rejects_non_private_or_invalid_targets(self) -> None:
        for ip in ("not-an-ip", "8.8.8.8", "2001:db8::1"):
            with self.subTest(ip=ip):
                with self.assertRaises(argparse.ArgumentTypeError):
                    lan_control_probe._target(ip)


if __name__ == "__main__":
    unittest.main()
