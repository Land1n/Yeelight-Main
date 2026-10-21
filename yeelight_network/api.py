from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import secrets
import shlex
import time
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from yeelight_logic import CommandError, DeviceError, StorageError, YeelightController
from yeelight_network.miio import (
    MiIOError,
    configure_wifi,
    enable_lan_control,
    is_valid_wifi_password,
)
from yeelight_network.modes import ModeStore


logger = logging.getLogger(__name__)

MAX_MODE_FAILURES = 10


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class ModeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    delay_seconds: float = Field(default=1.0, ge=0.1, le=3600)


class ModeStartRequest(BaseModel):
    ip: str


class WifiSetupRequest(BaseModel):
    ip: str = Field(min_length=7, max_length=45)
    ssid: str = Field(min_length=1, max_length=32)
    password: SecretStr
    enable_lan_control: bool = False


class LanControlRequest(BaseModel):
    ip: str = Field(min_length=7, max_length=45)
    confirmed: bool = False


def _miio_error_message(error: MiIOError) -> str:
    messages = {
        "handshake_timeout": "Лампа не ответила на miIO handshake.",
        "handshake_invalid": "Лампа ответила, но handshake имеет некорректный формат.",
        "token_unavailable": (
            "Лампа ответила на miIO handshake, но не предоставила пригодный токен. "
            "Это не означает, что лампа недоступна по сети. Попробуйте включить "
            "LAN Control на этапе первоначальной настройки или используйте "
            "поддерживаемый способ получения токена."
        ),
        "info_timeout": "Лампа ответила на handshake, но не ответила на miIO.info.",
        "response_unconfirmed": (
            "Лампа ответила на команду, но не подтвердила включение LAN Control."
        ),
        "unsupported_model": (
            "Модель не поддерживается. Настройка доступна только для "
            "yeelink.light.color1."
        ),
        "info_rejected": "Лампа отклонила запрос miIO.info.",
        "invalid_device_info": "Лампа ответила, но данные miIO.info некорректны.",
        "transport_error": "Не удалось обменяться пакетами miIO с лампой.",
    }
    return messages.get(
        error.code,
        "Лампа ответила некорректно или не ответила на запрос miIO.",
    )


def _wifi_status_message(status: str, error: str | None = None) -> str:
    messages = {
        "sent_unconfirmed": (
            "Запрос настройки Wi-Fi отправлен, но лампа не подтвердила его. "
            "Подключите компьютер к целевой сети и проверьте лампу."
        ),
        "responded_unverified": (
            "Лампа ответила на запрос настройки Wi-Fi, но подключение к сети "
            "ещё не подтверждено."
        ),
        "rejected": "Лампа отклонила запрос настройки Wi-Fi.",
    }
    if status == "failed":
        if error == "transport_error":
            return (
                "Не удалось отправить запрос настройки Wi-Fi или получить ответ "
                "от лампы."
            )
        return (
            "Ответ на запрос настройки Wi-Fi некорректен или не относится к "
            "этому запросу. Результат подключения неизвестен."
        )
    return messages.get(
        status,
        "Неизвестный результат настройки Wi-Fi; проверьте лампу.",
    )


def _lan_control_status_message(status: str, error: str | None = None) -> str:
    if status == "not_requested":
        return "Попытка включения LAN Control не запрашивалась."
    if status == "rejected":
        return "Лампа отклонила команду включения LAN Control."
    if status == "sent_unconfirmed":
        return (
            "Команда LAN Control отправлена до настройки Wi-Fi, но ответ не "
            "получен. Включение не подтверждено."
        )
    if status == "responded_unverified":
        return (
            "Лампа ответила на команду LAN Control, но включение ещё не "
            "подтверждено. Проверьте TCP 55443, SSDP и get_prop после подключения."
        )
    if error == "transport_error":
        return (
            "Не удалось отправить или проверить команду LAN Control; настройка "
            "Wi-Fi будет продолжена."
        )
    return (
        "Ответ команды LAN Control некорректен или не подтверждает включение; "
        "настройка Wi-Fi будет продолжена."
    )


