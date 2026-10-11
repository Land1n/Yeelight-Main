import asyncio
import unittest
from unittest.mock import patch

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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, *args, **kwargs):
        self.request_args = (args, kwargs)
        return self.response


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

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
