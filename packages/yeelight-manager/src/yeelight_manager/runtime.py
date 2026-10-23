"""Local lamp runtime shared by the agent, the local API and the UI.

The runtime is the single place where the manager touches lamps.  It wraps a
:class:`yeelight_logic.YeelightController` (which already serialises and paces
per-lamp access), keeps a small state cache for the web interface, and exposes
provisioning helpers.  All methods are synchronous and may be called from any
thread; the agent and the local API run them in worker threads.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from yeelight_logic import (
    CommandError,
    CommandResult,
    ProvisioningResult,
    YeelightController,
    connect_to_wifi,
    discover_bulbs,
    enable_lan_control,
    execute_action,
)

from .settings import ManagerSettings

logger = logging.getLogger(__name__)

STATE_ACTIONS = frozenset({"power", "brightness", "color", "color_temperature", "status"})


def _int_or_none(value: Any, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _rgb_from_value(value: Any) -> tuple[int, int, int] | None:
    packed = _int_or_none(value, 0, 0xFFFFFF)
    if packed is None:
        return None
    return ((packed >> 16) & 255, (packed >> 8) & 255, packed & 255)


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class LampState:
    """Cached information about one known lamp."""

    ip: str
    name: str | None = None
    model: str | None = None
    online: bool | None = None
    power: str | None = None
    brightness: int | None = None
    color_mode: str | None = None
    color_temperature: int | None = None
    rgb: tuple[int, int, int] | None = None
    last_seen: float | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "name": self.name,
            "model": self.model,
            "online": self.online,
            "power": self.power,
            "brightness": self.brightness,
            "color_mode": self.color_mode,
            "color_temperature": self.color_temperature,
            "rgb": list(self.rgb) if self.rgb else None,
            "last_seen": self.last_seen,
            "last_error": self.last_error,
        }

    def report(self) -> dict[str, Any]:
        """Compact record relayed to the server."""

        return {
            "ip": self.ip,
            "name": self.name,
            "model": self.model,
            "online": self.online,
        }


class ManagerRuntime:
    """Known lamps, cached state and provisioning for one manager."""

    def __init__(
        self,
        settings: ManagerSettings,
        *,
        controller: YeelightController | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._clock = clock
        if controller is None:
            controller = YeelightController(
                storage_path=settings.bulbs_file,
                discovery=lambda: discover_bulbs(
                    timeout=settings.discovery_timeout_seconds
                ),
            )
        self._controller = controller
        self._lock = threading.RLock()
        self._states: dict[str, LampState] = {}
        self._listeners: list[Callable[[str], None]] = []
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_listener(self, listener: Callable[[str], None]) -> None:
        """Register a callback invoked (from worker threads) on changes."""

        with self._lock:
            self._listeners.append(listener)

    def _emit(self, reason: str) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(reason)
            except Exception:  # pragma: no cover - listener errors are isolated
                logger.exception("Manager runtime listener failed")

    # ------------------------------------------------------------------
    # Known lamps
    # ------------------------------------------------------------------

    def known_ips(self) -> list[str]:
        with self._lock:
            known = set(self._states)
        known.update(item["ip"] for item in self._controller.known_bulbs())
        return sorted(known)

    def lamp_states(self) -> list[dict[str, Any]]:
        with self._lock:
            states = dict(self._states)
        return [states[ip].to_dict() for ip in sorted(states)]

    def lamp_reports(self) -> list[dict[str, Any]]:
        with self._lock:
            states = dict(self._states)
        return [states[ip].report() for ip in sorted(states)]

    def add_lamp(self, ip: str) -> CommandResult:
        result = self._run("add", None, {"ip": ip})
        if result.ok and isinstance(result.data, dict):
            address = str(result.data.get("ip") or ip)
            with self._lock:
                self._states.setdefault(address, LampState(ip=address))
        return result

    def remove_lamp(self, ip: str) -> CommandResult:
        result = self._run("remove", None, {"ip": ip})
        if result.ok:
            with self._lock:
                self._states.pop(ip, None)
        return result

    def discover(self) -> CommandResult:
        result = self._run("discover", None, {})
        if result.ok and isinstance(result.data, dict):
            bulbs = result.data.get("bulbs")
            if isinstance(bulbs, list):
                self._remember_discovery(bulbs)
        return result

    def _remember_discovery(self, bulbs: list[Any]) -> None:
        now = self._clock()
        with self._lock:
            for item in bulbs:
                if not isinstance(item, dict):
                    continue
                ip = _text_or_none(item.get("ip"))
                if not ip:
                    continue
                capabilities = item.get("capabilities")
                capabilities = capabilities if isinstance(capabilities, dict) else {}
                state = self._states.get(ip, LampState(ip=ip))
                changes: dict[str, Any] = {
                    "last_seen": now,
                    "last_error": None,
                    "online": True,
                }
                model = _text_or_none(capabilities.get("model"))
                if model:
                    changes["model"] = model
                name = _text_or_none(capabilities.get("name"))
                if name:
                    changes["name"] = name
                power = capabilities.get("power")
                if power in {"on", "off"}:
                    changes["power"] = power
                brightness = _int_or_none(capabilities.get("bright"), 0, 100)
                if brightness is not None:
                    changes["brightness"] = brightness
                temperature = _int_or_none(capabilities.get("ct"), 1700, 6500)
                if temperature is not None:
                    changes["color_temperature"] = temperature
                rgb = _rgb_from_value(capabilities.get("rgb"))
                if rgb is not None:
                    changes["rgb"] = rgb
                self._states[ip] = replace(state, **changes)
        self._emit("discover")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def run_action(
        self,
        action: str,
        ip: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Validate and execute one typed action, updating the state cache."""

        if not isinstance(action, str):
            return CommandResult(
                False, "Action must be a string", error_code="command_error"
            )
        result = self._run(action, ip, params if isinstance(params, dict) else {})
        if action == "discover":
            if result.ok and isinstance(result.data, dict):
                bulbs = result.data.get("bulbs")
                if isinstance(bulbs, list):
                    self._remember_discovery(bulbs)
            self._emit("discover")
        elif action in {"add", "remove", "list"}:
            self._apply_list_change(action, result)
            self._emit("lamps")
        else:
            self._apply_result(action, result, ip)
            self._emit("state")
        return result

    def _apply_list_change(self, action: str, result: CommandResult) -> None:
        """Update the cache for list operations without probing the lamp."""

        if not result.ok or not isinstance(result.data, dict):
            return
        address = _text_or_none(result.data.get("ip"))
        if not address:
            return
        with self._lock:
            if action == "add":
                self._states.setdefault(address, LampState(ip=address))
            elif action == "remove":
                self._states.pop(address, None)

    def _run(
        self, action: str, ip: str | None, params: dict[str, Any]
    ) -> CommandResult:
        try:
            return execute_action(self._controller, action, address=ip, params=params)
        except Exception as exc:  # defensive: execute_action should not raise
            logger.exception("Action %r crashed", action)
            return CommandResult(False, f"Action failed: {exc}", error_code="internal_error")

    def _apply_result(
        self, action: str, result: CommandResult, ip: str | None = None
    ) -> None:
        if isinstance(result.data, dict):
            ip = ip or _text_or_none(result.data.get("ip"))
        if ip is None:
            return
        with self._lock:
            state = self._states.get(ip)
            if state is None:
                if not result.ok:
                    return
                state = LampState(ip=ip)
            if result.ok:
                changes: dict[str, Any] = {
                    "online": True,
                    "last_seen": self._clock(),
                    "last_error": None,
                }
                data = result.data or {}
                if action == "power" and data.get("power") in {"on", "off"}:
                    changes["power"] = data["power"]
                elif action == "brightness":
                    brightness = _int_or_none(data.get("brightness"), 0, 100)
                    if brightness is not None:
                        changes["brightness"] = brightness
                elif action == "color":
                    rgb = data.get("rgb")
                    if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
                        changes["rgb"] = tuple(int(value) for value in rgb)
                elif action == "color_temperature":
                    temperature = _int_or_none(data.get("color_temperature"), 1700, 6500)
                    if temperature is not None:
                        changes["color_temperature"] = temperature
                elif action == "status":
                    properties = data.get("properties")
                    if isinstance(properties, dict):
                        changes.update(self._properties_changes(properties))
                self._states[ip] = replace(state, **changes)
            else:
                # Validation errors never reached the lamp, so they must not
                # make a reachable lamp look offline in the UI.
                changes: dict[str, Any] = {
                    "last_error": (result.message or "command failed")[:300],
                }
                if result.error_code != "command_error":
                    changes["online"] = False
                self._states[ip] = replace(state, **changes)

    @staticmethod
    def _properties_changes(properties: dict[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        power = properties.get("power")
        if power in {"on", "off"}:
            changes["power"] = power
        brightness = _int_or_none(properties.get("bright"), 0, 100)
        if brightness is not None:
            changes["brightness"] = brightness
        temperature = _int_or_none(properties.get("ct"), 1700, 6500)
        if temperature is not None:
            changes["color_temperature"] = temperature
        rgb = _rgb_from_value(properties.get("rgb"))
        if rgb is not None:
            changes["rgb"] = rgb
        color_mode = properties.get("color_mode")
        if isinstance(color_mode, str) and color_mode in {"0", "1", "2", "3"}:
            changes["color_mode"] = color_mode
        name = _text_or_none(properties.get("name"))
        if name:
            changes["name"] = name
        return changes

    # ------------------------------------------------------------------
    # State monitoring
    # ------------------------------------------------------------------

    def refresh_states(self) -> list[dict[str, Any]]:
        """Poll every known lamp once and refresh the state cache."""

        for ip in self.known_ips():
            self.run_action("status", ip)
        return self.lamp_states()

    def start_monitor(self) -> None:
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="yeelight-manager-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self.settings.poll_interval_seconds):
            try:
                self.refresh_states()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Lamp monitoring failed")

    def stop_monitor(self) -> None:
        self._monitor_stop.set()
        thread = self._monitor_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._monitor_thread = None

    # ------------------------------------------------------------------
    # Provisioning (local only, explicit confirmation required)
    # ------------------------------------------------------------------

    def provision_wifi(
        self,
        ip: str,
        ssid: str,
        password: str,
        *,
        enable_lan_control: bool = False,
        confirm: bool = False,
    ) -> ProvisioningResult:
        """Configure Wi-Fi for a lamp.

        The password is used for one encrypted miIO request and is never
        stored, logged or returned.  ``enable_lan_control`` additionally
        requests LAN Control in the same miIO session.
        """

        if not confirm:
            raise CommandError(
                "Wi-Fi setup requires explicit confirmation (confirm=true)."
            )
        result = connect_to_wifi(
            ip,
            ssid,
            password,
            timeout=self.settings.discovery_timeout_seconds,
            enable_lan_control=enable_lan_control,
        )
        return result

    def provision_lan_control(self, ip: str, *, confirm: bool = False) -> ProvisioningResult:
        """Try to enable LAN Control on a lamp; requires explicit confirmation."""

        if not confirm:
            raise CommandError(
                "LAN Control setup requires explicit confirmation (confirm=true)."
            )
        return enable_lan_control(
            ip, timeout=self.settings.discovery_timeout_seconds
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.stop_monitor()
        self._controller.close()


__all__ = [
    "LampState",
    "ManagerRuntime",
    "STATE_ACTIONS",
]
