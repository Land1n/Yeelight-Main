"""Human authentication endpoints and bootstrap helpers."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..config import Settings
from ..security.tokens import (
    expires_at,
    hash_password,
    new_token,
    normalize_username,
    password_is_strong,
    token_hash,
    verify_password,
)
from ..storage import Database
from .deps import (
    SESSION_COOKIE,
    enforce_rate_limit,
    get_client_ip,
    get_context,
    require_csrf,
    require_user,
)
from .schemas import LoginRequest

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
protected_router = APIRouter(
    prefix="/api/v1/auth", tags=["auth"], dependencies=[Depends(require_csrf)]
)


def ensure_admin_user(db: Database, settings: Settings) -> dict[str, Any]:
    """Create the initial administrator from configuration.

    The environment password is used only when the database has no users.  On
    later starts the stored scrypt hash wins, so changing ``.env`` does not
    silently reset a password.
    """

    if db.count_users() > 0:
        username = normalize_username(settings.admin_username)
        user = db.get_user_by_username(username)
        if user is None:
            logger.warning(
                "Configured administrator %r does not exist; keeping existing users",
                settings.admin_username,
            )
        return user or {}

    if not settings.admin_password:
        raise RuntimeError(
            "The database has no users and YEELIGHT_SERVER_ADMIN_PASSWORD is empty. "
            "Run tools/setup.bat or set the password before the first start."
        )
    if not password_is_strong(settings.admin_password):
        raise RuntimeError(
            "YEELIGHT_SERVER_ADMIN_PASSWORD must contain at least 8 characters."
        )
    username = normalize_username(settings.admin_username) or "admin"
    user = db.create_user(username, hash_password(settings.admin_password))
    db.audit(
        actor_type="system",
        actor_id=None,
        action="user_created",
        target=user["id"],
        outcome="success",
        details={"username": username},
    )
    logger.info("Created initial administrator %r", username)
    return user


def set_password(db: Database, username: str, password: str) -> bool:
    if not password_is_strong(password):
        raise ValueError("Password must contain at least 8 characters")
    user = db.get_user_by_username(normalize_username(username))
    if user is None:
        return False
    return db.set_user_password(user["id"], hash_password(password))


@public_router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    ctx = get_context(request)
    ip = get_client_ip(request)
    username = normalize_username(payload.username)
    enforce_rate_limit(
        ctx.login_limiter,
        f"login-ip:{ip}",
        limit=10,
        window_seconds=60.0,
        message="Too many login attempts. Try again in a minute.",
    )
    enforce_rate_limit(
        ctx.login_limiter,
        f"login-user:{username}",
        limit=5,
        window_seconds=60.0,
        message="Too many login attempts. Try again in a minute.",
    )

    user = ctx.db.get_user_by_username(username)
    valid = bool(
        user and verify_password(payload.password, str(user["password_hash"]))
    )
    if not valid:
        ctx.db.audit(
            actor_type="anonymous",
            actor_id=None,
            action="login",
            target=username[:64],
            outcome="denied",
            details={"ip": ip},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = new_token(32)
    csrf_token = new_token(24)
    ttl = ctx.settings.session_ttl_seconds
    session = ctx.db.create_session(
        user_id=user["id"],
        token_hash=token_hash(token),
        csrf_token=csrf_token,
        expires_at=expires_at(ttl),
        user_agent=request.headers.get("user-agent"),
    )
    ctx.db.purge_expired_sessions()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl,
        httponly=True,
        secure=ctx.settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    ctx.db.audit(
        actor_type="user",
        actor_id=user["id"],
        action="login",
        target=user["id"],
        outcome="success",
        details={"ip": ip},
    )
    return {
        "username": user["username"],
        "csrf_token": session["csrf_token"],
        "expires_at": session["expires_at"],
    }


@protected_router.get("/me")
async def me(session: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {
        "user_id": session["user_id"],
        "username": session["username"],
        "csrf_token": session["csrf_token"],
        "expires_at": session["expires_at"],
    }


@protected_router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: dict[str, Any] = Depends(require_user),
) -> dict[str, str]:
    ctx = get_context(request)
    ctx.db.delete_session(session["id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    ctx.db.audit(
        actor_type="user",
        actor_id=session["user_id"],
        action="logout",
        target=session["user_id"],
        outcome="success",
    )
    return {"status": "logged_out"}


__all__ = [
    "ensure_admin_user",
    "login",
    "public_router",
    "protected_router",
    "set_password",
]
