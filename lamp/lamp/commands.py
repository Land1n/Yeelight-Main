"""Команды над лампой с сериализацией в dict и откатом (undo)."""

from abc import ABC, abstractmethod
from typing import ClassVar

from lamp.device import Lamp, _check, parse_hex


class Command(ABC):
    """Базовая команда. Подклассы задают name, fields и реализуют _apply."""

    name: ClassVar[str] = ""
    fields: ClassVar[tuple] = ()
    _registry: ClassVar[dict] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            Command._registry[cls.name] = cls

    def __init__(self, lamp, **args):
        if set(args) != set(self.fields):
            raise ValueError(f"{self.name}: нужны параметры {list(self.fields)}, получено {sorted(args)}")
        self.lamp = lamp
        self.args = args
        self._before = None
        self._validate()

    def _validate(self):
        """Проверка значений; вызывается при создании, поэтому from_dict бросает ValueError сразу."""

    @abstractmethod
    def _apply(self):
        """Отправить команду лампе."""

    def execute(self):
        self._before = self.lamp.state()
        self._apply()

    def undo(self):
        """Восстановить снимок состояния, сделанный перед execute."""
        if self._before is None:
            raise RuntimeError("undo: команда ещё не выполнялась")
        before, lamp = self._before, self.lamp
        if before["bright"] is not None and 1 <= before["bright"] <= 100:
            lamp.set_brightness(before["bright"])
        if before["color_mode"] == 2 and before["ct"] is not None:
            lamp.set_color_temp(before["ct"])
        elif before["rgb"] is not None:
            rgb = before["rgb"]
            lamp.set_rgb(rgb >> 16, (rgb >> 8) & 255, rgb & 255)
        if before["power"] == "off":
            lamp.turn_off()
        elif before["power"] == "on":
            lamp.turn_on()

    def to_dict(self):
        return {"type": self.name, "ip": self.lamp.ip, **self.args}

    @staticmethod
    def from_dict(data, lamp=None):
        data = dict(data)
        kind = data.pop("type", None)
        cls = Command._registry.get(kind)
        if cls is None:
            raise ValueError(f"неизвестная команда: {kind!r}")
        ip = data.pop("ip", None)
        if lamp is None:
            if not ip:
                raise ValueError("нужен ip лампы")
            lamp = Lamp(ip)
        return cls(lamp, **data)


class TurnOnCommand(Command):
    name = "turn_on"

    def _apply(self):
        self.lamp.turn_on()


class TurnOffCommand(Command):
    name = "turn_off"

    def _apply(self):
        self.lamp.turn_off()


class ToggleCommand(Command):
    name = "toggle"

    def _apply(self):
        self.lamp.toggle()

    def undo(self):
        self.lamp.toggle()


class SetBrightnessCommand(Command):
    name = "set_brightness"
    fields = ("value",)

    def _validate(self):
        _check(self.args["value"], 1, 100, "яркость")

    def _apply(self):
        self.lamp.set_brightness(self.args["value"])


class SetRgbCommand(Command):
    name = "set_rgb"
    fields = ("r", "g", "b")

    def _validate(self):
        for key in self.fields:
            _check(self.args[key], 0, 255, key)

    def _apply(self):
        self.lamp.set_rgb(self.args["r"], self.args["g"], self.args["b"])


class SetHexCommand(Command):
    name = "set_hex"
    fields = ("value",)

    def _validate(self):
        parse_hex(self.args["value"])

    def _apply(self):
        self.lamp.set_hex(self.args["value"])


class SetHsvCommand(Command):
    name = "set_hsv"
    fields = ("hue", "sat")

    def _validate(self):
        _check(self.args["hue"], 0, 359, "оттенок")
        _check(self.args["sat"], 0, 100, "насыщенность")

    def _apply(self):
        self.lamp.set_hsv(self.args["hue"], self.args["sat"])


class SetColorTempCommand(Command):
    name = "set_color_temp"
    fields = ("kelvin",)

    def _validate(self):
        _check(self.args["kelvin"], 1700, 6500, "температура")

    def _apply(self):
        self.lamp.set_color_temp(self.args["kelvin"])


class SetNameCommand(Command):
    name = "set_name"
    fields = ("name",)

    def _validate(self):
        if not isinstance(self.args["name"], str):
            raise ValueError("имя должно быть строкой")

    def _apply(self):
        self.lamp.set_name(self.args["name"])