def _require_loopback(request: Request, detail: str) -> None:
    """Разрешить чувствительный маршрут только с этого компьютера."""

    peer = request.client.host if request.client else ""
    try:
        if ipaddress.ip_address(peer).is_loopback:
            return
    except ValueError:
        pass
    raise HTTPException(status_code=403, detail=detail)


def create_app(
    controller: YeelightController | None = None,
    api_token: str | None = None,
    poll_interval: float = 10.0,
    offline_timeout: float = 60.0,
    modes_path: str | Path | None = None,
) -> FastAPI:
    if not all(
        math.isfinite(value) and value > 0
        for value in (poll_interval, offline_timeout)
    ):
        raise ValueError("Polling interval and offline timeout must be positive")

    service = controller or YeelightController()
    last_seen: dict[str, float] = {}
    failed_since: dict[str, float] = {}
    bulb_status: dict[str, bool | None] = {}
    store = ModeStore(modes_path)
    modes = store.modes
    mode_tasks: dict[str, asyncio.Task[None]] = {}


    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        monitor_task = asyncio.create_task(monitor_bulbs())
        try:
            yield
        finally:
            tasks = [*mode_tasks.values(), monitor_task]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Yeelight Network", version="0.1.0", lifespan=lifespan)
    static_dir = Path(str(files("yeelight_app").joinpath("static")))
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    async def authorize(x_api_token: str | None = Header(default=None)) -> None:
        if api_token and (
            x_api_token is None or not secrets.compare_digest(x_api_token, api_token)
        ):
            raise HTTPException(status_code=401, detail="A valid X-API-Token is required")

    async def monitor_bulbs() -> None:
        while True:
            checked_at = time.monotonic()
            for item in service.known_bulbs():
                address = item["ip"]
                try:
                    await run_in_threadpool(service.execute, f"status {address}")
                    last_seen[address] = time.time()
                    failed_since.pop(address, None)
                    bulb_status[address] = True
                except (CommandError, DeviceError):
                    if address not in {
                        item["ip"] for item in service.known_bulbs()
                    }:
                        failed_since.pop(address, None)
                        last_seen.pop(address, None)
                        bulb_status.pop(address, None)
                        continue
                    bulb_status[address] = False
                    unavailable_at = failed_since.setdefault(address, checked_at)
                    if checked_at - unavailable_at >= offline_timeout:
                        try:
                            service.remove(address)
                        except CommandError:
                            logger.info(
                                "Lamp %s was removed while its status was being checked",
                                address,
                            )
                        except StorageError:
                            logger.exception(
                                "Could not persist removal of unavailable lamp %s",
                                address,
                            )
                            continue
                        failed_since.pop(address, None)
                        last_seen.pop(address, None)
                        bulb_status.pop(address, None)
            await asyncio.sleep(poll_interval)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    def serve_page(filename: str) -> FileResponse:
        page = static_dir / filename
        if not page.is_file():
            raise HTTPException(status_code=500, detail="Web client files are missing")
        return FileResponse(page, media_type="text/html")

    @app.get("/", include_in_schema=False)
    async def web_client() -> FileResponse:
        return serve_page("index.html")

    @app.get("/bulbs", include_in_schema=False)
    async def bulbs_page() -> FileResponse:
        return serve_page("bulbs.html")

    @app.get("/modes", include_in_schema=False)
    async def modes_page() -> FileResponse:
        return serve_page("modes.html")

    @app.get("/console", include_in_schema=False)
    async def console_page() -> FileResponse:
        return serve_page("console.html")

    @app.get("/setup", include_in_schema=False)
    async def setup_page() -> FileResponse:
        return serve_page("setup.html")

    @app.get("/help", include_in_schema=False)
    async def help_page() -> FileResponse:
        return serve_page("help.html")

    @app.get("/api/bulbs", dependencies=[Depends(authorize)])
    async def bulbs() -> dict[str, Any]:
        return {
            "bulbs": [
                {
                    **bulb,
                    "online": bulb_status.get(bulb["ip"]),
                    "last_seen": last_seen.get(bulb["ip"]),
                }
                for bulb in service.known_bulbs()
            ]
        }

    @app.get("/api/settings", dependencies=[Depends(authorize)])
    async def settings() -> dict[str, float]:
        return {
            "poll_interval_seconds": poll_interval,
            "offline_timeout_seconds": offline_timeout,
        }

    @app.post("/api/provisioning/wifi", dependencies=[Depends(authorize)])
    async def provision_wifi(request: Request, setup: WifiSetupRequest) -> dict[str, str]:
        _require_loopback(request, "Wi-Fi setup is only allowed from this computer.")

        if len(setup.ssid.encode("utf-8")) > 32 or "\x00" in setup.ssid:
            raise HTTPException(status_code=422, detail="Invalid Wi-Fi network name.")
        password = setup.password.get_secret_value()
        if not is_valid_wifi_password(password):
            setup.password = SecretStr("")
            password = ""
            raise HTTPException(
                status_code=422,
                detail="Wi-Fi password must be 8–63 bytes or a 64-digit hexadecimal key.",
            )
        try:
            result = await run_in_threadpool(
                configure_wifi,
                setup.ip,
                setup.ssid,
                password,
                enable_lan_control=setup.enable_lan_control,
            )
        except MiIOError as exc:
            message = _miio_error_message(exc)
            lan_control_status = (
                "not_attempted" if setup.enable_lan_control else "not_requested"
            )
            lan_control_message = (
                f"Попытка LAN Control не выполнена: {message}"
                if setup.enable_lan_control
                else _lan_control_status_message(lan_control_status)
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "message": message,
                    "wifi_status": "not_sent",
                    "lan_control_status": lan_control_status,
                    "lan_control_message": lan_control_message,
                },
            ) from exc
        finally:
            password = ""
            setup.password = SecretStr("")

        return {
            "status": result.wifi_status,
            "message": _wifi_status_message(
                result.wifi_status,
                result.wifi_error,
            ),
            "lan_control_status": result.lan_control_status,
            "lan_control_message": _lan_control_status_message(
                result.lan_control_status,
                result.lan_control_error,
            ),
        }

    @app.post("/api/provisioning/lan-control", dependencies=[Depends(authorize)])
    async def provision_lan_control(
        request: Request, setup: LanControlRequest
    ) -> dict[str, str]:
        _require_loopback(request, "LAN Control setup is only allowed from this computer.")

        if not setup.confirmed:
            raise HTTPException(
                status_code=422,
                detail="Explicit confirmation is required to enable LAN Control.",
            )

        try:
            outcome = await run_in_threadpool(enable_lan_control, setup.ip)
        except MiIOError as exc:
            raise HTTPException(
                status_code=400,
                detail=_miio_error_message(exc),
            ) from exc

        messages = {
            "sent_unconfirmed": (
                "Команда отправлена, но ответа лампы нет. Включение не подтверждено."
            ),
            "responded_unverified": (
                "Лампа ответила на команду, но это ещё не подтверждает LAN Control. "
                "Проверьте TCP 55443, SSDP и get_prop."
            ),
            "rejected": "Лампа отклонила команду включения LAN Control.",
        }
        return {"status": outcome, "message": messages[outcome]}

    @app.post("/api/commands", dependencies=[Depends(authorize)])
    async def command(request: CommandRequest) -> dict[str, Any]:
        try:
            parts = shlex.split(request.command)
        except ValueError:
            parts = []
        address = parts[1] if len(parts) > 1 else None
        try:
            result = await run_in_threadpool(service.execute, request.command)
            if parts and parts[0] == "remove" and address is not None:
                bulb_status.pop(address, None)
                failed_since.pop(address, None)
                last_seen.pop(address, None)
            elif parts and parts[0] == "add" and address is not None:
                bulb_status.setdefault(address, None)
            elif address is not None and any(
                item["ip"] == address for item in service.known_bulbs()
            ):
                bulb_status[address] = True
                failed_since.pop(address, None)
                last_seen[address] = time.time()
            return {"ok": True, "result": result}
        except CommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except StorageError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except DeviceError as exc:
            if address is not None and any(
                item["ip"] == address for item in service.known_bulbs()
            ):
                bulb_status[address] = False
                failed_since.setdefault(address, time.monotonic())
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/modes", dependencies=[Depends(authorize)])
    async def list_modes() -> dict[str, Any]:
        return {
            "modes": [
                {
                    **mode,
                    "running": name in mode_tasks and not mode_tasks[name].done(),
                }
                for name, mode in sorted(modes.items())
            ]
        }

    @app.post("/api/modes", dependencies=[Depends(authorize)])
    async def save_mode(request: ModeRequest) -> dict[str, Any]:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Mode name cannot be blank")
        if "/" in name or "\\" in name:
            raise HTTPException(status_code=422, detail="Mode name cannot contain path separators")
        if name in mode_tasks and not mode_tasks[name].done():
            raise HTTPException(status_code=409, detail="Stop the mode before editing it")
        try:
            mode = store.put(name, request.steps, request.delay_seconds)
        except (CommandError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not save modes") from exc
        return {"ok": True, "mode": mode}

    @app.delete("/api/modes/{name}", dependencies=[Depends(authorize)])
    async def delete_mode(name: str) -> dict[str, bool]:
        if name not in modes:
            raise HTTPException(status_code=404, detail="Mode not found")
        task = mode_tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            store.delete(name)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Could not save modes") from exc
        return {"ok": True}

    @app.post("/api/modes/{name}/start", dependencies=[Depends(authorize)])
    async def start_mode(name: str, request: ModeStartRequest) -> dict[str, str]:
        mode = modes.get(name)
        if mode is None:
            raise HTTPException(status_code=404, detail="Mode not found")
        try:
            parsed_address = ipaddress.ip_address(request.ip)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Enter a valid lamp IP address") from exc
        if parsed_address.version != 4:
            raise HTTPException(status_code=422, detail="Yeelight supports IPv4 addresses only")
        address = str(parsed_address)
        if address not in {item["ip"] for item in service.known_bulbs()}:
            raise HTTPException(status_code=404, detail="Add the lamp to the list before starting a mode")
        task = mode_tasks.get(name)
        if task is not None and not task.done():
            raise HTTPException(status_code=409, detail="Mode is already running")
        mode["last_error"] = None
        mode["running_ip"] = address

        async def repeat_commands() -> None:
            failures = 0
            try:
                bulb = service.bulb_for(address)
                while True:
                    for step in mode["steps"]:
                        action = step["action"]
                        args = [address, *(str(value) for value in step["values"])]
                        line = " ".join([action, *args])
                        try:
                            await run_in_threadpool(service.execute, line, bulb)
                        except DeviceError as exc:
                            failures += 1
                            mode["last_error"] = str(exc)
                            if failures >= MAX_MODE_FAILURES:
                                return
                            await asyncio.sleep(max(mode["delay_seconds"], 1.0))
                            continue
                        except Exception as exc:
                            mode["last_error"] = str(exc)
                            return
                        failures = 0
                        mode["last_error"] = None
                        await asyncio.sleep(mode["delay_seconds"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                mode["last_error"] = str(exc)
            finally:
                mode["running_ip"] = None

        mode_tasks[name] = asyncio.create_task(repeat_commands())
        return {"status": "started", "ip": address}

    @app.post("/api/modes/{name}/stop", dependencies=[Depends(authorize)])
    async def stop_mode(name: str) -> dict[str, str]:
        if name not in modes:
            raise HTTPException(status_code=404, detail="Mode not found")
        task = mode_tasks.get(name)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"status": "stopped"}

    return app
