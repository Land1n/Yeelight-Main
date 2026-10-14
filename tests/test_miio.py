import hashlib
import json
import socket
import struct
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from yeelight_network import miio


TOKEN = bytes.fromhex("00112233445566778899aabbccddeeff")
DEVICE_ID = 0x12345678
TARGET = "192.168.13.1"


def encrypted_response(
    payload: dict,
    stamp: int = 17,
    device_id: int = DEVICE_ID,
) -> bytes:
    key = hashlib.md5(TOKEN).digest()
    iv = hashlib.md5(key + TOKEN).digest()
    raw = json.dumps(payload, separators=(",", ":")).encode() + b"\x00"
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    header = struct.pack(">HHIII", 0x2131, 32 + len(encrypted), 0, device_id, stamp)
    checksum = hashlib.md5(header + TOKEN + encrypted).digest()
    return header + checksum + encrypted


class FakeSocket:
    def __init__(
        self,
        info: dict,
        *,
        response_timestamps: tuple[int, ...] = (17, 18),
        response_payloads: dict[int, dict] | None = None,
        response_sources: dict[int, tuple[str, int]] | None = None,
        response_device_ids: dict[int, int] | None = None,
        timeouts: set[int] | None = None,
        corrupt_responses: set[int] | None = None,
        handshake_token: bytes = TOKEN,
    ):
        self.info = info
        self.response_timestamps = response_timestamps
        self.response_payloads = response_payloads or {}
        self.response_sources = response_sources or {}
        self.response_device_ids = response_device_ids or {}
        self.timeouts = timeouts or set()
        self.corrupt_responses = corrupt_responses or set()
        self.handshake_token = handshake_token
        self.sent: list[bytes] = []
        self.received = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def settimeout(self, _timeout):
        pass

    def sendto(self, packet, _address):
        self.sent.append(packet)

    def recvfrom(self, _size):
        self.received += 1
        if self.received == 1:
            handshake = (
                b"!1"
                + bytes.fromhex("0020")
                + bytes(4)
                + DEVICE_ID.to_bytes(4, "big")
                + bytes.fromhex("00000010")
                + self.handshake_token
            )
            return handshake, (TARGET, 54321)
        response_index = self.received - 2
        if response_index in self.timeouts:
            raise socket.timeout
        request = decrypt_request(self.sent[-1])
        payload = self.response_payloads.get(
            response_index,
            {
                "id": request["id"],
                "result": [self.info] if request["method"] == "miIO.info" else [0],
            },
        )
        device_id = self.response_device_ids.get(response_index, DEVICE_ID)
        packet = encrypted_response(
            payload,
            stamp=self.response_timestamps[response_index],
            device_id=device_id,
        )
        if response_index in self.corrupt_responses:
            packet = packet[:-1] + bytes([packet[-1] ^ 1])
        source = self.response_sources.get(response_index, (TARGET, 54321))
        return packet, source


