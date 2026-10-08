import unittest

from yeelight_app.__main__ import local_command, main


class FakePage:
    def __init__(self) -> None:
        self.controls = []

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def run_task(self, _handler) -> None:
        pass

    def update(self) -> None:
        pass


class FletAppTests(unittest.TestCase):
    def test_app_builds_mobile_layout(self) -> None:
        page = FakePage()
        main(page)

        self.assertEqual(page.title, "Yeelight")
        self.assertEqual(len(page.controls), 1)
        self.assertEqual(len(page.controls[0].content.controls), 4)

    def test_console_help_and_clear_are_local_commands(self) -> None:
        self.assertEqual(local_command("help"), "help")
        self.assertEqual(local_command(" HELP "), "help")
        self.assertEqual(local_command("?"), "help")
        self.assertEqual(local_command("clear"), "clear")
        self.assertEqual(local_command("cls"), "clear")
        self.assertIsNone(local_command("on 192.168.1.45"))


if __name__ == "__main__":
    unittest.main()
