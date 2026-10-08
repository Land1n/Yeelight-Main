import inspect
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

    def test_async_event_handlers_are_not_wrapped_in_sync_lambdas(self) -> None:
        page = FakePage()
        main(page)
        pending = list(page.controls)
        handlers = []
        while pending:
            control = pending.pop()
            for name in ("on_click", "on_submit"):
                handler = getattr(control, name, None)
                if handler is not None:
                    handlers.append(handler)
            pending.extend(getattr(control, "controls", ()) or ())
            child = getattr(control, "content", None)
            if child is not None:
                pending.append(child)

        self.assertTrue(handlers)
        self.assertTrue(all(inspect.iscoroutinefunction(handler) for handler in handlers))

    def test_console_help_and_clear_are_local_commands(self) -> None:
        self.assertEqual(local_command("help"), "help")
        self.assertEqual(local_command(" HELP "), "help")
        self.assertEqual(local_command("?"), "help")
        self.assertEqual(local_command("clear"), "clear")
        self.assertEqual(local_command("cls"), "clear")
        self.assertIsNone(local_command("on 192.168.1.45"))


if __name__ == "__main__":
    unittest.main()
