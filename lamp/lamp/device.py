"""Синхронная обёртка над yeelight.Bulb: состояние и базовые операции."""

import string

from yeelight import Bulb, BulbException

STATE_PROPS = ["power", "bright", "rgb", "ct", "color_mode", "name"]
_NUMERIC = ("bright", "rgb", "ct", "color_mode")


class LampError(Exception):
    """Лампа недоступна или отклонила команду."""


def _check(value, lo, hi, name):
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"{name} должно быть целым от {lo} до {hi}, получено {value!r}")
    return value


def parse_hex(value):
    """'#33aaff' -> (51, 170, 255). Бросает ValueError при неверном формате."""
    text = value[1:] if isinstance(value, str) and value.startswith("#") else value
    valid = isinstance(text, str) and len(text) == 6 and all(c in string.hexdigits for c in text)
    if not valid:
        raise ValueError(f"цвет должен быть вида #rrggbb, получено {value!r}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


class Lamp:
    """Одна лампа. Все методы синхронные, ошибки связи превращаются в LampError."""

    def __init__(self, ip, effect="smooth", duration=300):
        self.ip = ip
        self._bulb = Bulb(ip, effect=effect, duration=duration)

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except (BulbException, OSError) as ex:
            raise LampError(f"лампа {self.ip}: {ex}") from ex

    def state(self):
        props = self._call(self._bulb.get_properties, STATE_PROPS)
        out = {key: props.get(key) for key in STATE_PROPS}
        for key in _NUMERIC:
            if out[key] is not None:
                out[key] = int(out[key])
        return out

    def turn_on(self):
        self._call(self._bulb.turn_on)

    def turn_off(self):
        self._call(self._bulb.turn_off)

    def toggle(self):
        self._call(self._bulb.toggle)

    def set_brightness(self, value):
        self._call(self._bulb.set_brightness, _check(value, 1, 100, "яркость"))

    def set_rgb(self, r, g, b):
        rgb = [_check(v, 0, 255, n) for v, n in ((r, "r"), (g, "g"), (b, "b"))]
        self._call(self._bulb.set_rgb, *rgb)

    def set_hex(self, value):
        self.set_rgb(*parse_hex(value))

    def set_hsv(self, hue, sat):
        hue = _check(hue, 0, 359, "оттенок")
        self._call(self._bulb.set_hsv, hue, _check(sat, 0, 100, "насыщенность"))

    def set_color_temp(self, kelvin):
        self._call(self._bulb.set_color_temp, _check(kelvin, 1700, 6500, "температура"))

    def set_name(self, name):
        if not isinstance(name, str):
            raise ValueError("имя должно быть строкой")
        self._call(self._bulb.set_name, name)

    def set_default(self):
        self._call(self._bulb.set_default)
