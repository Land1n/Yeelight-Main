"""Тесты команд на фейковой лампе, без сети."""

import pytest
from yeelight import BulbException

from lamp import Command, Lamp, LampError, SetBrightnessCommand, ToggleCommand
from lamp import device

IP = "192.168.1.45"


class FakeBulb:
    def __init__(self, ip, effect="smooth", duration=300):
        self.calls = []
        self.props = {
            "power": "on",
            "bright": "50",
            "rgb": "16711680",
            "ct": "4000",
            "color_mode": "1",
            "name": "lamp",
        }

    def get_properties(self, requested=None):
        return dict(self.props)

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, args))

        return record


@pytest.fixture
def lamp(monkeypatch):
    monkeypatch.setattr(device, "Bulb", FakeBulb)
    return Lamp(IP)


CASES = [
    ({"type": "turn_on", "ip": IP}, "turn_on", ()),
    ({"type": "turn_off", "ip": IP}, "turn_off", ()),
    ({"type": "toggle", "ip": IP}, "toggle", ()),
    ({"type": "set_brightness", "ip": IP, "value": 30}, "set_brightness", (30,)),
    ({"type": "set_rgb", "ip": IP, "r": 1, "g": 2, "b": 3}, "set_rgb", (1, 2, 3)),
    ({"type": "set_hex", "ip": IP, "value": "#33aaff"}, "set_rgb", (0x33, 0xAA, 0xFF)),
    ({"type": "set_hsv", "ip": IP, "hue": 120, "sat": 50}, "set_hsv", (120, 50)),
    ({"type": "set_color_temp", "ip": IP, "kelvin": 4000}, "set_color_temp", (4000,)),
    ({"type": "set_name", "ip": IP, "name": "desk"}, "set_name", ("desk",)),
]


@pytest.mark.parametrize("data,method,args", CASES)
def test_command_calls_lamp_method(data, method, args, lamp):
    Command.from_dict(data, lamp).execute()
    assert lamp._bulb.calls == [(method, args)]


@pytest.mark.parametrize("data,method,args", CASES)
def test_to_dict_roundtrip(data, method, args, lamp):
    assert Command.from_dict(data, lamp).to_dict() == data


def test_from_dict_without_lamp_creates_lamp(lamp):
    cmd = Command.from_dict({"type": "turn_on", "ip": IP})
    assert cmd.lamp.ip == IP


@pytest.mark.parametrize(
    "data",
    [
        {"type": "set_brightness", "ip": IP, "value": 0},
        {"type": "set_brightness", "ip": IP, "value": 101},
        {"type": "set_rgb", "ip": IP, "r": 256, "g": 0, "b": 0},
        {"type": "set_hex", "ip": IP, "value": "#zzzzzz"},
        {"type": "set_hsv", "ip": IP, "hue": 360, "sat": 0},
        {"type": "set_color_temp", "ip": IP, "kelvin": 1000},
        {"type": "set_brightness", "ip": IP},
        {"type": "nope", "ip": IP},
    ],
)
def test_invalid_data_raises_value_error(data, lamp):
    with pytest.raises(ValueError):
        Command.from_dict(data, lamp)


def test_lamp_rejects_out_of_range_without_sending(lamp):
    with pytest.raises(ValueError):
        lamp.set_brightness(0)
    assert lamp._bulb.calls == []


def test_undo_restores_snapshot(lamp):
    lamp._bulb.props.update(color_mode="2", ct="4000", rgb="16711680", bright="50")
    cmd = Command.from_dict({"type": "set_rgb", "ip": IP, "r": 255, "g": 0, "b": 0}, lamp)
    cmd.execute()
    lamp._bulb.calls.clear()
    cmd.undo()
    assert ("set_brightness", (50,)) in lamp._bulb.calls
    assert ("set_color_temp", (4000,)) in lamp._bulb.calls


def test_undo_turns_off_if_lamp_was_off(lamp):
    lamp._bulb.props["power"] = "off"
    cmd = SetBrightnessCommand(lamp, value=10)
    cmd.execute()
    lamp._bulb.calls.clear()
    cmd.undo()
    assert lamp._bulb.calls[-1] == ("turn_off", ())


def test_toggle_undo_is_toggle(lamp):
    cmd = ToggleCommand(lamp)
    cmd.execute()
    cmd.undo()
    assert lamp._bulb.calls == [("toggle", ()), ("toggle", ())]


def test_network_error_becomes_lamp_error(lamp):
    def fail(*args):
        raise BulbException("нет связи")

    lamp._bulb.get_properties = fail
    with pytest.raises(LampError):
        lamp.state()
