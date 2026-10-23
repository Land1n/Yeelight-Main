"""Manager pairing, inventory and lamp endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..security.tokens import mask_token, new_manager_token, new_pairing_code, token_hash
from .deps import (
    enforce_rate_limit,
    get_client_ip,
    get_context,
    require_csrf,
    require_user,
)
from .schemas import ManagerPairRequest, PairingCodeRequest

PAIRING_CODE_TTL_SECONDS = 10 * 60.0
PAIRING_CODE_LENGTH = 10

public_router = APIRouter(prefix="/api/v1/managers", tags=["managers"])
protected_router = APIRouter(
    prefix="/api/v1/managers", tags=["managers"], dependencies=[Depends(require_csrf)]
)
lamps_router = APIRouter(
    prefix="/api/v1/lamps", tags=["lamps"], dependencies=[Depends(require_csrf)]
)


def _normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _validate_manager_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Manager name is required")
    if len(name) > 60:
        raise HTTPException(
            status_code=422, detail="Manager name must be at most 60 characters"
        )
    if any(ord(ch) < 32 for ch in name):
        raise HTTPException(
            status_code=422, detail="Manager name contains control characters"
        )
    return name


@protected_router.post("/pairing-codes", status_code=status.HTTP_201_CREATED)
async def create_pairing_code(
    payload: PairingCodeRequest,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    code = new_pairing_code(PAIRING_CODE_LENGTH)
    record = ctx.db.create_pairing_code(
        session["user_id"], token_hash(code), PAIRING_CODE_TTL_SECONDS
    )
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="pairing_code_created",
        target=None,
        outcome="success",
        details={"name": payload.name, "expires_at": record["expires_at"]},
    )
    return {
        "code": code,
        "expires_at": record["expires_at"],
        "ttl_seconds": int(PAIRING_CODE_TTL_SECONDS),
        "manager_name_hint": payload.name,
    }


@public_router.post("/pair")
async def pair_manager(
    payload: ManagerPairRequest,
    request: Request,
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    ip = get_client_ip(request)
    enforce_rate_limit(
        ctx.pairing_limiter,
        f"pair:{ip}",
        limit=15,
        window_seconds=60.0,
        message="Too many pairing attempts. Try again later.",
    )
    name = _validate_manager_name(payload.name)
    code = _normalize_code(payload.code)
    if not code:
        raise HTTPException(status_code=422, detail="Pairing code is required")

    token = new_manager_token()
    try:
        manager = ctx.db.consume_pairing_code(
            code_hash=token_hash(code),
            manager_name=name,
            manager_token_hash=token_hash(token),
            version=(payload.version or "")[:40] or None,
        )
    except ValueError as exc:
        ctx.db.audit(
            actor_type="anonymous",
            actor_id=None,
            action="manager_pair",
            target=name,
            outcome="conflict",
            details={"ip": ip},
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if manager is None:
        ctx.db.audit(
            actor_type="anonymous",
            actor_id=None,
            action="manager_pair",
            target=name,
            outcome="denied",
            details={"ip": ip},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pairing code is invalid or expired",
        )

    ctx.db.audit(
        actor_type="user",
        actor_id=manager["user_id"],
        action="manager_paired",
        target=manager["id"],
        outcome="success",
        details={"name": manager["name"], "token_fingerprint": mask_token(token)},
    )
    return {
        "manager": manager,
        "token": token,
        "ws_path": ctx.settings.websocket_path,
        "heartbeat_interval_seconds": ctx.settings.heartbeat_interval_seconds,
    }


@protected_router.get("")
async def list_managers(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    managers = ctx.db.get_managers(session["user_id"])
    for manager in managers:
        manager["online"] = ctx.hub.is_online(manager["id"])
    return {"managers": managers}


@protected_router.delete("/{manager_id}")
async def delete_manager(
    manager_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    manager = ctx.db.get_manager(manager_id, session["user_id"])
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")
    await ctx.hub.close(manager_id)
    if not ctx.db.delete_manager(manager_id, session["user_id"]):
        raise HTTPException(status_code=404, detail="Manager not found")
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="manager_deleted",
        target=manager_id,
        outcome="success",
        details={"name": manager["name"]},
    )
    return {"status": "deleted", "manager_id": manager_id}


@protected_router.get("/{manager_id}/lamps")
async def list_manager_lamps(
    manager_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    manager = ctx.db.get_manager(manager_id, session["user_id"])
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")
    return {
        "manager": {**manager, "online": ctx.hub.is_online(manager_id)},
        "lamps": ctx.db.get_lamps(manager_id),
    }


@lamps_router.get("")
async def list_all_lamps(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    result: list[dict[str, Any]] = []
    managers = ctx.db.get_managers(session["user_id"])
    for manager in managers:
        online = ctx.hub.is_online(manager["id"])
        for lamp in ctx.db.get_lamps(manager["id"]):
            result.append(
                {
                    **lamp,
                    "manager_name": manager["name"],
                    "manager_online": online,
                }
            )
    result.sort(key=lambda item: (item["manager_name"].lower(), item["ip"]))
    return {"lamps": result, "count": len(result)}


__all__ = [
    "PAIRING_CODE_TTL_SECONDS",
    "lamps_router",
    "protected_router",
    "public_router",
]
