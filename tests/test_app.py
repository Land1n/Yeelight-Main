import asyncio
import inspect
import unittest
from unittest.mock import patch

import flet as ft

from yeelight_app.__main__ import local_command, main


class FakePage:
    def __init__(self) -> None:
        self.controls = []
        self.services = []

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def run_task(self, _handler) -> None:
        self.task = _handler

    def update(self) -> None:
        pass


class FletAppTests(unittest.TestCase):
    @staticmethod
    def controls_in(root):
        pending = [root]
        seen = set()
        while pending:
            control = pending.pop()
            if id(control) in seen:
                continue
            seen.add(id(control))
            yield control
            pending.extend(getattr(control, "controls", ()) or ())
            child = getattr(control, "content", None)
            if child is not None:
                pending.append(child)

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

    def test_saved_phone_connection_is_loaded_and_can_be_updated(self) -> None:
        class Preferences:
            def __init__(self) -> None:
                self.values = {
                    "server_url": "http://192.168.1.10:8000",
                    "api_token": "stored-token",
                }

            async def get(self, key):
                return self.values.get(key)

            async def set(self, key, value):
                self.values[key] = value
                return True

        class Response:
            status_code = 200
            is_success = True

            def __init__(self, url):
                self.url = url

            def json(self):
                if self.url.endswith("/api/bulbs"):
                    return {"bulbs": []}
                return {"status": "ok"}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def request(self, _method, url, **_kwargs):
                return Response(url)

        page = FakePage()
        preferences = Preferences()
        with patch("yeelight_app.__main__.ft.SharedPreferences", return_value=preferences):
            main(page)
            self.assertEqual(page.services, [preferences])

        async def verify_connection_settings():
            await page.task()
            controls = list(self.controls_in(page.controls[0]))
            server_field = next(
                c for c in controls
                if isinstance(c, ft.TextField) and c.label == "Адрес сервера"
            )
            token_field = next(
                c for c in controls
                if isinstance(c, ft.TextField) and c.label == "API-токен"
            )
            connect = next(
                c for c in controls
                if isinstance(c, ft.Button)
                and isinstance(c.content, ft.Text)
                and c.content.value == "Сохранить и подключиться"
            )
            self.assertEqual(server_field.value, "http://192.168.1.10:8000")
            self.assertEqual(token_field.value, "stored-token")

            server_field.value = "http://192.168.1.25:8000/"
            token_field.value = "new-token"
            await connect.on_click(None)
            self.assertEqual(preferences.values["server_url"], "http://192.168.1.25:8000")
            self.assertEqual(preferences.values["api_token"], "new-token")

        with patch("yeelight_app.__main__.httpx.AsyncClient", return_value=Client()):
            asyncio.run(verify_connection_settings())


if __name__ == "__main__":
    unittest.main()
