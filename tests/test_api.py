import unittest

from fastapi.testclient import TestClient

from yeelight_logic import YeelightController
from yeelight_network.api import create_app


class FakeBulb:
    def turn_on(self) -> None:
        pass

    def turn_off(self) -> None:
        pass

    def get_properties(self) -> dict[str, str]:
        return {"power": "on"}

    def set_brightness(self, brightness: int) -> None:
        pass

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        pass

    def set_color_temp(self, temperature: int) -> None:
        pass


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        controller = YeelightController(
            ["192.168.1.45"], bulb_factory=lambda _address: FakeBulb()
        )
        self.client = TestClient(create_app(controller, api_token="test-token"))
        self.headers = {"X-API-Token": "test-token"}

    def test_home_serves_web_client(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Yeelight Console", response.text)
        self.assertIn('id="command-form"', response.text)

    def test_api_requires_token(self) -> None:
        response = self.client.get("/api/bulbs")
        self.assertEqual(response.status_code, 401)

    def test_command_and_bulb_listing(self) -> None:
        response = self.client.post(
            "/api/commands",
            json={"command": "on 192.168.1.45"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

        response = self.client.get("/api/bulbs", headers=self.headers)
        self.assertEqual(response.json(), {"bulbs": [{"ip": "192.168.1.45"}]})

    def test_invalid_command_returns_client_error(self) -> None:
        response = self.client.post(
            "/api/commands", json={"command": "unknown"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
