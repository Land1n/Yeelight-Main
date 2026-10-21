import unittest
from pathlib import Path

from yeelight_config import PROJECT_ROOT
from yeelight_network.server import _project_path


class ServerPathTests(unittest.TestCase):
    def test_relative_env_paths_are_resolved_against_project_root(self) -> None:
        self.assertEqual(
            _project_path("data/modes.json"),
            PROJECT_ROOT / "data" / "modes.json",
        )

    def test_absolute_env_paths_are_kept(self) -> None:
        absolute = Path.cwd() / "custom" / "modes.json"
        self.assertEqual(_project_path(str(absolute)), absolute)


if __name__ == "__main__":
    unittest.main()
