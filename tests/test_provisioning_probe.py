import hashlib
import importlib.util
import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from tools import provisioning_probe


class ProvisioningProbeTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("cryptography"),
        "Install the diagnostics extra to test encrypted miIO requests",
    )
    def test_miio_info_requests_only_device_details_and_redacts_other_fields(self) -> None:
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        token = bytes.fromhex("00112233445566778899aabbccddeeff")
        device_id = 0x12345678
        handshake = (
            b"!1"
            + bytes.fromhex("0020")
            + bytes(4)
            + device_id.to_bytes(4, "big")
            + bytes.fromhex("00000010")
            + token
        )
        key = hashlib.md5(token).digest()
        iv = hashlib.md5(key + token).digest()
        payload = json.dumps(
            {
                "id": 1,
                "result": [{
                    "model": "yeelight.light.color1",
                    "fw_ver": "61",
                    "hw_ver": "1.0",
                    "token": token.hex(),
                    "mac": "00:11:22:33:44:55",
                }],
            },
            separators=(",", ":"),
        ).encode() + b"\x00"
        padder = padding.PKCS7(128).padder()
        padded_payload = padder.update(payload) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        encrypted = encryptor.update(padded_payload) + encryptor.finalize()
        header = struct.pack(">HHIII", 0x2131, 32 + len(encrypted), 0, device_id, 17)
        checksum = hashlib.md5(header + token + encrypted).digest()
        response = header + checksum + encrypted

        class FakeSocket:
            def __init__(self):
                self.sent = []
                self.responses = [handshake, response]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def settimeout(self, _timeout):
                pass

            def sendto(self, packet, address):
                self.sent.append((packet, address))

            def recvfrom(self, _size):
                return self.responses.pop(0), ("192.168.13.1", 54321)

        fake_socket = FakeSocket()
        with patch.object(provisioning_probe.socket, "socket", return_value=fake_socket):
            result = provisioning_probe.probe_miio_info("192.168.13.1")

        self.assertEqual(result["status"], "device_info_received")
        self.assertEqual(
            result["device_info"],
            {"model": "yeelight.light.color1", "fw_ver": "61", "hw_ver": "1.0"},
        )
        self.assertNotIn(token.hex(), str(result))
        self.assertNotIn("00:11:22:33:44:55", str(result))
        self.assertEqual(len(fake_socket.sent), 2)
        request_packet = fake_socket.sent[1][0]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded_request = decryptor.update(request_packet[32:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        request_bytes = unpadder.update(padded_request) + unpadder.finalize()
        request = json.loads(request_bytes.rstrip(b"\x00").decode())
        self.assertEqual(request["id"], 1)
        self.assertEqual(request["method"], "miIO.info")
        self.assertTrue(request_bytes.endswith(b"\x00"))
        self.assertFalse(request_bytes.endswith(b"\r\n"))
        self.assertNotIn("passwd", request.get("params", {}))

    def test_miio_probe_reports_token_availability_without_revealing_it(self) -> None:
        token = bytes.fromhex("00112233445566778899aabbccddeeff")
        response = (
            b"!1"
            + bytes.fromhex("0020")
            + bytes(4)
            + bytes.fromhex("12345678")
            + bytes(4)
            + token
        )

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def settimeout(self, _timeout):
                pass

            def sendto(self, packet, address):
                self.packet = packet
                self.address = address

            def recvfrom(self, _size):
                return response, ("192.168.1.45", 54321)

        fake_socket = FakeSocket()
        with patch.object(provisioning_probe.socket, "socket", return_value=fake_socket):
            result = provisioning_probe.probe_miio("192.168.1.45")

        self.assertEqual(result["status"], "miio_device_responded")
        self.assertEqual(result["device_id"], 0x12345678)
        self.assertTrue(result["token_available"])
        self.assertNotIn(token.hex(), str(result))
        self.assertEqual(fake_socket.address, ("192.168.1.45", 54321))
        self.assertEqual(fake_socket.packet[:4], bytes.fromhex("21310020"))

    def test_miio_probe_recognizes_hidden_token(self) -> None:
        response = b"!1" + bytes.fromhex("0020") + bytes(4) + bytes(8) + bytes(16)

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def settimeout(self, _timeout):
                pass

            def sendto(self, _packet, _address):
                pass

            def recvfrom(self, _size):
                return response, ("10.0.0.5", 54321)

        with patch.object(provisioning_probe.socket, "socket", return_value=FakeSocket()):
            result = provisioning_probe.probe_miio("10.0.0.5")

        self.assertEqual(result["status"], "miio_device_responded")
        self.assertFalse(result["token_available"])
        self.assertNotIn("token", result)

    def test_miio_probe_rejects_invalid_or_ipv6_targets(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "valid IPv4"):
            provisioning_probe.probe_miio("not-an-ip")
        with self.assertRaisesRegex(RuntimeError, "IPv4"):
            provisioning_probe.probe_miio("2001:db8::1")

    def test_windows_report_only_lists_yeelight_setup_networks(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "SSID 1 : Home WiFi\n"
                "    BSSID 1 : 00:11:22:33:44:55\n"
                "SSID 2 : yeelink-light-abc123\n"
                "SSID 3 : Guest Network\n"
                "SSID 4 : Yeelink-Light-def456\n"
            ),
            stderr="",
        )
        with (
            patch.object(provisioning_probe.platform, "system", return_value="Windows"),
            patch.object(provisioning_probe, "_run", return_value=result),
        ):
            report = provisioning_probe._yeelight_network_report()

        self.assertEqual(report["status"], "detected")
        self.assertEqual(
            report["yeelight_setup_networks"],
            ["Yeelink-Light-def456", "yeelink-light-abc123"],
        )
        self.assertNotIn("Home WiFi", str(report))
        self.assertNotIn("00:11:22:33:44:55", str(report))

    def test_no_matching_setup_network_is_reported_explicitly(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="SSID 1 : Home WiFi\n",
            stderr="",
        )
        with (
            patch.object(provisioning_probe.platform, "system", return_value="Windows"),
            patch.object(provisioning_probe, "_run", return_value=result),
        ):
            report = provisioning_probe._yeelight_network_report()

        self.assertEqual(report["status"], "not_detected")
        self.assertEqual(report["yeelight_setup_networks"], [])

    def test_windows_bluetooth_report_excludes_paired_devices(self) -> None:
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "Realtek Bluetooth 4.2 Adapter\n"
                "Microsoft Bluetooth LE Enumerator\n"
                "Redmi Note 12\n"
                "realme Buds T110 Avrcp Transport\n"
            ),
            stderr="",
        )
        with (
            patch.object(provisioning_probe.platform, "system", return_value="Windows"),
            patch.object(provisioning_probe, "_run", return_value=result),
        ):
            report = provisioning_probe._bluetooth_report()

        self.assertEqual(report["status"], "detected")
        self.assertEqual(report["present_adapters"], ["Realtek Bluetooth 4.2 Adapter"])
        self.assertNotIn("Redmi Note", str(report))
        self.assertNotIn("Buds", str(report))

    def test_report_discloses_protocol_limits_and_never_accepts_credentials(self) -> None:
        with (
            patch.object(provisioning_probe.platform, "system", return_value="Other"),
            patch.object(provisioning_probe.platform, "release", return_value="test"),
            patch.object(provisioning_probe.platform, "python_version", return_value="3.13"),
            patch.object(provisioning_probe.importlib.util, "find_spec", return_value=None),
        ):
            report = provisioning_probe.collect_report()

        self.assertIn("No Wi-Fi credentials are requested, sent, or stored.", report["limitations"])
        self.assertEqual(report["bluetooth"]["status"], "unsupported")
        self.assertEqual(report["yeelight_setup_wifi"]["status"], "unsupported")

    def test_ble_scan_reports_missing_optional_dependency_without_fallback(self) -> None:
        with patch.dict("sys.modules", {"bleak": None}):
            with self.assertRaisesRegex(RuntimeError, r"\.\[diagnostics\]"):
                import asyncio

                asyncio.run(provisioning_probe.scan_ble())


if __name__ == "__main__":
    unittest.main()
