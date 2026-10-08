import unittest

from yeelight_logic import CommandError, YeelightController


class FakeBulb:
    def __init__(self) -> None:
        self.power = "off"
        self.brightness = None
        self.rgb = None
        self.temperature = None

    def turn_on(self) -> None:
        self.power = "on"

    def turn_off(self) -> None:
        self.power = "off"

    def get_properties(self) -> dict[str, str]:
        return {"power": self.power}

    def set_brightness(self, value: int) -> None:
        self.brightness = value

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        self.rgb = (red, green, blue)

    def set_color_temp(self, value: int) -> None:
        self.temperature = value


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bulb = FakeBulb()
        self.controller = YeelightController(
            ["192.168.1.45"],
            bulb_factory=lambda _address: self.bulb,
            discovery=lambda: [{"ip": "192.168.1.46"}],
        )

    def test_command_controls_bulb(self) -> None:
        self.controller.execute("on 192.168.1.45")
        self.assertEqual(self.bulb.power, "on")
        self.controller.execute("brightness 192.168.1.45 60")
        self.assertEqual(self.bulb.brightness, 60)
        self.controller.execute("color 192.168.1.45 #33aaff")
        self.assertEqual(self.bulb.rgb, (51, 170, 255))
        self.controller.execute("temp 192.168.1.45 4000")
        self.assertEqual(self.bulb.temperature, 4000)

    def test_toggle_and_discovery(self) -> None:
        self.assertEqual(self.controller.execute("toggle 192.168.1.45")["power"], "on")
        found = self.controller.execute("discover")["bulbs"]
        self.assertEqual(found, [{"ip": "192.168.1.46"}])
        self.assertEqual(len(self.controller.execute("list")["bulbs"]), 2)

    def test_rejects_invalid_commands_and_addresses(self) -> None:
        for command in (
            "wat",
            "brightness 192.168.1.45 101",
            "color 192.168.1.45 red",
            "on 192.168.1.99",
            "add not-an-ip",
        ):
            with self.subTest(command=command), self.assertRaises(CommandError):
                self.controller.execute(command)


if __name__ == "__main__":
    unittest.main()

