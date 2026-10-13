import subprocess
import unittest
from unittest.mock import patch

from yeelight_network_utils import get_lan_addresses


class LanAddressTests(unittest.TestCase):
    def test_prefers_distinct_non_loopback_windows_addresses(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="192.168.1.10\n127.0.0.1\n192.168.1.10\n",
            stderr="",
        )
        with (
            patch("yeelight_network_utils.os.name", "nt"),
            patch("yeelight_network_utils.subprocess.run", return_value=result),
        ):
            self.assertEqual(get_lan_addresses(), ["192.168.1.10"])

    def test_uses_udp_route_when_windows_lookup_fails(self) -> None:
        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def connect(self, _address):
                pass

            def getsockname(self):
                return ("192.168.1.20", 12345)

        with (
            patch("yeelight_network_utils.os.name", "nt"),
            patch(
                "yeelight_network_utils.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            patch("yeelight_network_utils.socket.socket", return_value=FakeSocket()),
        ):
            self.assertEqual(get_lan_addresses(), ["192.168.1.20"])


if __name__ == "__main__":
    unittest.main()
