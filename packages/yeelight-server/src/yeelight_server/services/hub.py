"""Live manager WebSocket connections and pending command notifications."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ManagerHub:
    """Track manager WebSocket connections on the server event loop."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._events: dict[str, asyncio.Event] = {}

    def is_online(self, manager_id: str) -> bool:
        return manager_id in self._connections

    def online_managers(self) -> set[str]:
        return set(self._connections)

    async def connect(self, manager_id: str, websocket: WebSocket) -> None:
        previous = self._connections.get(manager_id)
        self._connections[manager_id] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="Replaced by a new connection")
            except Exception:
                logger.debug("Could not close previous manager socket", exc_info=True)

    def disconnect(self, manager_id: str, websocket: WebSocket) -> None:
        if self._connections.get(manager_id) is websocket:
            self._connections.pop(manager_id, None)

    async def close(self, manager_id: str) -> None:
        websocket = self._connections.pop(manager_id, None)
        if websocket is not None:
            try:
                await websocket.close(code=4003, reason="Manager was removed")
            except Exception:
                logger.debug("Could not close manager socket", exc_info=True)

    async def close_all(self) -> None:
        for manager_id in list(self._connections):
            await self.close(manager_id)

    async def send(self, manager_id: str, message: dict[str, Any]) -> bool:
        websocket = self._connections.get(manager_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            logger.info("Manager %s is not reachable over WebSocket", manager_id)
            self._connections.pop(manager_id, None)
            return False

    # ------------------------------------------------------------------
    # Command completion events
    # ------------------------------------------------------------------

    def create_event(self, command_id: str) -> asyncio.Event:
        event = self._events.get(command_id)
        if event is None:
            event = asyncio.Event()
            self._events[command_id] = event
        return event

    def resolve(self, command_id: str) -> None:
        event = self._events.pop(command_id, None)
        if event is not None:
            event.set()

    def event_for(self, command_id: str) -> asyncio.Event | None:
        return self._events.get(command_id)
