import asyncio
import unittest
from unittest.mock import patch

import httpx

from yeelight_app.api_client import YeelightApiClient


class FakeResponse:
    status_code = 200
    is_success = True

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.request_args = None
        self.request_count = 0
        self.closed = False

    async def request(self, *args, **kwargs):
        self.request_count += 1
        self.request_args = (args, kwargs)
        return self.response

    async def aclose(self):
        self.closed = True


class ApiClientTests(unittest.TestCase):
    def test_command_uses_normalized_url_token_and_json(self) -> None:
        async def verify() -> None:
            http_client = FakeHttpClient(FakeResponse({"result": {"message": "ok"}}))
            api = YeelightApiClient(" http://192.168.1.10:8000/ ", " secret ")
            with patch(
                "yeelight_app.api_client.httpx.AsyncClient",
                return_value=http_client,
            ):
                result = await api.execute("on 192.168.1.45")

            self.assertEqual(result, {"message": "ok"})
            args, kwargs = http_client.request_args
            self.assertEqual(args, ("POST", "http://192.168.1.10:8000/api/commands"))
            self.assertEqual(kwargs["headers"], {"X-API-Token": "secret"})
            self.assertEqual(kwargs["json"], {"command": "on 192.168.1.45"})
            await api.aclose()
            self.assertTrue(http_client.closed)

        asyncio.run(verify())

    def test_rejects_invalid_server_url(self) -> None:
        async def verify() -> None:
            api = YeelightApiClient("not-a-url")
            with self.assertRaisesRegex(ValueError, "Введите адрес сервера"):
                await api.check_health()

        asyncio.run(verify())

    def test_rejects_malformed_bulb_list(self) -> None:
        async def verify() -> None:
            api = YeelightApiClient("http://127.0.0.1:8000")
            with patch(
                "yeelight_app.api_client.httpx.AsyncClient",
                return_value=FakeHttpClient(FakeResponse({"bulbs": "invalid"})),
            ):
                with self.assertRaisesRegex(RuntimeError, "список ламп"):
                    await api.list_bulbs()
                await api.aclose()

        asyncio.run(verify())

    def test_reuses_http_client_and_closes_it(self) -> None:
        async def verify() -> None:
            http_client = FakeHttpClient(FakeResponse({"status": "ok"}))
            api = YeelightApiClient("http://127.0.0.1:8000")
            with patch(
                "yeelight_app.api_client.httpx.AsyncClient",
                return_value=http_client,
            ) as client_factory:
                await api.check_health()
                await api.check_health()
                self.assertEqual(client_factory.call_count, 1)
                self.assertEqual(http_client.request_count, 2)

                await api.aclose()
                self.assertTrue(http_client.closed)
                self.assertIsNone(api._client)

        asyncio.run(verify())

    def test_reports_connection_timeout(self) -> None:
        async def verify() -> None:
            class TimedOutClient(FakeHttpClient):
                async def request(self, *_args, **_kwargs):
                    raise httpx.ConnectTimeout("connection timed out")

            api = YeelightApiClient("http://127.0.0.1:8000")
            client = TimedOutClient(FakeResponse({}))
            with patch(
                "yeelight_app.api_client.httpx.AsyncClient",
                return_value=client,
            ):
                with self.assertRaisesRegex(RuntimeError, "Не удалось подключиться"):
                    await api.check_health()
                await api.aclose()

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
