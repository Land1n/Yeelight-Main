"""Проверка на реальной лампе. Запуск: $env:YEELIGHT_TEST_IP="192.168.1.45"; pytest -m hardware"""

import os

import pytest

from lamp import Command, Lamp

IP = os.environ.get("YEELIGHT_TEST_IP")


@pytest.mark.hardware
@pytest.mark.skipif(not IP, reason="нужна переменная YEELIGHT_TEST_IP")
def test_command_sequence_on_real_lamp():
    lamp = Lamp(IP, effect="sudden")
    run = lambda data: Command.from_dict({**data, "ip": IP}, lamp)

    run({"type": "turn_on"}).execute()
    assert lamp.state()["power"] == "on"

    run({"type": "set_brightness", "value": 40}).execute()
    assert lamp.state()["bright"] == 40

    run({"type": "set_rgb", "r": 255, "g": 0, "b": 0}).execute()
    assert lamp.state()["rgb"] == 0xFF0000

    temp = run({"type": "set_color_temp", "kelvin": 4000})
    temp.execute()
    assert lamp.state()["color_mode"] == 2

    temp.undo()
    assert lamp.state()["color_mode"] == 1
    assert lamp.state()["rgb"] == 0xFF0000

    run({"type": "turn_off"}).execute()
    assert lamp.state()["power"] == "off"
