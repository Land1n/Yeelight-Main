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


def encrypted_response(payload: dict, stamp: int = 17) -> bytes:
    key = hashlib.md5(TOKEN).digest()
    iv = hashlib.md5(key + TOKEN).digest()
    raw = json.dumps(payload, separators=(",", ":")).encode() + b"\x00"
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    header = struct.pack(">HHIII", 0x2131, 32 + len(encrypted), 0, DEVICE_ID, stamp)
    checksum = hashlib.md5(header + TOKEN + encrypted).digest()
    return header + checksum + encrypted


class FakeSocket:
    def __init__(self, info: dict):
        self.info_response = encrypted_response({"result": [info]})
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
                + TOKEN
            )
            return handshake, (TARGET, 54321)
        if self.received == 2:
            return self.info_response, (TARGET, 54321)
        raise socket.timeout


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
            {"model": "yeelink.light.color1", "fw_ver": "1.4.2_0061"}
        )
        with patch.object(miio.socket, "socket", return_value=fake):
            status = miio.configure_wifi(TARGET, "POCO F4", "test-pass-123")

        self.assertEqual(status, "sent_unconfirmed")
        self.assertEqual(len(fake.sent), 3)
        self.assertEqual(decrypt_request(fake.sent[1])["method"], "miIO.info")
        request = decrypt_request(fake.sent[2])
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


if __name__ == "__main__":
    unittest.main()
