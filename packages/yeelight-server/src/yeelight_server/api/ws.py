"""Manager WebSocket endpoint (server side of the relay protocol)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import __version__
from ..security.tokens import token_hash

logger = logging.getLogger(__name__)

router = APIRouter(tags=["manager-relay"])

MAX_MESSAGE_BYTES = 512 * 1024
MAX_LAMPS_PER_REPORT = 512


def _bearer_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _normalize_lamps(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)][:MAX_LAMPS_PER_REPORT]


@router.websocket("/api/v1/managers/ws")
async def manager_socket(websocket: WebSocket) -> None:
    token = _bearer_token(websocket)
    if not token:
        await websocket.accept()
        await websocket.close(code=4401, reason="Missing manager token")
        return

    ctx = websocket.app.state.ctx
    manager = ctx.db.get_manager_by_token_hash(token_hash(token))
    if manager is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="Invalid manager token")
        return

    manager_id = manager["id"]
    await websocket.accept()
    await ctx.hub.connect(manager_id, websocket)
    ctx.db.set_manager_online(manager_id, True)
    ctx.db.audit(
        actor_type="manager",
        actor_id=manager_id,
        action="manager_connected",
        target=manager_id,
        outcome="success",
    )
    await ctx.hub.send(
        manager_id,
        {
            "type": "hello",
            "protocol_version": 1,
            "server_version": __version__,
            "manager_id": manager_id,
            "heartbeat_interval_seconds": ctx.settings.heartbeat_interval_seconds,
        },
    )

    try:
        while True:
            text = await websocket.receive_text()
            if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
                logger.warning("Ignoring oversized message from manager %s", manager_id)
                continue
            try:
                message = json.loads(text)
            except ValueError:
                logger.warning("Ignoring malformed JSON from manager %s", manager_id)
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")

            if kind in {"hello", "lamps"}:
                version = message.get("version")
                if isinstance(version, str) and version.strip():
                    ctx.db.touch_manager(manager_id, version.strip()[:40])
                else:
                    ctx.db.touch_manager(manager_id)
                lamps = _normalize_lamps(message.get("lamps"))
                ctx.db.replace_lamps(manager_id, lamps)
                if kind == "hello":
                    ctx.db.audit(
                        actor_type="manager",
                        actor_id=manager_id,
                        action="manager_hello",
                        target=manager_id,
                        outcome="success",
                        details={
                            "version": (version or "")[:40] if isinstance(version, str) else "",
                            "lamps": len(lamps),
                        },
                    )
            elif kind == "heartbeat":
                ctx.db.touch_manager(manager_id)
            elif kind == "command_result":
                command_id = message.get("command_id")
                if not isinstance(command_id, str) or not command_id:
                    continue
                command = ctx.db.get_command(command_id)
                if command is None or command["manager_id"] != manager_id:
                    logger.warning(
                        "Ignoring result for unknown command from manager %s", manager_id
                    )
                    continue
                ctx.commands.complete_from_manager(command_id, message)
            else:
                logger.debug("Ignoring unknown message type %r", kind)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Manager WebSocket failed")
    finally:
        ctx.hub.disconnect(manager_id, websocket)
        if not ctx.hub.is_online(manager_id):
            ctx.db.set_manager_online(manager_id, False)
            ctx.commands.manager_disconnected(manager_id)
            ctx.db.audit(
                actor_type="manager",
                actor_id=manager_id,
                action="manager_disconnected",
                target=manager_id,
                outcome="success",
            )


__all__ = ["router"]
