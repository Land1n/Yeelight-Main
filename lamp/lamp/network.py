"""Поиск ламп и настройка Wi-Fi / LAN Control через python-miio. Без retry."""

import ipaddress

from miio import DeviceException
from miio.miioprotocol import MiIOProtocol
from yeelight import discover_bulbs

from lamp.device import LampError

TIMEOUT = 5


def discover(timeout=2):
    return discover_bulbs(timeout=timeout)


def _session(ip, token=None):
    """Handshake без повторов. Возвращает протокол, готовый к командам."""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError as ex:
        raise ValueError(f"неверный IPv4: {ip!r}") from ex
    if not addr.is_private:
        raise ValueError(f"разрешены только частные адреса, получено {ip}")
    proto = MiIOProtocol(ip, token, timeout=TIMEOUT)
    try:
        msg = proto.send_handshake(retry_count=0)
    except DeviceException as ex:
        raise LampError(f"лампа {ip} не отвечает: {ex}") from ex
    if token is None:
        proto.token = msg.checksum
    return proto


def _lan_control(proto):
    proto.send("set_ps", ["cfg_lan_ctrl", "1"], retry_count=0)


def _check_wifi(ssid, password):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf8")) <= 32:
        raise ValueError("SSID должен быть от 1 до 32 байт UTF-8")
    if not isinstance(password, str):
        raise ValueError("пароль должен быть строкой")
    size = len(password.encode("utf8"))
    is_hex_key = size == 64 and all(c in "0123456789abcdefABCDEF" for c in password)
    if not (8 <= size <= 63 or is_hex_key):
        raise ValueError("пароль: 8–63 байта или 64 hex-символа")


def enable_lan_control(ip, token=None):
    """Включить LAN Control. Ошибка связи поднимается как LampError."""
    proto = _session(ip, token)
    try:
        _lan_control(proto)
    except DeviceException as ex:
        raise LampError(f"LAN Control на {ip}: {ex}") from ex
    return {"lan_control": "ok"}


def connect_to_wifi(ip, ssid, password, enable_lan_control=False):
    """Отправить Wi-Fi-настройки лампе. Ошибка LAN Control не отменяет Wi-Fi."""
    _check_wifi(ssid, password)
    proto = _session(ip)
    result = {"wifi": "error", "lan_control": "skipped", "detail": ""}
    details = []
    if enable_lan_control:
        try:
            _lan_control(proto)
            result["lan_control"] = "ok"
        except DeviceException as ex:
            result["lan_control"] = "error"
            details.append(f"LAN Control: {ex}")
    try:
        proto.send("miIO.config_router", {"ssid": ssid, "passwd": password, "uid": 0}, retry_count=0)
        result["wifi"] = "sent"
    except DeviceException as ex:
        details.append(f"Wi-Fi: {ex}")
    result["detail"] = "; ".join(details)
    return result
