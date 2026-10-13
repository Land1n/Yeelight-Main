import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

import configure_phone


class PhoneSetupTests(unittest.TestCase):
    def test_creates_lan_configuration_and_random_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / ".env"
            example_file = root / ".env.example"
            example_file.write_text(
                "YEELIGHT_HOST=127.0.0.1\n"
                "YEELIGHT_PORT=8000\n"
                "YEELIGHT_API_TOKEN=\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch.object(configure_phone, "ROOT", root),
                patch.object(configure_phone, "ENV_FILE", env_file),
                patch.object(configure_phone, "EXAMPLE_FILE", example_file),
                patch.object(
                    configure_phone,
                    "lan_ipv4",
                    return_value=["192.168.1.10", "10.0.0.8"],
                ),
                contextlib.redirect_stdout(output),
            ):
                configure_phone.main()

            settings = dotenv_values(env_file)
            self.assertEqual(settings["YEELIGHT_HOST"], "0.0.0.0")
            self.assertEqual(settings["YEELIGHT_PORT"], "8000")
            self.assertGreaterEqual(len(settings["YEELIGHT_API_TOKEN"]), 40)
            self.assertIn("http://192.168.1.10:8000", output.getvalue())
            self.assertIn("http://10.0.0.8:8000", output.getvalue())
            self.assertNotIn(settings["YEELIGHT_API_TOKEN"], output.getvalue())

    def test_invalid_port_does_not_modify_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            original = "YEELIGHT_HOST=127.0.0.1\nYEELIGHT_PORT=invalid\n"
            env_file.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "YEELIGHT_PORT"):
                configure_phone.configure_phone_access(env_file)

            self.assertEqual(env_file.read_text(encoding="utf-8"), original)

    def test_configuration_preserves_existing_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "YEELIGHT_HOST=127.0.0.1\n"
                "YEELIGHT_PORT=8123\n"
                "YEELIGHT_API_TOKEN=existing-token\n",
                encoding="utf-8",
            )

            port = configure_phone.configure_phone_access(env_file)

            settings = dotenv_values(env_file)
            self.assertEqual(port, 8123)
            self.assertEqual(settings["YEELIGHT_HOST"], "0.0.0.0")
            self.assertEqual(settings["YEELIGHT_API_TOKEN"], "existing-token")


if __name__ == "__main__":
    unittest.main()
