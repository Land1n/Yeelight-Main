from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import tempfile
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol


class CommandError(ValueError):
    """Команда имеет неверный формат или запрашивает неподдерживаемую операцию."""


class DeviceError(RuntimeError):
    """Не удалось выполнить действие с лампой."""


class StorageError(RuntimeError):
    """Не удалось сохранить список ламп."""


class LightAdapter(Protocol):
    def turn_on(self) -> Any: ...
    def turn_off(self) -> Any: ...
    def get_properties(self) -> dict[str, Any]: ...
    def set_brightness(self, brightness: int) -> Any: ...
    def set_rgb(self, red: int, green: int, blue: int) -> Any: ...
    def set_color_temp(self, temperature: int) -> Any: ...


class YeelightController:
    """Сервис команд, использующий LAN-протокол Yeelight."""

    def __init__(
        self,
        addresses: Iterable[str] = (),
        bulb_factory: Callable[[str], LightAdapter] | None = None,
        discovery: Callable[[], list[dict[str, Any]]] | None = None,
        storage_path: str | Path | None = None,
    ) -> None:
        self._addresses: set[str] = set()
        self._address_lock = threading.RLock()
        self._bulb_factory = bulb_factory or self._create_bulb
        self._discovery = discovery
        self._storage_path = Path(storage_path) if storage_path is not None else None
        if self._storage_path is not None and self._storage_path.is_file():
            try:
                saved_addresses = json.loads(
                    self._storage_path.read_text(encoding="utf-8")
                )
                if not isinstance(saved_addresses, list) or any(
                    not isinstance(address, str) for address in saved_addresses
                ):
                    raise ValueError("Lamp storage must contain a list of IP addresses")
                for address in saved_addresses:
                    self._addresses.add(self._validate_address(address))
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    f"Could not load lamp addresses from {self._storage_path}: {exc}"
                ) from exc
        for address in addresses:
            self.add(address)

    def add(self, address: str) -> str:
        address = self._validate_address(address)
        with self._address_lock:
            if address in self._addresses:
                return address
            self._addresses.add(address)
            try:
                self._save_addresses()
            except OSError as exc:
                self._addresses.remove(address)
                raise StorageError(
                    f"Could not save lamp addresses to {self._storage_path}: {exc}"
                ) from exc
        return address

    def remove(self, address: str) -> str:
        address = address.strip()
        with self._address_lock:
            if address not in self._addresses:
                raise CommandError(f"Unknown lamp: {address}")
            self._addresses.remove(address)
            try:
                self._save_addresses()
            except OSError as exc:
                self._addresses.add(address)
                raise StorageError(
                    f"Could not save lamp addresses to {self._storage_path}: {exc}"
                ) from exc
        return address

    def known_bulbs(self) -> list[dict[str, str]]:
        with self._address_lock:
            return [{"ip": ip} for ip in sorted(self._addresses)]

    def execute(self, line: str) -> dict[str, Any]:
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            raise CommandError(f"Could not parse command: {exc}") from exc
        if not parts:
            raise CommandError("Enter a command")

        operation, *args = parts
        if operation == "discover":
            self._require_args(operation, args, 0)
            return {"message": "Discovery completed", "bulbs": self.discover()}
        if operation == "list":
            self._require_args(operation, args, 0)
            return {"bulbs": self.known_bulbs()}
        if operation == "add":
            self._require_args(operation, args, 1)
            address = self.add(args[0])
            return {"message": f"Added {address}", "ip": address}
        if operation == "remove":
            self._require_args(operation, args, 1)
            address = self.remove(args[0])
            return {"message": f"Removed {address}", "ip": address}

        if operation not in {"on", "off", "toggle", "status", "brightness", "color", "temp"}:
            raise CommandError(f"Unknown command: {operation}")
        expected = {"on": 1, "off": 1, "toggle": 1, "status": 1,
                    "brightness": 2, "temp": 2}.get(operation)
        if expected is not None:
            self._require_args(operation, args, expected)
        elif operation == "color" and len(args) not in {2, 4}:
            raise CommandError("Usage: color <IP> <#RRGGBB> or color <IP> <R> <G> <B>")
        address = args[0]
        if address not in self._addresses:
            raise CommandError(f"Unknown lamp {address}; run 'discover' or 'add {address}' first")

        try:
            bulb = self._bulb_factory(address)
            if operation == "on":
                bulb.turn_on()
                return {"message": f"Turned on {address}"}
            if operation == "off":
                bulb.turn_off()
                return {"message": f"Turned off {address}"}
            if operation == "toggle":
                power = bulb.get_properties().get("power")
                if power not in {"on", "off"}:
                    raise DeviceError(f"Lamp {address} returned an invalid power state")
                (bulb.turn_off if power == "on" else bulb.turn_on)()
                return {"message": f"Toggled {address}", "power": "off" if power == "on" else "on"}
            if operation == "status":
                return {"ip": address, "properties": bulb.get_properties()}
            if operation == "brightness":
                brightness = self._integer(args[1], "brightness", 1, 100)
                bulb.set_brightness(brightness)
                return {"message": f"Set brightness of {address} to {brightness}"}
            if operation == "color":
                if len(args) == 4:
                    red, green, blue = (
                        self._integer(value, name, 0, 255)
                        for value, name in zip(args[1:], ("red", "green", "blue"))
                    )
                else:
                    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", args[1])
                    if match is None:
                        raise CommandError("Color must be RGB values (0-255) or six-digit hex")
                    value = int(match.group(1), 16)
                    red, green, blue = (value >> 16) & 255, (value >> 8) & 255, value & 255
                bulb.set_rgb(red, green, blue)
                return {
                    "message": f"Set color of {address} to RGB({red}, {green}, {blue})",
                    "rgb": [red, green, blue],
                }
            temperature = self._integer(args[1], "temperature", 1700, 6500)
            bulb.set_color_temp(temperature)
            return {"message": f"Set color temperature of {address} to {temperature} K"}
        except (CommandError, DeviceError):
            raise
        except Exception as exc:
            raise DeviceError(f"{operation} failed for {address}: {exc}") from exc

    def discover(self) -> list[dict[str, Any]]:
        try:
            if self._discovery is None:
                from yeelight import discover_bulbs

                found = discover_bulbs()
            else:
                found = self._discovery()
        except Exception as exc:
            raise DeviceError(f"Yeelight discovery failed: {exc}") from exc

        bulbs = []
        added_addresses = []
        with self._address_lock:
            for item in found:
                address = item.get("ip")
                if not isinstance(address, str):
                    continue
                address = self._validate_address(address)
                if address not in self._addresses:
                    self._addresses.add(address)
                    added_addresses.append(address)
                bulbs.append(item)
            if added_addresses:
                try:
                    self._save_addresses()
                except OSError as exc:
                    self._addresses.difference_update(added_addresses)
                    raise StorageError(
                        f"Could not save lamp addresses to {self._storage_path}: {exc}"
                    ) from exc
        return bulbs

    @staticmethod
    def _validate_address(address: str) -> str:
        address = address.strip()
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise CommandError(f"Invalid IP address: {address}") from exc
        if parsed.version != 4:
            raise CommandError("Yeelight LAN discovery currently supports IPv4 addresses only")
        return address

    def _save_addresses(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._storage_path.parent,
                prefix=f".{self._storage_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(sorted(self._addresses), temporary_file, indent=2)
                temporary_file.write("\n")
            os.replace(temporary_path, self._storage_path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _create_bulb(address: str) -> LightAdapter:
        from yeelight import Bulb

        return Bulb(address)

    @staticmethod
    def _require_args(operation: str, args: list[str], count: int) -> None:
        if len(args) != count:
            raise CommandError(f"Usage error for '{operation}': expected {count} argument(s)")

    @staticmethod
    def _integer(value: str, name: str, minimum: int, maximum: int) -> int:
        try:
            result = int(value)
        except ValueError as exc:
            raise CommandError(f"{name.capitalize()} must be an integer") from exc
        if not minimum <= result <= maximum:
            raise CommandError(f"{name.capitalize()} must be between {minimum} and {maximum}")
        return result
