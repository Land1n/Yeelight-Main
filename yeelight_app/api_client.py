from __future__ import annotations

import re
from typing import Any

import httpx


class YeelightApiClient:
    """Фасад для HTTP API сервера Yeelight."""

    def __init__(self, server_url: str, api_token: str = "") -> None:
        self._client: httpx.AsyncClient | None = None
        self.configure(server_url, api_token)

    def configure(self, server_url: str, api_token: str = "") -> None:
        self.server_url = server_url.strip().rstrip("/")
        self.api_token = api_token.strip()

    async def check_health(self) -> dict[str, Any]:
        return await self._request("/api/health")

    async def list_bulbs(self) -> list[dict[str, Any]]:
        response = await self._request("/api/bulbs")
        bulbs = response.get("bulbs")
        if not isinstance(bulbs, list) or any(
            not isinstance(bulb, dict) or not isinstance(bulb.get("ip"), str)
            for bulb in bulbs
        ):
            raise RuntimeError("Сервер вернул некорректный список ламп")
        return bulbs

    async def execute(self, command: str) -> dict[str, Any]:
        response = await self._request("/api/commands", command=command)
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Сервер вернул некорректный результат команды")
        return result

    async def _request(
        self,
        path: str,
        *,
        command: str | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"https?://[^/]+", self.server_url, re.IGNORECASE):
            raise ValueError("Введите адрес сервера, например http://192.168.1.10:8000")

        try:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(35, connect=5)
                )
            response = await self._client.request(
                "POST" if command is not None else "GET",
                f"{self.server_url}{path}",
                headers={"X-API-Token": self.api_token},
                json={"command": command} if command is not None else None,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"Не удалось подключиться к серверу: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Сервер вернул некорректный ответ (HTTP {response.status_code})"
            ) from exc
        if not isinstance(body, dict):
            raise RuntimeError(
                f"Сервер вернул некорректный ответ (HTTP {response.status_code})"
            )
        if not response.is_success:
            raise RuntimeError(body.get("detail", f"Ошибка HTTP {response.status_code}"))
        return body

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()
