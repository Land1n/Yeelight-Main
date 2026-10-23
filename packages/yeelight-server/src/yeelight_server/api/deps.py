"""FastAPI dependencies for session authentication and CSRF protection."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from ..context import AppContext
from ..security.tokens import constant_time_equals, token_hash

SESSION_COOKIE = "yl_session"


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def get_client_ip(request: Request) -> str:
    """Return the direct peer address.

    Forwarded headers are intentionally ignored: this application does not
    assume a trusted reverse proxy, so trusting them would let a remote client
    spoof loopback or rate-limit identities.
    """

    if request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def get_optional_session(request: Request) -> dict[str, Any] | None:
    ctx: AppContext = request.app.state.ctx
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return ctx.db.get_session(token_hash(raw))


def require_user(
    session: dict[str, Any] | None = Depends(get_optional_session),
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Session"},
        )
    return session


def require_csrf(
    request: Request,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return session
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not constant_time_equals(supplied, session["csrf_token"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )
    return session


def enforce_rate_limit(
    limiter,
    key: str,
    *,
    limit: int,
    window_seconds: float,
    message: str = "Too many requests. Try again later.",
) -> None:
    result = limiter.hit(key, limit=limit, window_seconds=window_seconds)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=message,
            headers={"Retry-After": str(result.retry_after)},
        )


__all__ = [
    "SESSION_COOKIE",
    "enforce_rate_limit",
    "get_client_ip",
    "get_context",
    "get_optional_session",
    "require_csrf",
    "require_user",
]
