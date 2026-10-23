"""Manager service lifecycle: token, agent thread, monitor, local API and UI."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from . import __version__
from .agent import ManagerAgent
from .pairing import PairingOutcome, pair_and_store, unpair as remove_token
from .runtime import ManagerRuntime
from .secrets import SecretError, load_token, token_fingerprint
from .settings import ManagerSettings

logger = logging.getLogger(__name__)


class ManagerService:
    """Owns all manager-side components and their threads."""

    def __init__(
        self,
        settings: ManagerSettings,
        *,
        runtime: ManagerRuntime | None = None,
        agent: ManagerAgent | None = None,
        pair_func: Callable[..., PairingOutcome] | None = None,
    ) -> None:
        self.settings = settings
        self._pair_func = pair_func or pair_and_store
        self.runtime = runtime or ManagerRuntime(settings)

        self._token: str | None = None
        self._token_error: str | None = None
        self._load_token()

        self.agent = agent or ManagerAgent(
            settings,
            self.runtime,
            token_provider=self.current_token,
            on_status=self._on_agent_status,
        )
        self._status_lock = threading.Lock()
        self._agent_status: dict[str, Any] = self.agent.status()

        try:
            self.runtime.add_listener(self._on_runtime_change)
        except AttributeError:  # pragma: no cover - duck-typed test runtimes
            pass

        self._agent_thread: threading.Thread | None = None
        self._agent_loop: asyncio.AbstractEventLoop | None = None
        self._local_server: Any = None
        self._local_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._started = False

    # ------------------------------------------------------------------
    # Token handling
    # ------------------------------------------------------------------

    def _load_token(self) -> None:
        try:
            self._token = load_token(self.settings.token_file)
        except SecretError as exc:
            self._token = None
            self._token_error = str(exc)
            logger.error("Could not load the manager token: %s", exc)

    def current_token(self) -> str | None:
        return self._token

    @property
    def paired(self) -> bool:
        return bool(self._token)

    def pair(self, code: str, *, name: str | None = None) -> PairingOutcome:
        """Pair with the server, store the token and wake the agent."""

        outcome = self._pair_func(self.settings, code, name=name)
        self._token = outcome.token
        self._token_error = None
        logger.info("Manager paired as %r", outcome.manager_name)
        self.agent.request_reconnect()
        return outcome

    def unpair(self) -> bool:
        """Forget the manager token and stop relaying."""

        existed = bool(self._token)
        try:
            existed = remove_token(self.settings) or existed
        except OSError as exc:
            logger.error("Could not remove the manager token: %s", exc)
        self._token = None
        self.agent.request_reconnect()
        return existed

    # ------------------------------------------------------------------
    # Agent
    # ------------------------------------------------------------------

    def _on_agent_status(self, status: dict[str, Any]) -> None:
        with self._status_lock:
            self._agent_status = dict(status)

    def _on_runtime_change(self, reason: str) -> None:
        self.agent.notify_state_changed()

    def _run_agent(self) -> None:
        loop = asyncio.new_event_loop()
        self._agent_loop = loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.agent.run())
        except Exception:  # pragma: no cover - defensive
            logger.exception("Manager agent loop failed")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # pragma: no cover - shutdown best effort
                pass
            loop.close()
            self._agent_loop = None

    def _start_agent_thread(self) -> None:
        if self._agent_thread is not None and self._agent_thread.is_alive():
            return
        self._agent_thread = threading.Thread(
            target=self._run_agent,
            name="yeelight-manager-agent",
            daemon=True,
        )
        self._agent_thread.start()

    def reconnect(self) -> None:
        self.agent.request_reconnect()

    # ------------------------------------------------------------------
    # Local API
    # ------------------------------------------------------------------

    def start_local_api(self) -> None:
        if not self.settings.local_api_enabled:
            return
        if self._local_thread is not None and self._local_thread.is_alive():
            return
        import uvicorn

        from .local_api import create_local_app

        app = create_local_app(self)
        config = uvicorn.Config(
            app,
            host=self.settings.local_api_host,
            port=self.settings.local_api_port,
            log_level="warning",
            access_log=False,
            server_header=False,
            proxy_headers=False,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=server.run,
            name="yeelight-manager-local-api",
            daemon=True,
        )
        self._local_server = server
        self._local_thread = thread
        thread.start()
        logger.info(
            "Local manager API: http://%s:%s",
            self.settings.local_api_host,
            self.settings.local_api_port,
        )

    def stop_local_api(self) -> None:
        server = self._local_server
        thread = self._local_thread
        self._local_server = None
        self._local_thread = None
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    # ------------------------------------------------------------------
    # Snapshot for the UI and the local API
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        lamps = self.runtime.lamp_states()
        agent = self.agent.status()
        with self._status_lock:
            self._agent_status = dict(agent)
        local_thread = self._local_thread
        return {
            "version": __version__,
            "manager_name": self.settings.manager_name,
            "server_url": self.settings.server_url,
            "paired": bool(self._token),
            "token_fingerprint": token_fingerprint(self._token),
            "token_error": self._token_error,
            "agent": agent,
            "lamps": lamps,
            "lamp_count": len(lamps),
            "local_api": {
                "enabled": bool(self.settings.local_api_enabled),
                "url": (
                    f"http://{self.settings.local_api_host}:"
                    f"{self.settings.local_api_port}"
                ),
                "running": bool(local_thread and local_thread.is_alive()),
            },
            "paths": {
                "home": str(self.settings.home),
                "state": str(self.settings.state_file),
                "bulbs": str(self.settings.bulbs_file),
                "token": str(self.settings.token_file),
            },
            "settings": {
                "poll_interval_seconds": self.settings.poll_interval_seconds,
                "discovery_timeout_seconds": self.settings.discovery_timeout_seconds,
                "command_timeout_seconds": self.settings.command_timeout_seconds,
            },
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self.runtime.start_monitor()
        self._start_agent_thread()
        self.start_local_api()

    def run(self) -> int:
        """Start everything and block until the UI closes or Ctrl+C is pressed."""

        self.start()
        try:
            if self.settings.ui_enabled:
                from .ui.main_view import run_ui

                run_ui(self)
            else:
                while not self._stop_event.wait(0.5):
                    pass
        except KeyboardInterrupt:
            logger.info("Interrupted; shutting down")
        finally:
            self.stop()
        return 0

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.agent.stop()
        except Exception:  # pragma: no cover - shutdown best effort
            logger.debug("Could not stop the agent", exc_info=True)
        self.stop_local_api()
        try:
            self.runtime.close()
        except Exception:  # pragma: no cover - shutdown best effort
            logger.debug("Could not close the runtime", exc_info=True)
        thread = self._agent_thread
        self._agent_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._started = False


__all__ = ["ManagerService"]
