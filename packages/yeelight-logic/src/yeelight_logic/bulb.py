"""Convenient public API for controlling one lamp."""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

from .controller import YeelightController
from .exceptions import CommandError, DeviceError
from .protocol import LightBulb

logger = logging.getLogger(__name__)

MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 100
MIN_COLOR_TEMP = 1700
MAX_COLOR_TEMP = 6500


class Bulb:
    """Short and safe API for one physical lamp.

    Example::

        bulb = Bulb("192.168.1.45")
        bulb.turn_on()
        bulb.set_brightness(60)
        bulb.set_rgb(51, 170, 255)
        bulb.set_color_temperature(4000)
        bulb.turn_off()

    The object may share a :class:`YeelightController` with other bulbs.  Use
    it as a context manager or call :meth:`close` to release the socket.
    """

    def __init__(
        self, address: str, controller: YeelightController | None = None
    ) -> None:
        self._address = self._validate_address(address)
        self._controller = controller or YeelightController([self._address])
        self._bulb: LightBulb | None = None

    @property
    def address(self) -> str:
        return self._address

    @staticmethod
    def _validate_address(address: str) -> str:
        address = address.strip()
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise CommandError(f"Invalid IP address: {address}") from exc
        if parsed.version != 4:
            raise CommandError("Only IPv4 addresses are supported")
        return address

    def _ensure(self) -> LightBulb:
        if self._bulb is None:
            self._bulb = self._controller.bulb_for(self._address)
        return self._bulb

    # ------------------------------------------------------------------
    # Power
    # ------------------------------------------------------------------

    def turn_on(self) -> None:
        try:
            self._ensure().turn_on()
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not turn on lamp {self._address}: {exc}"
            ) from exc

    def turn_off(self) -> None:
        try:
            self._ensure().turn_off()
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not turn off lamp {self._address}: {exc}"
            ) from exc

    def toggle(self) -> None:
        try:
            bulb = self._ensure()
            props = bulb.get_properties()
            power = props.get("power")
            if power == "on":
                bulb.turn_off()
            elif power == "off":
                bulb.turn_on()
            else:
                raise DeviceError(
                    f"Lamp {self._address} returned an invalid power state: {power!r}"
                )
        except (CommandError, DeviceError):
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not toggle lamp {self._address}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        try:
            props = self._ensure().get_properties()
            return {"ip": self._address, "properties": props}
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not read lamp {self._address}: {exc}"
            ) from exc

    def is_online(self) -> bool:
        try:
            props = self._ensure().get_properties()
            return props.get("power") in ("on", "off")
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Brightness
    # ------------------------------------------------------------------

    def set_brightness(self, brightness: int) -> None:
        if not isinstance(brightness, int) or isinstance(brightness, bool):
            raise CommandError("Brightness must be an integer")
        if not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
            raise CommandError(
                f"Brightness must be between {MIN_BRIGHTNESS} and {MAX_BRIGHTNESS}"
            )
        try:
            self._ensure().set_brightness(brightness)
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not set brightness of lamp {self._address}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Colour
    # ------------------------------------------------------------------

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        for name, value in (("red", red), ("green", green), ("blue", blue)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise CommandError(f"{name} must be an integer")
            if not 0 <= value <= 255:
                raise CommandError(f"{name} must be between 0 and 255")
        try:
            self._ensure().set_rgb(red, green, blue)
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not set colour of lamp {self._address}: {exc}"
            ) from exc

    def set_color(self, hex_color: str) -> None:
        """Set a colour from a ``#RRGGBB`` string."""

        hex_color = hex_color.strip()
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color)
        if match is None:
            raise CommandError("Colour must be in #RRGGBB format")
        value = int(match.group(1), 16)
        self.set_rgb((value >> 16) & 255, (value >> 8) & 255, value & 255)

    # ------------------------------------------------------------------
    # Colour temperature
    # ------------------------------------------------------------------

    def set_color_temperature(self, temperature: int) -> None:
        if not isinstance(temperature, int) or isinstance(temperature, bool):
            raise CommandError("Colour temperature must be an integer")
        if not MIN_COLOR_TEMP <= temperature <= MAX_COLOR_TEMP:
            raise CommandError(
                f"Colour temperature must be between "
                f"{MIN_COLOR_TEMP} and {MAX_COLOR_TEMP} K"
            )
        try:
            self._ensure().set_color_temperature(temperature)
        except CommandError:
            raise
        except Exception as exc:
            raise DeviceError(
                f"Could not set colour temperature of lamp "
                f"{self._address}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._bulb is not None:
            try:
                self._bulb.close()
            except Exception:
                logger.debug(
                    "Error while closing lamp adapter %s",
                    self._address,
                    exc_info=True,
                )
            finally:
                self._bulb = None

    def __enter__(self) -> "Bulb":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
