"""Command relay service: server side of the remote protocol."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from ..storage import Database
from .hub import ManagerHub

logger = logging.getLogger(__name__)


class CommandServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, command: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.command = command


@dataclass
class _Pending:
    event: asyncio.Event
    timeout_task: asyncio.Task[None] | None = None


class CommandService:
    """Store commands, deliver them to managers and collect typed results.

    States distinguish "queued", "delivered", "completed", "failed",
    "timed_out" and "manager_unavailable" so the web UI does not claim that a
    command ran when the manager was offline.
    """

    def __init__(
        self,
        db: Database,
        hub: ManagerHub,
        *,
        default_timeout: float = 15.0,
        max_wait: float = 30.0,
    ) -> None:
        self.db = db
        self.hub = hub
        self.default_timeout = default_timeout
        self.max_wait = max_wait
        self._pending: dict[str, _Pending] = {}

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def create_and_deliver(
        self,
        *,
        user_id: str,
        manager_id: str,
        action: str,
        ip: str | None,
        params: dict[str, Any],
        timeout_seconds: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        timeout = float(timeout_seconds or self.default_timeout)
        timeout = max(1.0, min(timeout, self.default_timeout))

        if idempotency_key:
            existing = self.db.get_command_by_idempotency(
                manager_id, idempotency_key
            )
            if existing is not None:
                return existing

        command = self.db.create_command(
            user_id=user_id,
            manager_id=manager_id,
            action=action,
            ip=ip,
            params=params,
            timeout_seconds=timeout,
            idempotency_key=idempotency_key,
        )
        self._pending[command["id"]] = _Pending(
            event=self.hub.create_event(command["id"])
        )

        if not self.hub.is_online(manager_id):
            command = self.db.finish_command(
                command["id"],
                "manager_unavailable",
                error="Manager is not connected",
                error_code="manager_unavailable",
            )
            self._resolve(command["id"])
            self.db.audit(
                actor_type="user",
                actor_id=user_id,
                action="command",
                target=manager_id,
                outcome="manager_unavailable",
                details={"action": action, "ip": ip},
            )
            raise CommandServiceError(
                "Manager is not connected",
                status_code=503,
                command=command,
            )

        message = {
            "type": "command",
            "command_id": command["id"],
            "action": action,
            "ip": ip,
            "params": params,
            "timeout_seconds": timeout,
        }
        delivered = await self.hub.send(manager_id, message)
        if not delivered:
            command = self.db.finish_command(
                command["id"],
                "manager_unavailable",
                error="Manager connection was lost before delivery",
                error_code="manager_unavailable",
            )
            self._resolve(command["id"])
            raise CommandServiceError(
                "Manager connection was lost before delivery",
                status_code=503,
                command=command,
            )

        command = self.db.mark_command_delivered(command["id"]) or command
        pending = self._pending.get(command["id"])
        if pending is not None:
            pending.timeout_task = asyncio.create_task(
                self._expire(command["id"], timeout)
            )
        self.db.audit(
            actor_type="user",
            actor_id=user_id,
            action="command",
            target=manager_id,
            outcome="delivered",
            details={"command_id": command["id"], "action": action, "ip": ip},
        )
        return command

    async def _expire(self, command_id: str, timeout: float) -> None:
        try:
            await asyncio.sleep(timeout)
            current = self.db.get_command(command_id)
            if current is None or current["status"] not in {"pending", "delivered"}:
                return
            self.db.finish_command(
                command_id,
                "timed_out",
                error="Manager did not return a result in time",
                error_code="timeout",
            )
            self._resolve(command_id)
            self.db.audit(
                actor_type="system",
                actor_id=None,
                action="command_timeout",
                target=current["manager_id"],
                outcome="timed_out",
                details={"command_id": command_id, "action": current["action"]},
            )
        finally:
            pending = self._pending.get(command_id)
            if pending is not None and pending.timeout_task is asyncio.current_task():
                self._pending.pop(command_id, None)

    async def wait(
        self, command_id: str, timeout: float | None = None
    ) -> dict[str, Any]:
        current = self.db.get_command(command_id)
        if current is None:
            raise CommandServiceError("Command not found", status_code=404)
        if current["status"] not in {"pending", "delivered"}:
            return current
        pending = self._pending.get(command_id)
        if pending is None:
            # The process restarted; never report a stale command as running.
            return self.db.finish_command(
                command_id,
                "manager_unavailable",
                error="Command state was lost after a server restart",
                error_code="manager_unavailable",
            ) or current
        wait_seconds = min(
            float(timeout if timeout is not None else self.default_timeout),
            self.max_wait,
        )
        try:
            await asyncio.wait_for(pending.event.wait(), timeout=max(0.0, wait_seconds))
        except asyncio.TimeoutError:
            current = self.db.get_command(command_id)
            if current is not None and current["status"] in {"pending", "delivered"}:
                current = self.db.finish_command(
                    command_id,
                    "timed_out",
                    error="Timed out while waiting for the manager result",
                    error_code="timeout",
                ) or current
                self._resolve(command_id)
        return self.db.get_command(command_id) or current

    # ------------------------------------------------------------------
    # Manager results and disconnects
    # ------------------------------------------------------------------

    def complete_from_manager(
        self, command_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        command = self.db.get_command(command_id)
        if command is None:
            return None
        if command["status"] not in {"pending", "delivered"}:
            return command
        ok = bool(payload.get("ok"))
        if ok:
            result = payload.get("result")
            updated = self.db.finish_command(
                command_id,
                "completed",
                result=result if isinstance(result, dict) else {"value": result},
            )
        else:
            error = str(payload.get("error") or "Manager reported a failure")[:500]
            error_code = str(payload.get("error_code") or "device_error")[:80]
            updated = self.db.finish_command(
                command_id,
                "failed",
                error=error,
                error_code=error_code,
            )
        self._resolve(command_id)
        self.db.audit(
            actor_type="manager",
            actor_id=command["manager_id"],
            action="command_result",
            target=command["manager_id"],
            outcome=(updated or command)["status"],
            details={"command_id": command_id, "action": command["action"]},
        )
        return updated or command

    def manager_disconnected(self, manager_id: str) -> None:
        ids = self.db.fail_inflight_commands(
            manager_id,
            error="Manager disconnected before returning a result",
            error_code="manager_unavailable",
        )
        for command_id in ids:
            self._resolve(command_id)
        if ids:
            self.db.audit(
                actor_type="system",
                actor_id=None,
                action="manager_disconnected",
                target=manager_id,
                outcome="manager_unavailable",
                details={"failed_commands": len(ids)},
            )

    def _resolve(self, command_id: str) -> None:
        pending = self._pending.pop(command_id, None)
        if pending is not None and pending.timeout_task is not None:
            pending.timeout_task.cancel()
        self.hub.resolve(command_id)

    async def shutdown(self) -> None:
        for command_id, pending in list(self._pending.items()):
            if pending.timeout_task is not None:
                pending.timeout_task.cancel()
            self.hub.resolve(command_id)
        self._pending.clear()
        await asyncio.sleep(0)
