"""FastAPI application factory for yeelight-server."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import auth, commands, diagnostics, managers, modes, pages, ws
from .api.auth import ensure_admin_user
from .config import Settings
from .context import AppContext
from .security.middleware import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from .services.modes import import_legacy_modes

logger = logging.getLogger(__name__)


async def _maintenance_loop(ctx: AppContext) -> None:
    while True:
        try:
            await asyncio.sleep(300)
            ctx.db.purge_expired_sessions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Database maintenance failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: AppContext = app.state.ctx
    ctx.settings.validate_for_run()
    user = ensure_admin_user(ctx.db, ctx.settings)
    ctx.db.mark_all_managers_offline()
    if not user:
        user = ctx.db.get_first_user()
    if user:
        imported = import_legacy_modes(
            ctx.db, user["id"], ctx.settings.legacy_modes_file
        )
        if imported:
            logger.info("Imported %s legacy mode(s)", imported)
    maintenance = asyncio.create_task(_maintenance_loop(ctx))
    try:
        yield
    finally:
        maintenance.cancel()
        await asyncio.gather(maintenance, return_exceptions=True)
        await ctx.modes.shutdown()
        await ctx.commands.shutdown()
        await ctx.hub.close_all()
        ctx.db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    ctx = AppContext.create(settings)
    app = FastAPI(
        title="Yeelight Server",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.ctx = ctx

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=bool(settings.tls_cert) or settings.secure_cookies,
    )
    app.add_middleware(RequestSizeLimitMiddleware)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.public_router)
    app.include_router(auth.protected_router)
    app.include_router(managers.public_router)
    app.include_router(managers.protected_router)
    app.include_router(managers.lamps_router)
    app.include_router(commands.router)
    app.include_router(modes.router)
    app.include_router(diagnostics.router)
    app.include_router(ws.router)
    app.include_router(pages.router)

    static_dir = settings.frontend_dir / "static"
    if not static_dir.is_dir():
        raise RuntimeError(f"Frontend assets are missing: {static_dir}")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


__all__ = ["create_app", "lifespan"]
