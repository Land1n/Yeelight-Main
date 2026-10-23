"""Lamp controller: device list, discovery and a thin command facade."""

from __future__ import annotations

import functools
import ipaddress
import re
import shlex
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .exceptions import CommandError, DeviceError, StorageError
from .protocol import LightBulb, RealBulb
from .storage import read_json_atomic, write_json_atomic

# Yeelight firmware rejects more than roughly 60 LAN commands per minute with
# "client quota exceeded"; keep a margin so modes never hit the limit.
MIN_COMMAND_INTERVAL_SECONDS = 1.05
# The lamp closes connections that stay idle for about a minute.
SOCKET_IDLE_TIMEOUT_SECONDS = 30.0


class YeelightController:
    """Manage known lamps and execute operations against them.

    One controller can serve several lamps.  A reusable, thread-safe adapter is
    created per IP address; every public operation on a lamp goes through that
    adapter and therefore through the same retry/rate-limit code.
    """

    def __init__(
        self,
        addresses: Iterable[str] = (),
        bulb_factory: Callable[[str], LightBulb] | None = None,
        discovery: Callable[[], list[dict[str, Any]]] | None = None,
        storage_path: str | Path | None = None,
        min_command_interval: float = MIN_COMMAND_INTERVAL_SECONDS,
        socket_idle_timeout: float = SOCKET_IDLE_TIMEOUT_SECONDS,
    ) -> None:
        self._addresses: set[str] = set()
        self._address_lock = threading.RLock()
        self._bulbs: dict[str, LightBulb] = {}
        self._bulb_locks: dict[str, threading.Lock] = {}
        self._bulbs_lock = threading.Lock()
        self._min_command_interval = min_command_interval
        self._socket_idle_timeout = socket_idle_timeout
        self._bulb_factory = bulb_factory or self._create_bulb
        self._discovery = discovery
        self._storage_path = Path(storage_path) if storage_path is not None else None
        if self._storage_path is not None and self._storage_path.is_file():
            try:
                saved = read_json_atomic(self._storage_path, [])
                if not isinstance(saved, list) or any(
                    not isinstance(address, str) for address in saved
                ):
                    raise ValueError("Lamp storage must contain a list of IP addresses")
                for address in saved:
                    self._addresses.add(self._validate_address(address))
            except (OSError, ValueError) as exc:
                raise RuntimeError(
                    f"Could not load lamp addresses from {self._storage_path}: {exc}"
                ) from exc
        for address in addresses:
            self.add(address)

    # ------------------------------------------------------------------
    # Known lamps
    # ------------------------------------------------------------------

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
        with self._bulbs_lock:
            bulb = self._bulbs.pop(address, None)
            self._bulb_locks.pop(address, None)
        if bulb is not None:
            self._close_bulb(bulb)
        return address

    def known_bulbs(self) -> list[dict[str, str]]:
        with self._address_lock:
            return [{"ip": ip} for ip in sorted(self._addresses)]

    def is_known(self, address: str) -> bool:
        with self._address_lock:
            return address in self._addresses

    def bulb_for(self, address: str) -> LightBulb:
        """Return the reusable adapter for ``address``."""

        return self._get_bulb(self._validate_address(address))

    def _get_bulb(self, address: str) -> LightBulb:
        with self._bulbs_lock:
            bulb = self._bulbs.get(address)
            if bulb is None:
                lock = self._bulb_locks.setdefault(address, threading.Lock())
                bulb = _LockedBulb(
                    self._bulb_factory(address),
                    lock,
                    self._min_command_interval,
                    self._socket_idle_timeout,
                )
                self._bulbs[address] = bulb
            return bulb

    # ------------------------------------------------------------------
    # Legacy text command interface
    # ------------------------------------------------------------------

    def execute(
        self, line: str, bulb: LightBulb | None = None
    ) -> dict[str, Any]:
        """Execute a legacy text command.

        This facade is kept for compatibility with existing scripts and the
        console.  New code should use :class:`yeelight_logic.Bulb`, the command
        classes or :func:`yeelight_logic.actions.execute_action`.
        """

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

        if operation not in {
            "on",
            "off",
            "toggle",
            "status",
            "brightness",
            "color",
            "temp",
        }:
            raise CommandError(f"Unknown command: {operation}")
        expected = {
            "on": 1,
            "off": 1,
            "toggle": 1,
            "status": 1,
            "brightness": 2,
            "temp": 2,
        }.get(operation)
        if expected is not None:
            self._require_args(operation, args, expected)
        elif operation == "color" and len(args) not in {2, 4}:
            raise CommandError(
                "Usage: color <IP> <#RRGGBB> or color <IP> <R> <G> <B>"
            )

        address = args[0]
        if address not in self._addresses:
            raise CommandError(
                f"Unknown lamp {address}; run 'discover' or 'add {address}' first"
            )

        action, params = _parse_legacy_action(operation, args)
        from .actions import execute_action

        result = execute_action(
            self, action, address=address, params=params, bulb=bulb
        )
        if not result.ok:
            _raise_for_result(result.error_code, result.message)
        return dict(result.data or {"message": result.message})

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[dict[str, Any]]:
        try:
            if self._discovery is None:
                from yeelight import discover_bulbs

                found = discover_bulbs()
            else:
                found = self._discovery()
        except Exception as exc:
            raise DeviceError(f"Yeelight discovery failed: {exc}") from exc

        bulbs: list[dict[str, Any]] = []
        added_addresses: list[str] = []
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._bulbs_lock:
            bulbs = list(self._bulbs.values())
            self._bulbs.clear()
            self._bulb_locks.clear()
        for bulb in bulbs:
            self._close_bulb(bulb)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_address(address: str) -> str:
        address = address.strip()
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise CommandError(f"Invalid IP address: {address}") from exc
        if parsed.version != 4:
            raise CommandError("Yeelight LAN control supports IPv4 addresses only")
        return address

    def _save_addresses(self) -> None:
        if self._storage_path is None:
            return
        write_json_atomic(self._storage_path, sorted(self._addresses))

    @staticmethod
    def _create_bulb(address: str) -> LightBulb:
        return RealBulb(address)

    @staticmethod
    def _close_bulb(bulb: LightBulb) -> None:
        try:
            bulb.close()
        except Exception:
            pass

    @staticmethod
    def _require_args(operation: str, args: list[str], count: int) -> None:
        if len(args) != count:
            raise CommandError(
                f"Usage error for '{operation}': expected {count} argument(s)"
            )


