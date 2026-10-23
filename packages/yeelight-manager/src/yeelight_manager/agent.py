"""Outbound WebSocket agent between the manager and the relay server.

The manager only ever makes outbound connections.  The server sends typed
commands; the agent executes them through :class:`ManagerRuntime` and returns a
typed result.  No arbitrary command strings cross the wire.

Protocol (version 1)::

    server -> manager: hello, command
    manager -> server: hello, heartbeat, lamps, command_result
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from . import __version__
from .runtime import ManagerRuntime
from .settings import ManagerSettings, websocket_url

logger = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 512 * 1024
MAX_CACHED_RESULTS = 256
HELLO_TIMEOUT_SECONDS = 15.0
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 60.0
UNPAIRED_RETRY_SECONDS = 5.0

ConnectFactory = Callable[..., Any]


def _json(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def _ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    if verify_tls:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _default_connect(
    url: str, *, headers: dict[str, str], verify_tls: bool
) -> Any:
    kwargs: dict[str, Any] = {
        "additional_headers": headers,
        "open_timeout": HELLO_TIMEOUT_SECONDS,
        "close_timeout": 5.0,
        "max_size": MAX_MESSAGE_BYTES,
        "ping_interval": None,
        "user_agent_header": f"yeelight-manager/{__version__}",
        # Desktop tools should connect directly; environment proxies are for
        # browsers and would break LAN relays.
        "proxy": None,
    }
    if url.startswith("wss://") and not verify_tls:
        kwargs["ssl"] = _ssl_context(False)
    return websockets.connect(url, **kwargs)


class ManagerAgent:
    """Reconnecting WebSocket agent.

    ``run()`` is a coroutine intended to be executed on a dedicated event loop
    thread owned by :class:`~yeelight_manager.service.ManagerService`.
    """

    def __init__(
        self,
        settings: ManagerSettings,
        runtime: ManagerRuntime,
        *,
        token_provider: Callable[[], str | None],
        version: str = __version__,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        connect_factory: ConnectFactory | None = None,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self._token_provider = token_provider
        self._version = version
        self._on_status = on_status or (lambda status: None)
        self._connect = connect_factory or _default_connect

        self._status_lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "stopped",
            "connected": False,
            "error": None,
            "manager_id": None,
            "server_version": None,
            "heartbeat_interval_seconds": None,
            "last_connected_at": None,
            "last_message_at": None,
        }
        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._state_event: asyncio.Event | None = None
        self._ws: Any = None
        self._retry_delay = RECONNECT_MIN_SECONDS
        self._results: OrderedDict[str, dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._status_lock:
            return dict(self._status)

    def _set_status(self, state: str | None = None, **fields: Any) -> None:
        with self._status_lock:
            if state is not None:
                self._status["state"] = state
            self._status.update(fields)
            snapshot = dict(self._status)
        try:
            self._on_status(snapshot)
        except Exception:  # pragma: no cover - status callbacks are isolated
            logger.exception("Manager status callback failed")

    # ------------------------------------------------------------------
    # Thread-safe controls
    # ------------------------------------------------------------------

    def request_reconnect(self) -> None:
        """Wake a waiting agent so it retries immediately (for example after pairing)."""

        loop = self._loop
        wake = self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:  # pragma: no cover - loop closed while shutting down
            pass

    def notify_state_changed(self) -> None:
        """Ask the agent to push an updated lamp inventory (called from threads)."""

        loop = self._loop
        event = self._state_event
        if loop is None or event is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:  # pragma: no cover - loop closed while shutting down
            pass

    def stop(self) -> None:
        """Request a graceful shutdown from any thread."""

        self._stopping = True
        self.request_reconnect()
        loop = self._loop
        ws = self._ws
        if loop is not None and ws is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(ws.close(code=1000), loop)
            except RuntimeError:  # pragma: no cover
                pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._state_event = asyncio.Event()
        try:
            while not self._stopping:
                token = self._token_provider()
                if not token:
                    self._set_status(
                        "unpaired",
                        connected=False,
                        error="Pair this manager with the server to start relaying commands.",
                    )
                    await self._sleep(UNPAIRED_RETRY_SECONDS)
                    continue
                try:
                    await self._session(token)
                    self._retry_delay = RECONNECT_MIN_SECONDS
                    self._set_status(
                        "disconnected",
                        connected=False,
                        error="Connection closed; reconnecting.",
                    )
                except ConnectionClosed as exc:
                    code = getattr(exc, "code", None)
                    reason = (getattr(exc, "reason", "") or "").strip()
                    if code == 4401:
                        self._set_status(
                            "unauthorized",
                            connected=False,
                            error="The manager token was rejected; pair again.",
                        )
                        return
                    if code == 4003:
                        self._set_status(
                            "removed",
                            connected=False,
                            error="This manager was removed on the server; pair again.",
                        )
                        return
                    detail = f"Connection closed ({code})"
                    if reason:
                        detail = f"{detail}: {reason}"
                    self._set_status(
                        "disconnected", connected=False, error=detail[:300]
                    )
                except InvalidStatus as exc:
                    status_code = exc.response.status_code
                    if status_code in {401, 403}:
                        self._set_status(
                            "unauthorized",
                            connected=False,
                            error="The manager token was rejected; pair again.",
                        )
                        return
                    self._set_status(
                        "error",
                        connected=False,
                        error=f"Server rejected the WebSocket (HTTP {status_code}).",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._set_status(
                        "error", connected=False, error=str(exc)[:300] or exc.__class__.__name__
                    )
                if self._stopping:
                    break
                delay = self._retry_delay
                self._retry_delay = min(
                    RECONNECT_MAX_SECONDS, self._retry_delay * 2
                )
                await self._sleep(delay)
        finally:
            self._ws = None
            self._loop = None
            self._wake = None
            self._state_event = None
            self._set_status("stopped", connected=False)

    async def _sleep(self, seconds: float) -> None:
        assert self._wake is not None
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(0.0, seconds))
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake.clear()

    # ------------------------------------------------------------------
    # One connection
    # ------------------------------------------------------------------

    async def _session(self, token: str) -> None:
        url = websocket_url(self.settings.server_url, self.settings.websocket_path)
        headers = {"Authorization": f"Bearer {token}"}
        self._set_status("connecting", connected=False, error=None)
        connect = self._connect(
            url,
            headers=headers,
            verify_tls=self.settings.verify_tls,
        )
        async with connect as ws:
            self._ws = ws
            try:
                hello = await asyncio.wait_for(
                    self._read_hello(ws), timeout=HELLO_TIMEOUT_SECONDS
                )
                try:
                    interval = float(
                        hello.get("heartbeat_interval_seconds") or 20.0
                    )
                except (TypeError, ValueError):
                    interval = 20.0
                interval = max(5.0, min(interval, 120.0))
                self._retry_delay = RECONNECT_MIN_SECONDS
                self._set_status(
                    "connected",
                    connected=True,
                    error=None,
                    manager_id=hello.get("manager_id"),
                    server_version=hello.get("server_version"),
                    heartbeat_interval_seconds=interval,
                    last_connected_at=time.time(),
                )
                await ws.send(
                    _json(
                        {
                            "type": "hello",
                            "version": self._version,
                            "lamps": self.runtime.lamp_reports(),
                        }
                    )
                )
                assert self._state_event is not None
                receiver = asyncio.create_task(self._receive_loop(ws))
                heartbeat = asyncio.create_task(
                    self._heartbeat_loop(ws, interval)
                )
                inventory = asyncio.create_task(self._inventory_loop(ws))
                try:
                    await receiver
                finally:
                    for task in (heartbeat, inventory):
                        task.cancel()
                    await asyncio.gather(
                        heartbeat, inventory, return_exceptions=True
                    )
            finally:
                self._ws = None
                if not self._stopping:
                    self._set_status(
                        "disconnected",
                        connected=False,
                        error="Connection closed.",
                    )

    async def _read_hello(self, ws: Any) -> dict[str, Any]:
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                continue
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "hello":
                return message

    async def _heartbeat_loop(self, ws: Any, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await ws.send(_json({"type": "heartbeat"}))

    async def _inventory_loop(self, ws: Any) -> None:
        assert self._state_event is not None
        while True:
            await self._state_event.wait()
            self._state_event.clear()
            await ws.send(
                _json(
                    {
                        "type": "lamps",
                        "version": self._version,
                        "lamps": self.runtime.lamp_reports(),
                    }
                )
            )

    async def _receive_loop(self, ws: Any) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                logger.warning("Ignoring oversized server message")
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                logger.warning("Ignoring malformed server message")
                continue
            if not isinstance(message, dict):
                continue
            self._set_status(last_message_at=time.time())
            if message.get("type") == "command":
                await self._handle_command(ws, message)

    async def _handle_command(self, ws: Any, message: dict[str, Any]) -> None:
        command_id = message.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            return
        cached = self._results.get(command_id)
        if cached is not None:
            self._results.move_to_end(command_id)
            await ws.send(_json(cached))
            return

        action = message.get("action")
        ip = message.get("ip")
        params = message.get("params")
        result = await asyncio.to_thread(
            self.runtime.run_action,
            action if isinstance(action, str) else "",
            ip if isinstance(ip, str) else None,
            params if isinstance(params, dict) else {},
        )
        payload: dict[str, Any] = {
            "type": "command_result",
            "command_id": command_id,
            "ok": bool(result.ok),
        }
        if result.ok:
            payload["result"] = (
                dict(result.data) if result.data else {"message": result.message}
            )
        else:
            payload["error"] = result.message[:500]
            payload["error_code"] = (result.error_code or "device_error")[:80]

        self._results[command_id] = payload
        while len(self._results) > MAX_CACHED_RESULTS:
            self._results.popitem(last=False)
        await ws.send(_json(payload))

    # ------------------------------------------------------------------
    # Test/diagnostic helpers
    # ------------------------------------------------------------------

    def reset_result_cache(self) -> None:
        self._results.clear()


def agent_status_text(status: dict[str, Any]) -> str:
    """Human-readable Russian status used by the desktop UI and CLI."""

    labels = {
        "stopped": "Остановлен",
        "unpaired": "Не привязан",
        "connecting": "Подключение…",
        "connected": "Подключён",
        "disconnected": "Переподключение…",
        "unauthorized": "Токен отклонён",
        "removed": "Удалён на сервере",
        "error": "Ошибка",
    }
    return labels.get(str(status.get("state")), str(status.get("state") or "Неизвестно"))


__all__ = [
    "MAX_MESSAGE_BYTES",
    "ManagerAgent",
    "agent_status_text",
]
