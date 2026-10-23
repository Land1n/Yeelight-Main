"""Cyclic mode CRUD and runtime endpoints."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .deps import get_context, require_csrf, require_user
from .schemas import ModeRequest, ModeStartRequest

router = APIRouter(
    prefix="/api/v1/modes",
    tags=["modes"],
    dependencies=[Depends(require_csrf)],
)


def _mode_exists_or_404(ctx, mode_id: str, user_id: str) -> dict[str, Any]:
    mode = ctx.modes.get_mode(mode_id, user_id)
    if mode is None:
        raise HTTPException(status_code=404, detail="Mode not found")
    return mode


@router.get("")
async def list_modes(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    return {"modes": ctx.modes.list_modes(session["user_id"])}


@router.get("/{mode_id}")
async def get_mode(
    mode_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    return {"mode": _mode_exists_or_404(ctx, mode_id, session["user_id"])}


@router.post("")
async def put_mode(
    payload: ModeRequest,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    try:
        mode = ctx.modes.put_mode(
            session["user_id"],
            name=payload.name,
            steps=[step.model_dump() for step in payload.steps],
            delay_seconds=payload.delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="mode_saved",
        target=mode["id"],
        outcome="success",
        details={"name": mode["name"], "steps": len(mode["steps"])},
    )
    return {"mode": mode}


@router.delete("/{mode_id}")
async def delete_mode(
    mode_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    mode = _mode_exists_or_404(ctx, mode_id, session["user_id"])
    try:
        ctx.modes.delete_mode(mode_id, session["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mode not found") from exc
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="mode_deleted",
        target=mode_id,
        outcome="success",
        details={"name": mode["name"]},
    )
    return {"status": "deleted", "mode_id": mode_id}


@router.post("/{mode_id}/start")
async def start_mode(
    mode_id: str,
    payload: ModeStartRequest,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    mode = _mode_exists_or_404(ctx, mode_id, session["user_id"])
    manager = ctx.db.get_manager(payload.manager_id, session["user_id"])
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")
    try:
        address = str(ipaddress.ip_address(payload.ip))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid IPv4 address") from exc
    try:
        mode = await ctx.modes.start(
            mode=mode, manager_id=payload.manager_id, ip=address
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="mode_started",
        target=mode_id,
        outcome="success",
        details={"manager_id": payload.manager_id, "ip": address},
    )
    return {"mode": mode, "ip": address}


@router.post("/{mode_id}/stop")
async def stop_mode(
    mode_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    mode = _mode_exists_or_404(ctx, mode_id, session["user_id"])
    await ctx.modes.stop(mode_id)
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="mode_stopped",
        target=mode_id,
        outcome="success",
        details={"name": mode["name"]},
    )
    return {"status": "stopped", "mode_id": mode_id}


__all__ = ["router"]
