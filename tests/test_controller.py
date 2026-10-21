import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from yeelight_logic import CommandError, StorageError, YeelightController


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
        self.controller.execute("color 192.168.1.45 0 128 255")
        self.assertEqual(self.bulb.rgb, (0, 128, 255))
        self.controller.execute("temp 192.168.1.45 4000")
        self.assertEqual(self.bulb.temperature, 4000)

    def test_toggle_and_discovery(self) -> None:
        self.assertEqual(self.controller.execute("toggle 192.168.1.45")["power"], "on")
        found = self.controller.execute("discover")["bulbs"]
        self.assertEqual(found, [{"ip": "192.168.1.46"}])
        self.assertEqual(len(self.controller.execute("list")["bulbs"]), 2)

    def test_remove_bulb(self) -> None:
        self.controller.execute("remove 192.168.1.45")
        self.assertEqual(self.controller.known_bulbs(), [])
        with self.assertRaises(CommandError):
            self.controller.execute("remove 192.168.1.45")

    def test_bulb_addresses_persist_across_controller_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "bulbs.json"
            controller = YeelightController(storage_path=storage_path)
            controller.add("192.168.1.45")

            restarted = YeelightController(storage_path=storage_path)
            self.assertEqual(
                restarted.known_bulbs(),
                [{"ip": "192.168.1.45"}],
            )
            restarted.remove("192.168.1.45")
            self.assertEqual(
                json.loads(storage_path.read_text(encoding="utf-8")),
                [],
            )

    def test_discovered_bulbs_are_written_in_one_persistent_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "bulbs.json"
            controller = YeelightController(
                storage_path=storage_path,
                discovery=lambda: [
                    {"ip": "192.168.1.46"},
                    {"ip": "192.168.1.47"},
                ],
            )
            controller.discover()

            restarted = YeelightController(storage_path=storage_path)
            self.assertEqual(
                restarted.known_bulbs(),
                [{"ip": "192.168.1.46"}, {"ip": "192.168.1.47"}],
            )

    def test_concurrent_additions_are_not_lost_from_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "bulbs.json"
            controller = YeelightController(storage_path=storage_path)
            addresses = [f"192.168.1.{ip}" for ip in range(1, 21)]
            with ThreadPoolExecutor(max_workers=8) as workers:
                list(workers.map(controller.add, addresses))

            restarted = YeelightController(storage_path=storage_path)
            self.assertEqual(
                [bulb["ip"] for bulb in restarted.known_bulbs()],
                sorted(addresses),
            )

    def test_invalid_bulb_storage_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage_path = Path(directory) / "bulbs.json"
            storage_path.write_text('{"not": "a list"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Could not load lamp addresses"):
                YeelightController(storage_path=storage_path)

    def test_storage_write_failure_does_not_add_lamp_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid_parent = Path(directory) / "not-a-directory"
            invalid_parent.write_text("file", encoding="utf-8")
            controller = YeelightController(
                storage_path=invalid_parent / "bulbs.json"
            )
            with self.assertRaises(StorageError):
                controller.add("192.168.1.45")
            self.assertEqual(controller.known_bulbs(), [])

    def test_rejects_invalid_commands_and_addresses(self) -> None:
        for command in (
            "wat",
            "brightness 192.168.1.45 101",
            "color 192.168.1.45 red",
            "color 192.168.1.45 0 256 1",
            "color 192.168.1.45 -1 10 20",
            "on 192.168.1.99",
            "add not-an-ip",
        ):
            with self.subTest(command=command), self.assertRaises(CommandError):
                self.controller.execute(command)

    def test_transport_failure_is_retried_for_idempotent_command(self) -> None:
        class FlakyBulb(FakeBulb):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def set_rgb(self, red: int, green: int, blue: int) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError(
                        "A socket error occurred when sending the command."
                    )
                super().set_rgb(red, green, blue)

        bulb = FlakyBulb()
        controller = YeelightController(
            ["192.168.1.45"],
            bulb_factory=lambda _address: bulb,
            min_command_interval=0,
        )
        result = controller.execute("color 192.168.1.45 10 20 30")
        self.assertEqual(result["rgb"], [10, 20, 30])
        self.assertEqual(bulb.calls, 2)

    def test_transport_failure_is_not_retried_for_toggle(self) -> None:
        class FlakyBulb(FakeBulb):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def get_properties(self) -> dict[str, str]:
                self.calls += 1
                raise RuntimeError("A socket error occurred when sending the command.")

        bulb = FlakyBulb()
        controller = YeelightController(
            ["192.168.1.45"],
            bulb_factory=lambda _address: bulb,
            min_command_interval=0,
        )
        with self.assertRaisesRegex(RuntimeError, "socket error"):
            controller.execute("toggle 192.168.1.45")
        self.assertEqual(bulb.calls, 1)

    def test_idle_socket_is_dropped_before_next_command(self) -> None:
        class Socket:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        socket = Socket()
        bulb = FakeBulb()
        bulb.__dict__["_Bulb__socket"] = socket
        controller = YeelightController(
            ["192.168.1.45"],
            bulb_factory=lambda _address: bulb,
            min_command_interval=0,
            socket_idle_timeout=30,
        )
        locked = controller.bulb_for("192.168.1.45")
        locked._last_call = 0.0

        controller.execute("on 192.168.1.45")

        self.assertTrue(socket.closed)
        self.assertIsNone(bulb.__dict__["_Bulb__socket"])
        self.assertEqual(bulb.power, "on")


if __name__ == "__main__":
    unittest.main()
