"""Read-only diagnostics and audit endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import __version__
from .deps import get_context, require_csrf, require_user

router = APIRouter(
    prefix="/api/v1",
    tags=["diagnostics"],
    dependencies=[Depends(require_csrf)],
)


def _safe_settings(ctx) -> dict[str, Any]:
    return {
        "host": ctx.settings.host,
        "port": ctx.settings.port,
        "tls": bool(ctx.settings.tls_cert),
        "secure_cookies": ctx.settings.secure_cookies,
        "session_ttl_seconds": ctx.settings.session_ttl_seconds,
        "command_timeout_seconds": ctx.settings.command_timeout_seconds,
        "max_command_wait_seconds": ctx.settings.max_command_wait_seconds,
        "heartbeat_interval_seconds": ctx.settings.heartbeat_interval_seconds,
        "manager_offline_grace_seconds": ctx.settings.manager_offline_grace_seconds,
        "features": {
            "manager_relay": True,
            "direct_lamp_access": False,
            "wifi_provisioning": False,
            "lan_control_provisioning": False,
        },
    }


@router.get("/settings")
async def get_settings(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"settings": _safe_settings(get_context(request))}


@router.get("/diagnostics")
async def diagnostics(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    user_id = session["user_id"]
    managers = ctx.db.get_managers(user_id)
    lamps = sum(len(ctx.db.get_lamps(manager["id"])) for manager in managers)
    modes = ctx.modes.list_modes(user_id)
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": round(time.time() - ctx.started_at, 1),
        "database": "sqlite",
        "managers": {
            "total": len(managers),
            "online": sum(1 for manager in managers if ctx.hub.is_online(manager["id"])),
            "connected_ids": sorted(ctx.hub.online_managers()),
        },
        "lamps": lamps,
        "modes": {
            "total": len(modes),
            "running": sum(1 for mode in modes if mode["running"]),
        },
        "commands": ctx.db.command_stats(user_id),
        "settings": _safe_settings(ctx),
        "recent_audit": ctx.db.list_audit(user_id, limit=20),
    }


@router.get("/audit")
async def list_audit(
    request: Request,
    limit: int = 100,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    limit = max(1, min(int(limit), 500))
    return {"events": ctx.db.list_audit(session["user_id"], limit=limit)}


__all__ = ["router"]
