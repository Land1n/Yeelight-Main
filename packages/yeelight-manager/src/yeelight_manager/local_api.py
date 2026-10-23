"""Loopback-only HTTP API for the manager.

The desktop UI talks to :class:`ManagerService` directly.  This API exists for
local scripts and diagnostics.  It is bound to loopback by the service, rejects
non-local clients and cross-origin browser requests, and requires an explicit
header on every state-changing request.  Wi-Fi and LAN Control endpoints
additionally require ``confirm: true`` in the JSON body.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from yeelight_logic import YeelightLogicError

from . import __version__
from .pairing import PairingError

logger = logging.getLogger(__name__)

LOCAL_API_HEADER = "X-Yeelight-Manager"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost"})


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddLampRequest(_StrictModel):
    ip: str = Field(min_length=1, max_length=45)


class CommandRequest(_StrictModel):
    action: str = Field(min_length=1, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)


class WifiRequest(_StrictModel):
    ip: str = Field(min_length=1, max_length=45)
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)
    enable_lan_control: bool = False
    confirm: bool = False


class LanControlRequest(_StrictModel):
    ip: str = Field(min_length=1, max_length=45)
    confirm: bool = False


class PairRequest(_StrictModel):
    code: str = Field(min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=60)


def _require_local_header(
    x_yeelight_manager: str | None = Header(default=None, alias=LOCAL_API_HEADER),
) -> None:
    if x_yeelight_manager != "1":
        raise HTTPException(
            status_code=403,
            detail=f"Send the header {LOCAL_API_HEADER}: 1 with state-changing requests.",
        )


def create_local_app(
    service: Any, *, allow_clients: frozenset[str] | None = None
) -> FastAPI:
    """Build the manager's local FastAPI application.

    ``service`` is a :class:`~yeelight_manager.service.ManagerService`-like
    object.  ``allow_clients`` exists for tests; production always uses loopback
    client addresses.
    """

    allowed_clients = allow_clients or LOOPBACK_CLIENTS
    app = FastAPI(
        title="Yeelight Manager (local)",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = service

    @app.middleware("http")
    async def restrict_to_local(request: Request, call_next):  # type: ignore[no-untyped-def]
        client = request.client.host if request.client else ""
        if client not in allowed_clients:
            return JSONResponse(
                status_code=403,
                content={"detail": "The manager API is available on loopback only."},
            )
        origin = request.headers.get("origin")
        if origin:
            host = (urlsplit(origin).hostname or "").lower()
            if host not in LOOPBACK_HOSTS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin requests are not allowed."},
                )
        return await call_next(request)

    @app.exception_handler(YeelightLogicError)
    async def logic_error_handler(  # type: ignore[no-untyped-def]
        request: Request, exc: YeelightLogicError
    ):
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": exc.info.code},
        )

    @app.exception_handler(PairingError)
    async def pairing_error_handler(  # type: ignore[no-untyped-def]
        request: Request, exc: PairingError
    ):
        status_code = exc.status_code if 400 <= exc.status_code < 600 else 502
        return JSONResponse(
            status_code=status_code,
            content={"detail": str(exc), "code": "pairing_error"},
        )

    read_router = APIRouter()
    write_router = APIRouter(dependencies=[Depends(_require_local_header)])

    @read_router.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @read_router.get("/api/status")
    def status() -> dict[str, Any]:
        return service.snapshot()

    @read_router.get("/api/lamps")
    def lamps() -> dict[str, Any]:
        states = service.runtime.lamp_states()
        return {"lamps": states, "count": len(states)}

    @write_router.post("/api/lamps/discover")
    def discover() -> Any:
        result = service.runtime.discover()
        if not result.ok:
            return JSONResponse(
                status_code=502, content=result.to_dict()
            )
        bulbs = (result.data or {}).get("bulbs") or []
        return {"ok": True, "bulbs": bulbs, "count": len(bulbs)}

    @write_router.post("/api/lamps")
    def add_lamp(payload: AddLampRequest) -> Any:
        result = service.runtime.add_lamp(payload.ip)
        return JSONResponse(
            status_code=200 if result.ok else 400, content=result.to_dict()
        )

    @write_router.delete("/api/lamps/{ip}")
    def remove_lamp(ip: str) -> Any:
        result = service.runtime.remove_lamp(ip)
        return JSONResponse(
            status_code=200 if result.ok else 400, content=result.to_dict()
        )

    @write_router.post("/api/lamps/{ip}/command")
    def run_command(ip: str, payload: CommandRequest) -> Any:
        result = service.runtime.run_action(payload.action, ip, payload.params)
        return JSONResponse(
            status_code=200 if result.ok else 400, content=result.to_dict()
        )

    @write_router.post("/api/provisioning/wifi")
    def provision_wifi(payload: WifiRequest) -> dict[str, Any]:
        result = service.runtime.provision_wifi(
            payload.ip,
            payload.ssid,
            payload.password,
            enable_lan_control=payload.enable_lan_control,
            confirm=payload.confirm,
        )
        return {"ok": True, "result": result.to_dict()}

    @write_router.post("/api/provisioning/lan-control")
    def provision_lan_control(payload: LanControlRequest) -> dict[str, Any]:
        result = service.runtime.provision_lan_control(
            payload.ip, confirm=payload.confirm
        )
        return {"ok": True, "result": result.to_dict()}

    @write_router.post("/api/pair")
    def pair(payload: PairRequest) -> dict[str, Any]:
        outcome = service.pair(payload.code, name=payload.name)
        return {"ok": True, **outcome.describe()}

    @write_router.post("/api/unpair")
    def unpair() -> dict[str, Any]:
        removed = service.unpair()
        return {"ok": True, "was_paired": bool(removed)}

    @write_router.post("/api/reconnect")
    def reconnect() -> dict[str, Any]:
        service.reconnect()
        return {"ok": True}

    app.include_router(read_router)
    app.include_router(write_router)
    return app


__all__ = [
    "LOCAL_API_HEADER",
    "LOOPBACK_CLIENTS",
    "LOOPBACK_HOSTS",
    "create_local_app",
]