def decrypt_request(packet: bytes) -> dict:
    key = hashlib.md5(TOKEN).digest()
    iv = hashlib.md5(key + TOKEN).digest()
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(packet[32:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    raw = unpadder.update(padded) + unpadder.finalize()
    return json.loads(raw.rstrip(b"\x00"))


class MiIOTests(unittest.TestCase):
    def test_wifi_setup_is_sent_only_after_exact_model_check(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1", "fw_ver": "1.4.2_0061"},
            response_timestamps=(0x2A, 0x2B),
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            status = miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(status, "responded_unverified")
        self.assertEqual(len(fake.sent), 3)
        info_request = decrypt_request(fake.sent[1])
        self.assertEqual(info_request["method"], "miIO.info")
        request = decrypt_request(fake.sent[2])
        self.assertEqual([info_request["id"], request["id"]], [1, 2])
        self.assertEqual(
            [struct.unpack(">HHIII", packet[:16])[4] for packet in fake.sent[1:]],
            [0x11, 0x2B],
        )
        self.assertEqual(request["method"], "miIO.config_router")
        self.assertEqual(
            request["params"],
            {"ssid": "POCO F4", "passwd": "test-pass-123", "uid": 0},
        )

    def test_wifi_setup_refuses_a_different_model_before_sending_credentials(self) -> None:
        fake = FakeSocket({"model": "yeelink.light.other"})
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "only for detected model"):
                miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(len(fake.sent), 2)
        self.assertNotIn(b"test-pass-123", b"".join(fake.sent))

    def test_wifi_setup_validates_target_and_credentials(self) -> None:
        invalid_inputs = (
            ("192.168.13.1", "", "12345678"),
            ("192.168.13.1", "A" * 33, "12345678"),
            ("192.168.13.1", "network", "short"),
            ("8.8.8.8", "network", "test-pass-123"),
        )
        for ip, ssid, password in invalid_inputs:
            with self.subTest(ip=ip, ssid=ssid):
                with self.assertRaises(miio.MiIOError):
                    miio.configure_wifi(ip, ssid, password)

    def test_enables_lan_control_with_python_miio_command(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1", "fw_ver": "1.4.2_0061"},
            response_timestamps=(0x2A, 0x2B),
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            status = miio.enable_lan_control(TARGET)

        self.assertEqual(status, "responded_unverified")
        self.assertEqual(len(fake.sent), 3)
        info_request = decrypt_request(fake.sent[1])
        request = decrypt_request(fake.sent[2])
        self.assertEqual(info_request, {"id": 1, "method": "miIO.info", "params": []})
        self.assertEqual(
            request,
            {
                "id": 2,
                "method": "set_ps",
                "params": ["cfg_lan_ctrl", "1"],
            },
        )
        self.assertEqual(
            [struct.unpack(">HHIII", packet[:16])[4] for packet in fake.sent[1:]],
            [0x11, 0x2B],
        )

    def test_lan_control_refuses_unsupported_model(self) -> None:
        fake = FakeSocket({"model": "yeelink.light.other"})
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "only for detected model"):
                miio.enable_lan_control(TARGET)
        self.assertEqual(len(fake.sent), 2)

    def test_lan_control_fails_when_handshake_has_no_token(self) -> None:
        fake = FakeSocket({"model": "yeelink.light.color1"}, handshake_token=bytes(16))
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "usable miIO token"):
                miio.enable_lan_control(TARGET)
        self.assertEqual(len(fake.sent), 1)

    def test_lan_control_reports_device_rejection(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={1: {"id": 2, "error": {"code": -1}}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            self.assertEqual(miio.enable_lan_control(TARGET), "rejected")

    def test_lan_control_timeout_is_unconfirmed(self) -> None:
        fake = FakeSocket({"model": "yeelink.light.color1"}, timeouts={1})
        with patch.object(miio.socket, "socket", return_value=fake):
            self.assertEqual(miio.enable_lan_control(TARGET), "sent_unconfirmed")

    def test_lan_control_requires_a_well_formed_success_response(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={1: {"id": 2, "result": []}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "unexpected LAN Control"):
                miio.enable_lan_control(TARGET)

    def test_mismatched_response_id_is_rejected_before_configuring_wifi(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={0: {"id": 99, "result": [{"model": "yeelink.light.color1"}]}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "unexpected miIO response"):
                miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(len(fake.sent), 2)

    def test_unrelated_or_invalid_config_response_is_never_success(self) -> None:
        invalid_responses = (
            (
                {"id": 99, "result": [0]},
                {},
                {},
                set(),
            ),
            (
                {"id": 2, "result": [0]},
                {1: ("192.168.13.2", 54321)},
                {},
                set(),
            ),
            (
                {"id": 2, "result": [0]},
                {},
                {1: DEVICE_ID + 1},
                set(),
            ),
            (
                {"id": 2, "result": [0]},
                {},
                {},
                {1},
            ),
            (
                {"id": 2},
                {},
                {},
                set(),
            ),
        )
        for payload, sources, device_ids, corrupt in invalid_responses:
            with self.subTest(payload=payload, sources=sources, corrupt=corrupt):
                fake = FakeSocket(
                    {"model": "yeelink.light.color1"},
                    response_payloads={1: payload},
                    response_sources=sources,
                    response_device_ids=device_ids,
                    corrupt_responses=corrupt,
                )
                with patch.object(miio.socket, "socket", return_value=fake):
                    with self.assertRaises(miio.MiIOError):
                        miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

    def test_device_error_response_is_reported_as_rejected(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={1: {"id": 2, "error": {"code": -1}}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            status = miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(status, "rejected")

    def test_info_error_stops_before_sending_wifi_credentials(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={0: {"id": 1, "error": {"code": -1}}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "rejected the miIO info"):
                miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(len(fake.sent), 2)

    def test_malformed_device_error_is_not_reported_as_rejected_or_success(self) -> None:
        fake = FakeSocket(
            {"model": "yeelink.light.color1"},
            response_payloads={1: {"id": 2, "error": "invalid"}},
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            with self.assertRaisesRegex(miio.MiIOError, "malformed miIO error"):
                miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

    def test_timeouts_are_distinguished_from_invalid_responses(self) -> None:
        no_info = FakeSocket({"model": "yeelink.light.color1"}, timeouts={0})
        with patch.object(miio.socket, "socket", return_value=no_info):
            with self.assertRaisesRegex(miio.MiIOError, "did not answer"):
                miio.request_device_info(TARGET)

        no_config_reply = FakeSocket(
            {"model": "yeelink.light.color1"}, timeouts={1}
        )
        with patch.object(miio.socket, "socket", return_value=no_config_reply):
            status = miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")
        self.assertEqual(status, "sent_unconfirmed")

    def test_sequence_id_and_timestamp_wrap_at_protocol_limits(self) -> None:
        self.assertEqual(miio._next_request_id(9998), 1)
        self.assertEqual(miio._next_timestamp(0xFFFFFFFF), 0)


if __name__ == "__main__":
    unittest.main()
