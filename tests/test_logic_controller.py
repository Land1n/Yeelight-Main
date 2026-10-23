from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yeelight_logic import (
    Bulb,
    CommandError,
    DeviceError,
    StorageError,
    YeelightController,
    parse_int,
    read_json_atomic,
    write_json_atomic,
)

from tests.support import make_controller


class ControllerTests(unittest.TestCase):
    def test_add_remove_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "bulbs.json"
            controller, _ = make_controller((), storage_path=storage)
            self.assertEqual(controller.known_bulbs(), [])
            self.assertEqual(controller.add("192.168.1.10"), "192.168.1.10")
            self.assertEqual(controller.add("192.168.1.10"), "192.168.1.10")
            self.assertEqual(controller.known_bulbs(), [{"ip": "192.168.1.10"}])
            self.assertEqual(read_json_atomic(storage), ["192.168.1.10"])

            controller.remove("192.168.1.10")
            self.assertFalse(controller.is_known("192.168.1.10"))
            self.assertEqual(read_json_atomic(storage), [])
            with self.assertRaises(CommandError):
                controller.remove("192.168.1.10")
            controller.close()

            reloaded, _ = make_controller((), storage_path=storage)
            self.assertEqual(reloaded.known_bulbs(), [])
            reloaded.close()

    def test_loading_invalid_storage_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "bulbs.json"
            storage.write_text('{"not": "a list"}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                YeelightController(storage_path=storage)

    def test_invalid_ip_is_rejected(self) -> None:
        controller, _ = make_controller(())
        for address in ("", "not-an-ip", "::1", "192.168.1.999"):
            with self.subTest(address=address):
                with self.assertRaises(CommandError):
                    controller.add(address)
        controller.close()

    def test_discovery_adds_and_persists_lamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "bulbs.json"
            controller, _ = make_controller(
                (),
                discovery_result=[
                    {"ip": "192.168.1.30"},
                    {"ip": "192.168.1.31"},
                    {"missing": "ip"},
                ],
                storage_path=storage,
            )
            found = controller.discover()
            self.assertEqual(len(found), 2)
            self.assertEqual(
                [item["ip"] for item in controller.known_bulbs()],
                ["192.168.1.30", "192.168.1.31"],
            )
            self.assertEqual(
                read_json_atomic(storage), ["192.168.1.30", "192.168.1.31"]
            )
            controller.close()

    def test_discovery_errors_are_wrapped(self) -> None:
        def failing_discovery() -> list[dict[str, object]]:
            raise OSError("network down")

        controller = YeelightController(
            (),
            bulb_factory=lambda address: None,  # type: ignore[arg-type,return-value]
            discovery=failing_discovery,
        )
        with self.assertRaises(DeviceError):
            controller.discover()
        controller.close()

    def test_legacy_text_commands(self) -> None:
        controller, bulbs = make_controller()
        bulb = bulbs["192.168.1.10"]

        self.assertEqual(controller.execute("list")["bulbs"], [{"ip": "192.168.1.10"}])
        self.assertEqual(
            controller.execute("on 192.168.1.10")["power"], "on"
        )
        self.assertEqual(
            controller.execute("brightness 192.168.1.10 70")["brightness"], 70
        )
        self.assertEqual(
            controller.execute("color 192.168.1.10 #102030")["rgb"], [16, 32, 48]
        )
        self.assertEqual(
            controller.execute("color 192.168.1.10 1 2 3")["rgb"], [1, 2, 3]
        )
        self.assertEqual(
            controller.execute("temp 192.168.1.10 3500")["color_temperature"], 3500
        )
        self.assertEqual(
            controller.execute("status 192.168.1.10")["properties"]["power"], "on"
        )
        self.assertEqual(
            controller.execute("off 192.168.1.10")["power"], "off"
        )
        self.assertEqual(
            controller.execute("toggle 192.168.1.10")["power"], "on"
        )
        self.assertEqual(bulb.properties["bright"], "70")
        controller.close()

    def test_legacy_text_command_errors(self) -> None:
        controller, _ = make_controller()
        for line in (
            "",
            "unknown",
            "on",
            "on 192.168.1.99",
            "brightness 192.168.1.10 0",
            "color 192.168.1.10 not-a-colour",
            "add 999.1.1.1",
            "list extra",
        ):
            with self.subTest(line=line):
                with self.assertRaises(CommandError):
                    controller.execute(line)
        with self.assertRaises(StorageError):
            controller._storage_path = Path("Z:/definitely/missing/dir/bulbs.json")
            controller.add("192.168.1.50")

    def test_parse_int(self) -> None:
        self.assertEqual(parse_int("5", "value", 1, 10), 5)
        for value in (True, 1.5, "x", 0, 11):
            with self.subTest(value=value):
                with self.assertRaises(CommandError):
                    parse_int(value, "value", 1, 10)


class BulbTests(unittest.TestCase):
    def test_bulb_wraps_fake_adapter(self) -> None:
        controller, bulbs = make_controller()
        bulb = Bulb("192.168.1.10", controller=controller)
        self.assertEqual(bulb.address, "192.168.1.10")
        # A lamp that answers get_properties() reports as online.
        self.assertTrue(bulb.is_online())
        bulb.turn_on()
        self.assertTrue(bulb.is_online())
        bulb.set_brightness(42)
        bulb.set_rgb(10, 20, 30)
        bulb.set_color("#010203")
        bulb.set_color_temperature(3000)
        bulb.toggle()
        self.assertEqual(bulb.get_status()["ip"], "192.168.1.10")
        self.assertEqual(bulbs["192.168.1.10"].properties["power"], "off")
        with bulb:
            pass
        self.assertTrue(bulbs["192.168.1.10"].closed)
        controller.close()

    def test_bulb_validation(self) -> None:
        controller, _ = make_controller()
        with self.assertRaises(CommandError):
            Bulb("bad-ip")
        bulb = Bulb("192.168.1.10", controller=controller)
        for method, value in (
            (bulb.set_brightness, 0),
            (bulb.set_brightness, True),
            (bulb.set_color_temperature, 1000),
            (bulb.set_color_temperature, 7000),
            (bulb.set_color, "red"),
        ):
            with self.subTest(method=method, value=value):
                with self.assertRaises(CommandError):
                    method(value)  # type: ignore[operator]
        for rgb in ((-1, 0, 0), (0, 256, 0), (0, 0, True)):
            with self.subTest(rgb=rgb):
                with self.assertRaises(CommandError):
                    bulb.set_rgb(*rgb)  # type: ignore[arg-type]
        controller.close()


class StorageTests(unittest.TestCase):
    def test_atomic_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "value.json"
            write_json_atomic(path, {"ключ": [1, 2, 3]})
            self.assertEqual(read_json_atomic(path), {"ключ": [1, 2, 3]})
            self.assertEqual(read_json_atomic(Path(directory) / "missing.json", []), [])

    def test_corrupt_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_json_atomic(path)


if __name__ == "__main__":
    unittest.main()
