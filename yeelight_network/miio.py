from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_HELLO = bytes.fromhex(
    "21310020ffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)
_SUPPORTED_MODEL = "yeelink.light.color1"


class MiIOError(RuntimeError):
    pass


@dataclass(frozen=True)
class _MiIOResponse:
    payload: dict[str, Any]
    device_id: int
    timestamp: int


def is_valid_wifi_password(password: str) -> bool:
    if len(password) > 64 or "\x00" in password:
        return False
    password_bytes = password.encode("utf-8")
    return 8 <= len(password_bytes) <= 63 or (
        len(password_bytes) == 64
        and all(c in "0123456789abcdefABCDEF" for c in password)
    )


def _target(ip: str) -> str:
    try:
        target = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise MiIOError("Enter a valid IPv4 address for the device.") from exc
    if target.version != 4 or not target.is_private:
        raise MiIOError("Only a private IPv4 device address is allowed.")
    return str(target)


def _decode_response(
    packet: bytes,
    source: tuple[str, int],
    target: str,
    token: bytes,
    expected_device_id: int,
    expected_request_id: int,
) -> _MiIOResponse:
    if (
        source[0] != target
        or len(packet) < 48
        or packet[:2] != b"\x21\x31"
        or int.from_bytes(packet[2:4], "big") != len(packet)
    ):
        raise MiIOError("Device response failed miIO packet validation.")

    _, _, _, device_id, timestamp = struct.unpack(">HHIII", packet[:16])
    if device_id != expected_device_id:
        raise MiIOError("Device response came from an unexpected miIO device.")
    if not hmac.compare_digest(
        hashlib.md5(packet[:16] + token + packet[32:]).digest(), packet[16:32]
    ):
        raise MiIOError("Device response failed miIO packet validation.")

    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    try:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(packet[32:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        decoded = json.loads(plaintext.rstrip(b"\x00").decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MiIOError("Device returned an unreadable miIO response.") from exc
    if (
        not isinstance(decoded, dict)
        or not isinstance(decoded.get("id"), int)
        or isinstance(decoded.get("id"), bool)
        or decoded["id"] != expected_request_id
    ):
        raise MiIOError("Device returned an unexpected miIO response.")
    return _MiIOResponse(decoded, device_id, timestamp)


def _send_request(
    client: socket.socket,
    target: str,
    device_id: int,
    stamp: int,
    token: bytes,
    method: str,
    params: list[Any] | dict[str, Any],
    request_id: int,
    timeout: float,
) -> _MiIOResponse | None:
    payload = json.dumps(
        {"id": request_id, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8") + b"\x00"
    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    header = struct.pack(
        ">HHIII", 0x2131, 32 + len(encrypted), 0, device_id, stamp & 0xFFFFFFFF
    )
    packet = header + hashlib.md5(header + token + encrypted).digest() + encrypted
    client.sendto(packet, (target, 54321))
    try:
        response, source = client.recvfrom(2048)
    except socket.timeout:
        return None
    return _decode_response(
        response, source, target, token, device_id, request_id
    )


def _open_session(
    client: socket.socket, target: str, timeout: float
) -> tuple[int, int, bytes]:
    client.settimeout(timeout)
    client.sendto(_HELLO, (target, 54321))
    try:
        handshake, source = client.recvfrom(1024)
    except socket.timeout as exc:
        raise MiIOError("The device did not answer the miIO handshake.") from exc
    if source[0] != target or len(handshake) != 32 or handshake[:2] != b"\x21\x31":
        raise MiIOError("The device did not return a valid miIO handshake.")
    if int.from_bytes(handshake[2:4], "big") != 32:
        raise MiIOError("The device did not return a valid miIO handshake.")
    token = handshake[16:32]
    if token in (bytes(16), b"\xff" * 16):
        raise MiIOError("The device did not provide a usable miIO token.")
    return (
        int.from_bytes(handshake[8:12], "big"),
        (int.from_bytes(handshake[12:16], "big") + 1) & 0xFFFFFFFF,
        token,
    )


def _device_info(
    client: socket.socket,
    target: str,
    device_id: int,
    stamp: int,
    token: bytes,
    request_id: int,
    timeout: float,
) -> tuple[dict[str, Any], _MiIOResponse]:
    response = _send_request(
        client,
        target,
        device_id,
        stamp,
        token,
        "miIO.info",
        [],
        request_id,
        timeout,
    )
    if response is None:
        raise MiIOError("The device did not answer the miIO info request.")
    if "error" in response.payload:
        if not isinstance(response.payload["error"], dict):
            raise MiIOError("Device returned a malformed miIO error response.")
        raise MiIOError("The device rejected the miIO info request.")
    if "result" not in response.payload:
        raise MiIOError("Device returned an unexpected miIO info response.")
    result = response.payload["result"]
    details = result[0] if isinstance(result, list) and result else result
    if not isinstance(details, dict):
        raise MiIOError("The device did not return standard miIO info fields.")
    return details, response


def _next_request_id(request_id: int) -> int:
    return 1 if request_id >= 9998 else request_id + 1


def _next_timestamp(timestamp: int) -> int:
    return (timestamp + 1) & 0xFFFFFFFF


def request_device_info(ip: str, timeout: float = 3.0) -> dict[str, Any]:
    target = _target(ip)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            device_id, stamp, token = _open_session(client, target, timeout)
            info, _ = _device_info(
                client, target, device_id, stamp, token, 1, timeout
            )
    except OSError as exc:
        raise MiIOError("Could not communicate with the miIO device.") from exc
    return {
        field: info[field][:100]
        for field in ("model", "fw_ver", "hw_ver")
        if isinstance(info.get(field), str)
    }


def configure_wifi(
    ip: str,
    ssid: str,
    password: str,
    timeout: float = 3.0,
) -> str:
    target = _target(ip)
    if not ssid or len(ssid.encode("utf-8")) > 32 or "\x00" in ssid:
        raise MiIOError("SSID must contain 1 to 32 UTF-8 bytes.")
    if not is_valid_wifi_password(password):
        raise MiIOError("Wi-Fi password must be 8–63 bytes or a 64-digit hexadecimal key.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            device_id, stamp, token = _open_session(client, target, timeout)
            info, info_response = _device_info(
                client, target, device_id, stamp, token, 1, timeout
            )
            if info.get("model") != _SUPPORTED_MODEL:
                raise MiIOError(
                    "Wi-Fi setup is enabled only for detected model yeelink.light.color1."
                )
            response = _send_request(
                client,
                target,
                device_id,
                _next_timestamp(info_response.timestamp),
                token,
                "miIO.config_router",
                {"ssid": ssid, "passwd": password, "uid": 0},
                _next_request_id(info_response.payload["id"]),
                timeout,
            )
    except OSError as exc:
        raise MiIOError("Could not send the Wi-Fi setup request to the device.") from exc
    if response is None:
        return "sent_unconfirmed"
    if "error" in response.payload:
        if not isinstance(response.payload["error"], dict):
            raise MiIOError("Device returned a malformed miIO error response.")
        return "rejected"
    if "result" not in response.payload:
        raise MiIOError("Device returned an unexpected miIO config response.")
    return "responded_unverified"


def enable_lan_control(ip: str, timeout: float = 3.0) -> str:
    target = _target(ip)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            device_id, stamp, token = _open_session(client, target, timeout)
            info, info_response = _device_info(
                client, target, device_id, stamp, token, 1, timeout
            )
            if info.get("model") != _SUPPORTED_MODEL:
                raise MiIOError(
                    "LAN Control setup is enabled only for detected model "
                    "yeelink.light.color1."
                )
            response = _send_request(
                client,
                target,
                device_id,
                _next_timestamp(info_response.timestamp),
                token,
                "set_ps",
                ["cfg_lan_ctrl", "1"],
                _next_request_id(info_response.payload["id"]),
                timeout,
            )
    except OSError as exc:
        raise MiIOError("Could not send the LAN Control request to the device.") from exc

    if response is None:
        return "sent_unconfirmed"
    if "error" in response.payload:
        if not isinstance(response.payload["error"], dict):
            raise MiIOError("Device returned a malformed miIO error response.")
        return "rejected"
    result = response.payload.get("result")
    if result is None or result is False or result == []:
        raise MiIOError("Device returned an unexpected LAN Control response.")
    return "responded_unverified"
