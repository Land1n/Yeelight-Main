"""Contract implemented by every lamp adapter."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LightBulb(Protocol):
    """Minimal lamp adapter used by the controller, commands and tests.

    The real adapter (:class:`yeelight_logic.protocol.RealBulb`) wraps
    ``yeelight.Bulb``; tests use in-memory fakes implementing the same methods.
    """

    def turn_on(self) -> Any: ...
    def turn_off(self) -> Any: ...
    def get_properties(self) -> dict[str, Any]: ...
    def set_brightness(self, brightness: int) -> Any: ...
    def set_rgb(self, red: int, green: int, blue: int) -> Any: ...
    def set_color_temperature(self, temperature: int) -> Any: ...
    def close(self) -> None: ...


class RealBulb:
    """Adapter from ``yeelight.Bulb`` to :class:`LightBulb`.

    ``python-yeelight`` names the colour-temperature method ``set_color_temp``
    and does not expose ``close``.  Keeping this mapping in one place guarantees
    that the direct API, the command layer and the manager use the same calls.
    """

    def __init__(self, address: str) -> None:
        from yeelight import Bulb as _YeelightBulb

        self._bulb = _YeelightBulb(address)

    def turn_on(self) -> Any:
        return self._bulb.turn_on()

    def turn_off(self) -> Any:
        return self._bulb.turn_off()

    def toggle(self) -> Any:
        return self._bulb.toggle()

    def get_properties(self) -> dict[str, Any]:
        return dict(self._bulb.get_properties())

    def set_brightness(self, brightness: int) -> Any:
        return self._bulb.set_brightness(brightness)

    def set_rgb(self, red: int, green: int, blue: int) -> Any:
        return self._bulb.set_rgb(red, green, blue)

    def set_color_temperature(self, temperature: int) -> Any:
        return self._bulb.set_color_temp(temperature)

    def set_color_temp(self, temperature: int) -> Any:
        """Compatibility alias used by older code."""

        return self.set_color_temperature(temperature)

    def close(self) -> None:
        socket = getattr(self._bulb, "_Bulb__socket", None)
        if socket is None:
            return
        try:
            socket.close()
        except OSError:
            pass
        finally:
            self._bulb.__dict__["_Bulb__socket"] = None
