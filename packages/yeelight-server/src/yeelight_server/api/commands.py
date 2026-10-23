"""Typed command relay endpoints.

Only the closed action set from :mod:`yeelight_logic.actions` is accepted.  The
server never accepts shell-like text and never contacts a lamp directly.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from yeelight_logic import CommandError, validate_action_params
from yeelight_logic.actions import LAMP_ACTIONS

from ..services.commands import CommandServiceError
from .deps import enforce_rate_limit, get_context, require_csrf, require_user
from .schemas import CommandRequest

router = APIRouter(
    prefix="/api/v1/commands",
    tags=["commands"],
    dependencies=[Depends(require_csrf)],
)


def _validate_ip(value: Any, field: str = "ip") -> str:
    try:
        address = str(value).strip()
        parsed = ipaddress.ip_address(address)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field} address") from exc
    if parsed.version != 4:
        raise HTTPException(status_code=422, detail="Only IPv4 addresses are supported")
    return address


def _command_payload(command: dict[str, Any]) -> dict[str, Any]:
    return {
        key: command[key]
        for key in (
            "id",
            "manager_id",
            "action",
            "ip",
            "params",
            "status",
            "result",
            "error",
            "error_code",
            "created_at",
            "delivered_at",
            "completed_at",
            "timeout_seconds",
        )
    }


@router.post("", status_code=status.HTTP_200_OK)
async def create_command(
    payload: CommandRequest,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> Any:
    ctx = get_context(request)
    user_id = session["user_id"]
    enforce_rate_limit(
        ctx.command_limiter,
        f"command:{user_id}",
        limit=120,
        window_seconds=60.0,
        message="Too many commands. Slow down.",
    )

    manager = ctx.db.get_manager(payload.manager_id, user_id)
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")

    raw_params = dict(payload.params or {})
    ip = payload.ip
    if payload.action in {"add", "remove"}:
        ip = ip or raw_params.get("ip") or raw_params.get("address")
        if ip is None:
            raise HTTPException(
                status_code=422, detail=f"Action '{payload.action}' requires an IP address"
            )
        ip = _validate_ip(ip)
        raw_params["ip"] = ip
    elif payload.action in {"discover", "list"}:
        if ip is not None or raw_params:
            raise HTTPException(
                status_code=422,
                detail=f"Action '{payload.action}' does not accept an IP or parameters",
            )
    else:
        if ip is None:
            raise HTTPException(
                status_code=422, detail=f"Action '{payload.action}' requires an IP address"
            )
        ip = _validate_ip(ip)
        if ctx.db.get_lamp(payload.manager_id, ip) is None:
            raise HTTPException(
                status_code=404,
                detail="Lamp is not known to this manager. Run discovery or add it first.",
            )

    try:
        params = validate_action_params(payload.action, raw_params)
    except CommandError as exc:
        ctx.db.audit(
            actor_type="user",
            actor_id=user_id,
            action="command_rejected",
            target=payload.manager_id,
            outcome="invalid",
            details={"action": payload.action, "ip": ip},
        )
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "error_code": exc.code},
        ) from exc

    idempotency_key = payload.idempotency_key or request.headers.get(
        "Idempotency-Key"
    )
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(status_code=422, detail="Invalid Idempotency-Key")

    try:
        command = await ctx.commands.create_and_deliver(
            user_id=user_id,
            manager_id=payload.manager_id,
            action=payload.action,
            ip=ip,
            params=params,
            timeout_seconds=payload.timeout_seconds,
            idempotency_key=idempotency_key,
        )
    except CommandServiceError as exc:
        body = _command_payload(exc.command) if exc.command else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"message": exc.message, "command": body}},
        )

    if not payload.wait:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"command": _command_payload(command)},
        )
    final = await ctx.commands.wait(command["id"])
    if final["status"] == "manager_unavailable":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": {
                    "message": final.get("error") or "Manager is not available",
                    "command": _command_payload(final),
                }
            },
        )
    return {"command": _command_payload(final)}


@router.get("")
async def list_commands(
    request: Request,
    manager_id: str | None = None,
    limit: int = 50,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    limit = max(1, min(int(limit), 200))
    commands = ctx.db.list_commands(
        session["user_id"], manager_id=manager_id, limit=limit
    )
    return {"commands": [_command_payload(command) for command in commands]}


@router.get("/{command_id}")
async def get_command(
    command_id: str,
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    ctx = get_context(request)
    command = ctx.db.get_command_for_user(command_id, session["user_id"])
    if command is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"command": _command_payload(command)}


__all__ = ["router"]