class _LockedBulb:
    """Serialize and pace access to one lamp socket.

    Yeelight firmware allows about 60 LAN commands per minute and answers
    ``client quota exceeded`` above that limit.  Idle sockets are dropped
    because the lamp closes unused connections itself and a stale socket turns
    the next command into a transport error.
    """

    def __init__(
        self,
        bulb: LightBulb,
        lock: threading.Lock,
        min_interval: float,
        idle_timeout: float,
    ) -> None:
        self._bulb = bulb
        self._lock = lock
        self._min_interval = min_interval
        self._idle_timeout = idle_timeout
        self._last_call = 0.0

    def _drop_idle_socket(self) -> None:
        if self._idle_timeout <= 0:
            return
        if time.monotonic() - self._last_call < self._idle_timeout:
            return
        try:
            self._bulb.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._bulb, name)
        if not callable(attribute):
            return attribute

        @functools.wraps(attribute)
        def locked(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                if self._min_interval > 0:
                    wait = self._min_interval - (
                        time.monotonic() - self._last_call
                    )
                    if wait > 0:
                        time.sleep(wait)
                self._drop_idle_socket()
                try:
                    return attribute(*args, **kwargs)
                finally:
                    self._last_call = time.monotonic()

        return locked


def _parse_legacy_action(
    operation: str, args: list[str]
) -> tuple[str, dict[str, Any]]:
    if operation == "on":
        return "power", {"state": "on"}
    if operation == "off":
        return "power", {"state": "off"}
    if operation in {"toggle", "status"}:
        if operation == "toggle":
            return "power", {"state": "toggle"}
        return operation, {}
    if operation == "brightness":
        return "brightness", {"value": parse_int(args[1], "brightness", 1, 100)}
    if operation == "temp":
        return "color_temperature", {
            "value": parse_int(args[1], "temperature", 1700, 6500)
        }
    if len(args) == 4:
        red, green, blue = (
            parse_int(value, name, 0, 255)
            for value, name in zip(args[1:], ("red", "green", "blue"))
        )
    else:
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", args[1])
        if match is None:
            raise CommandError(
                "Color must be RGB values (0-255) or six-digit hex"
            )
        value = int(match.group(1), 16)
        red, green, blue = (value >> 16) & 255, (value >> 8) & 255, value & 255
    return "color", {"rgb": [red, green, blue]}


def _raise_for_result(error_code: str | None, message: str) -> None:
    if error_code == "command_error":
        raise CommandError(message)
    if error_code == "storage_error":
        raise StorageError(message)
    raise DeviceError(message)


def parse_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    """Validate an integer coming from a command or JSON payload."""

    if isinstance(value, bool) or isinstance(value, float):
        raise CommandError(f"{name.capitalize()} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{name.capitalize()} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise CommandError(f"{name.capitalize()} must be between {minimum} and {maximum}")
    return result
