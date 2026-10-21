import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yeelight_logic import CommandError, parse_int, write_json_atomic
from yeelight_network.modes import ModeStore, normalize_delay, normalize_step


class StorageTests(unittest.TestCase):
    def test_atomic_write_replaces_content_without_leaving_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("[]", encoding="utf-8")

            write_json_atomic(path, {"mode": "ok"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"mode": "ok"})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_failed_write_keeps_previous_file_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"old": true}', encoding="utf-8")

            with patch("yeelight_logic.storage.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    write_json_atomic(path, {"new": True})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"old": True},
            )
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])


class StepValidationTests(unittest.TestCase):
    def test_normalizes_supported_steps(self) -> None:
        self.assertEqual(
            normalize_step({"action": "color", "values": [10, 20, 30]}),
            {"action": "color", "values": [10, 20, 30]},
        )
        self.assertEqual(
            normalize_step({"action": "brightness", "values": ["50"]}),
            {"action": "brightness", "values": [50]},
        )
        self.assertEqual(
            normalize_step({"action": "on"}),
            {"action": "on", "values": []},
        )

    def test_rejects_out_of_range_or_malformed_steps(self) -> None:
        invalid = (
            {"action": "brightness", "values": [500]},
            {"action": "brightness", "values": [True]},
            {"action": "brightness", "values": [50.5]},
            {"action": "temp", "values": [1000]},
            {"action": "color", "values": [0, 0]},
            {"action": "color", "values": [0, 0, 256]},
            {"action": "on", "values": [1]},
            {"action": "wat", "values": []},
            {"action": "on", "values": "on"},
            "on",
        )
        for step in invalid:
            with self.subTest(step=step), self.assertRaises(ValueError):
                normalize_step(step)

    def test_rejects_non_finite_or_out_of_range_delay(self) -> None:
        for value in (0, -1, float("inf"), float("nan"), "abc", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_delay(value)
        self.assertEqual(normalize_delay("1.5"), 1.5)

    def test_parse_int_rejects_bool_and_fractional_values(self) -> None:
        for value in (True, 1.5, "1.5", None, "abc"):
            with self.subTest(value=value), self.assertRaises(CommandError):
                parse_int(value, "brightness", 1, 100)
        self.assertEqual(parse_int("50", "brightness", 1, 100), 50)


class ModeStoreTests(unittest.TestCase):
    def test_legacy_commands_are_migrated_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modes.json"
            path.write_text(
                json.dumps(
                    {
                        "Старый": {
                            "commands": [
                                "on 192.168.1.45",
                                "brightness 192.168.1.45 50",
                                "color 192.168.1.45 #0080ff",
                            ],
                            "delay_seconds": 1,
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = ModeStore(path)

        self.assertEqual(
            store.modes["Старый"]["steps"],
            [
                {"action": "on", "values": []},
                {"action": "brightness", "values": [50]},
                {"action": "color", "values": [0, 128, 255]},
            ],
        )

    def test_invalid_saved_step_values_stop_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modes.json"
            path.write_text(
                json.dumps(
                    {
                        "Плохой": {
                            "steps": [{"action": "brightness", "values": [500]}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "Could not load modes"):
                ModeStore(path)

    def test_invalid_saved_delay_stops_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modes.json"
            path.write_text(
                json.dumps(
                    {
                        "Плохой": {
                            "steps": [{"action": "on", "values": []}],
                            "delay_seconds": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "Could not load modes"):
                ModeStore(path)

    def test_put_and_delete_persist_only_steps_and_delay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "modes.json"
            store = ModeStore(path)
            store.put("Вечер", [{"action": "brightness", "values": [35]}], 2)
            store.put("Вечер", [{"action": "off", "values": []}], 3)
            self.assertEqual(len(store.modes), 1)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved,
                {"Вечер": {"steps": [{"action": "off", "values": []}], "delay_seconds": 3}},
            )

            store.delete("Вечер")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})
            self.assertEqual(store.modes, {})


if __name__ == "__main__":
    unittest.main()
